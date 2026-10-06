"""Sandbox helper functions."""
from __future__ import annotations
from src.models.sandbox_config import SandboxConfig
from typing import Any, Callable
import os
import signal
import resource
import json
import struct


def _tool_proxy(name: str, out_fd: int, in_fd: int) -> Callable[..., Any]:
    """Build a stub that forwards a call to the parent's MCP client.

    The interval timer is cancelled across the round trip and the
    remainder restored afterwards, so a tool spawning a container does
    not burn the snippet's exectuion budget.
    """
    def proxy(**kwargs: Any) -> Any:
        """Proxy the tools."""
        remaining, _ = signal.setitimer(signal.ITIMER_REAL, 0.0)
        try:
            _send(out_fd, {
                "kind": "tool_call", "name": name, "arguments": kwargs,
            })
            reply = _recv(in_fd)
        finally:
            if remaining > 0:
                signal.setitimer(signal.ITIMER_REAL, remaining)
        if reply.get("error") is not None:
            print(reply)
            raise RuntimeError(f"tool {name!r} failed: {reply['error']}")
        return reply.get("result")
    proxy.__name__ = name
    proxy.__doc__ = f"MCP tool {name!r}, executed outside the sandbox."
    return proxy


def _apply_limits(config: SandboxConfig) -> None:
    """Drop privileges, Hard limits only go down.

    RLIMIT_AS caps virtual address space, which is what makes a runaway
    allocation raise MemoryError instead of swapping the machine.
    """
    max_bytes = config.max_memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (max_bytes, max_bytes))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))


def _disable_network() -> None:
    """Neuter sockets in the child, in case a module reaches one."""
    try:
        import socket
    except ImportError:
        return

    def blocked(*_a: Any, **_k: Any) -> Any:
        raise PermissionError("network access is disabled")

    socket.socket = blocked  # type: ignore[assignment,misc]
    socket.create_connection = blocked  # type: ignore[assignment]
    socket.getaddrinfo = blocked  # type: ignore[assignment]


class _Timeout(Exception):
    """Raised for timeout when too long. SIGALRM handler in child."""


def _on_alarm(*_args: Any) -> None:
    """Raise timeout."""
    raise _Timeout()


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    """Cap text, stating what was dropped.

    The marker matters: without it the LLM treats a cut-off result as
    complete and reasons from a false premise.
    """
    if len(text) <= limit:
        return text, False
    dropped = len(text) - limit
    marked = (
        f"{text[:limit]}\n[output truncated: {dropped} of {len(text)} "
        f"characters omitted; narrow your request to see the rest]"
    )
    return marked, True


# send to child/parent
def _send(fd: int, message: dict[str, Any]) -> None:
    """Write one length-prefixed JSON message.

    fd is the legnth of the message.
    """
    payload = json.dumps(message).encode("utf-8")
    data = memoryview(struct.pack("!I", len(payload)) + payload)
    while data:
        data = data[os.write(fd, data):]


# receieve from child/parent
def _recv(fd: int) -> dict[str, Any]:
    """Read one length-prefixed JSON message."""
    def read_exactly(size: int) -> bytes:
        """Read exactly amount of bytes."""
        chunks: list[bytes] = []
        while size:
            chunk = os.read(fd, size)
            if not chunk:
                raise EOFError("pipe closed")
            chunks.append(chunk)
            size -= len(chunk)
        return b"".join(chunks)

    (length,) = struct.unpack("!I", read_exactly(4))
    return json.loads(read_exactly(length).decode("utf-8"))

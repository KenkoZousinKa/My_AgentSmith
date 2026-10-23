"""Sandbox helper functions."""
from __future__ import annotations
from src.models.sandbox_config import SandboxConfig
from typing import Any, Callable
import os
import sys
import signal
import resource
import json
import struct
import re


def tool_proxy(name: str, out_fd: int, in_fd: int) -> Callable[..., Any]:
    """Build a stub that forwards a call to the parent's MCP client.

    The interval timer is cancelled across the round trip and the
    remainder restored afterwards, so a tool spawning a container does
    not burn the snippet's exectuion budget.
    """
    def proxy(**kwargs: Any) -> Any:
        """Proxy the tools."""
        remaining, _ = signal.setitimer(signal.ITIMER_REAL, 0.0)
        try:
            send(out_fd, {
                "kind": "tool_call", "name": name, "arguments": kwargs,
            })
            reply = recv(in_fd)
        finally:
            if remaining > 0:
                signal.setitimer(signal.ITIMER_REAL, remaining)
        if reply.get("error") is not None:
            raise RuntimeError(f"tool {name!r} failed: {reply['error']}")
        return reply.get("result")
    proxy.__name__ = name
    proxy.__doc__ = f"MCP tool {name!r}, executed outside the sandbox."
    return proxy


def scrub_environment() -> None:
    """Drop every inhgerited envrionment variable in the child.

    Scrubs the .env from the namespace created from the agent process.
    """
    os.environ.clear()


def apply_limits(config: SandboxConfig) -> None:
    """Drop privileges, Hard limits only go down.

    RLIMIT_AS caps virtual address space, which is what makes a runaway
    allocation raise MemoryError instead of swapping the machine.
    """
    max_bytes = config.max_memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (max_bytes, max_bytes))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
    except (ValueError, OSError):
        pass


_DENIED_EVENTS = frozenset({
    "os.system", "os.exec", "os.spawn", "os.fork", "os.forkpty",
    "os.posix_spawn", "os.putenv", "os.unsetenv", "os.startfile",
    "subprocess.Popen",
    "socket.socket", "socket.connect", "socket.bind", "socket.getaddrinfo",
    "ctypes.dlopen", "ctypes.dlsym", "ctypes.call_function", "ctypes.cdata",
    "ctypes.set_errno",
    "gc.get_objects", "gc.get_referrers", "gc.get_referents",
    "resource.setrlimit",
})


_WRITE_PATH_EVENTS = frozenset({
    "os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.unlink",
    "os.link", "os.symlink", "os.chmod", "os.chown", "os.truncate",
    "shutil.copyfile", "shutil.copymode", "shutil.copystat",
    "shutil.move", "shutil.rmtree",
})


_LISTDIR_EVENTS = frozenset({"os.listdir", "os.scandir"})


_W_FLAGS = (
    os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
)


def norm_roots(paths: Any) -> tuple[str, ...]:
    """Absolute, symlink-resolved roots for prefix comparison."""
    roots = []
    for p in paths:
        if not p:
            continue
        try:
            roots.append(os.path.realpath(p))
        except OSError:
            continue
    return tuple(roots)


def under(path: Any, roots: tuple[str, ...]) -> bool:
    """Return true if path resolves to somewhere inside one of the roots."""
    try:
        real = os.path.realpath(os.fsdecode(path))
    except (OSError, TypeError, ValueError):
        return False
    for root in roots:
        if real == root or real.startswith(root + os.sep):
            return True
    return False


def is_write(mode: Any, flags: Any) -> bool:
    """Decide whether an 'open' event is for writing."""
    if isinstance(mode, str) and mode:
        return any(c in mode for c in "wax+") is True
    if isinstance(flags, int):
        return bool(flags & _W_FLAGS)
    return False


def install_audit_hook(config: SandboxConfig) -> None:
    """Install the deny-by-operation hook.

    After this, the child's code cannot write outside the allow list.
    """
    write_roots = norm_roots(config.allowed_directories)
    read_roots = write_roots + norm_roots({
        sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix,
        *sys.path
    })

    def hook(event: str, args: tuple[Any, ...]) -> None:
        """Check to see if the action the code is legal."""
        if event in _DENIED_EVENTS:
            raise PermissionError(
                f"operation {event!r} is not allowed in sandbox."
            )
        if event == "open":
            path, mode, flags = args
            if isinstance(path, int):
                raise PermissionError(
                    "opening a raw file descriptor is not allowed."
                )
            if is_write(mode, flags):
                if not under(path, write_roots):
                    raise PermissionError(f"write outside allowlist: {path}")
            elif not under(path, read_roots):
                raise PermissionError(f"read outside allowlist: {path}")
        elif event in _WRITE_PATH_EVENTS:
            if args and not under(args[0], write_roots):
                raise PermissionError(f"write outside allowlist: {args[0]}")
        elif event in _LISTDIR_EVENTS:
            if args and args[0] is not None and not under(
                args[0], write_roots
            ):
                raise PermissionError(f"listing outside allowlist: {args[0]}")

    sys.addaudithook(hook)


def disable_network() -> None:
    """Neuter sockets in the child, in case a module reaches one."""

    def blocked(*_a: Any, **_k: Any) -> Any:
        """Refuse every socket operation."""
        raise PermissionError("network access is disabled")

    for mod_name in ("socket", "_socket"):
        try:
            mod = __import__(mod_name)
        except ImportError:
            continue
        for attr in (
            "socket", "socketpair", "SocketType", "fromfd",
            "create_connection", "getaddrinfo", "gethostbyname"
        ):
            if hasattr(mod, attr):
                try:
                    setattr(mod, attr, blocked)
                except (AttributeError, TypeError):
                    pass


class Timeout(BaseException):
    """Raised for timeout when too long. SIGALRM handler in child."""


def on_alarm(*_args: Any) -> None:
    """Raise timeout."""
    raise Timeout()


def truncate(text: str, limit: int) -> tuple[str, bool]:
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
def send(fd: int, message: dict[str, Any]) -> None:
    """Write one length-prefixed JSON message.

    fd is the legnth of the message.
    """
    payload = json.dumps(message).encode("utf-8")
    data = memoryview(struct.pack("!I", len(payload)) + payload)
    while data:
        data = data[os.write(fd, data):]


# receieve from child/parent
def recv(fd: int) -> dict[str, Any]:
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
    message: dict[str, Any] = json.loads(read_exactly(length).decode("utf-8"))
    return message


def py_name(name: str) -> str:
    """Check if name is a callable MCP tool."""
    cleaned = re.sub(r"\W", "_", name)
    return f"tool_{cleaned}" if cleaned[:1].isdigit() else cleaned


def catalog_relays(out_fd: int, in_fd: int) -> dict[str, Callable[..., Any]]:
    """Build read_resource and get_prompt stubs for the child namespace.

    Same round trip as tool call: pause the execution timer, send the
    request over the pipe, wait for the parent to hit the MCP client,
    then restore the time. The work happens outside the sandbox, so it
    does not count against the snippet's time budget.
    """

    def _send_recv(message: dict[str, Any]) -> Any:
        """Send and recieve across the pipeline."""
        remaining, _ = signal.setitimer(signal.ITIMER_REAL, 0.0)
        try:
            send(out_fd, message)
            reply = recv(in_fd)
        finally:
            if remaining > 0:
                signal.setitimer(signal.ITIMER_REAL, remaining)
        if reply.get("error") is not None:
            raise RuntimeError(reply["error"])
        return reply.get("result")

    def read_resource(uri: str) -> Any:
        """Read an mcp resource by uri (runs outside the sandbox)."""
        return _send_recv({"kind": "resource_read", "uri": uri})

    def get_prompt(
            name: str, arguments: dict[str, str] | None = None
    ) -> Any:
        """Fetch an MCP prompt by name (runs outside the sandbox)."""
        return _send_recv({
            "kind": "prompt_get", "name": name, "arguments": arguments
        })

    return {"read_resource": read_resource, "get_prompt": get_prompt}





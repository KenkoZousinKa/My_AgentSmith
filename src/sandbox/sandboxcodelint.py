"""A test version of the Sandbox. much looser error checks."""

from __future__ import annotations

import argparse
import ast
import builtins
import io
import signal
import traceback
import select
import os
import json
import struct
import resource
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import Any, Callable
from pydantic import BaseModel, Field


class SandboxConfig(BaseModel):
    """Sandbox configuration for student solutions.

    Uses allowlist approach: only imports in authorized_imports are
    allowed. Everything else is blocked by default.
    """
    authorized_imports: list[str] = Field(default_factory=lambda: [
        "math", "math.*",
        "collections", "collections.*",
        "itertools", "re", "json",
        "typing", "typing.*",
        "functools", "operator",
        "heapq", "bisect", "copy",
        "string", "random",
        "datetime", "datetime.*",
        "array", "cmath",
    ])
    allowed_directories: list[str] = Field(default_factory=lambda: [
        "/testbed", "/tmp/agent"
    ])
    max_execution_time_seconds: int = 30
    max_memory_mb: int = 512
    max_output_chars: int = 8000


class ExecuteResult(BaseModel):
    """Outcome of one part.

    Its either pass error or standard code compile.
    """
    stdout: str = ""
    stderr: str = ""
    value: str | None = None
    error: str | None = None
    final_answer: str | None = None


class FinalAnswer(BaseException):
    """Task complete signal.

    BaseException so generated code wrapping its work
    in try/except Exception cannot eat it.
    """
    def __init__(self, value: Any) -> None:
        """Init self with base exception inheritance."""
        super().__init__(value)
        self.value = value


class _Timeout(Exception):
    """Raised for timeout when too long. SIGALRM handler in child."""


_BLOCKED = frozenset({
    "eval", "exec", "compile", "__import__", "globals", "locals", "vars",
    "getattr", "setattr", "breakpoint", "input", "exit", "quit",
})


def _allowed(name: str, authorized: frozenset[str]) -> bool:
    """Match a module name against the allowlist."""
    return name in authorized or any(
        e.endswith(".*") and (name == e[:-2] or name.startswith(e[:-1]))
        for e in authorized
    )


def _truncate(text: str, limit: int) -> str:
    """Cap text, stating what was dropped.

    The marker matters: without it the LLM treats a cut-off result as
    complete and reasons from a false premise.
    """
    if len(text) <= limit:
        return text
    dropped = len(text) - limit
    return (
        f"{text[:limit]}\n[output truncated: {dropped} of {len(text)} "
        f"characters omitted; narrow your request to see the rest]"
    )


class _Checker(ast.NodeVisitor):
    """Static pass: cheap rejection before anything happens."""
    def __init__(
        self,
        authorized: frozenset[str],
        tool_names: frozenset[str] = frozenset()
    ) -> None:
        """Record the allowlist, the tool nams, and any rejections."""
        self.authorized: frozenset[str] = authorized
        self.tool_names = tool_names
        self.errors: list[str] = []

    def _check_module(self, name: str) -> None:
        """Check if importing named module is allowed."""
        if not _allowed(name, self.authorized):
            self.errors.append(f"import of {name!r} is not allowed")

    def visit_Import(self, node: ast.Import) -> None:
        """Visit all nodes."""
        for alias in node.names:
            self._check_module(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Visit from-imports and reject relative ones."""
        if node.level:
            self.errors.append("relative imports are not allowed")
        elif node.module:
            self._check_module(node.module)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Blocks dunder access, which reaches globals and subclasses."""
        if node.attr.startswith("__") and node.attr.endswith("__"):
            self.errors.append(f"access to dunder attribute {node.attr!r}")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        """Check names, letting injectted tools shadow blocked bultins.

        An unknown MCP server may expose a tools that aren't allowed.
        """
        if node.id in _BLOCKED and node.id not in self.tool_names:
            self.errors.append(f"use of {node.id!r} is not allowed")
        self.generic_visit(node)


def check_code(
    code: str,
    config: SandboxConfig,
    tool_names: frozenset[str] = frozenset()
) -> str | None:
    """Return a rejection reason, or None if the code is okay."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"SyntaxError: {exc.msg} (line {exc.lineno})"
    checker = _Checker(frozenset(config.authorized_imports), tool_names)
    checker.visit(tree)
    return "; ".join(checker.errors) or None


# send to child/parent
def _send(fd: int, message: dict[str, Any]) -> None:
    """Write one length-prefixed JSON message."""
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


def _guarded_open(config: SandboxConfig) -> Callable[..., Any]:
    """Build an open() restricted to allowed_directories."""
    roots = [Path(d).resolve() for d in config.allowed_directories]
    real = builtins.open

    def guard(file: Any, mode: str = "r", *args: Any, **kw: Any) -> Any:
        """Resolve the path, then allow only inside allowlist."""
        if isinstance(file, int):
            raise PermissionError("Raw file descriptors are not allowed")
        target = Path(os.fsdecode(file)).resolve()
        if not any(target == r or target.is_relative_to(r) for r in roots):
            raise PermissionError(f"path outside allowlist: {target}")
        return real(target, mode, *args, **kw)

    return guard


def _safe_builtins(config: SandboxConfig) -> dict[str, Any]:
    """Bultins minus the dangerous ones, plus guarded __import__.

    This must be set explicitly: exec() given a globals dict with no
    '__bultins__' key silently inserts the real bultins module.
    """
    safe: dict[str, Any] = {
        n: getattr(builtins, n)
        for n in dir(builtins) if not n.startswith("_") and n not in _BLOCKED
    }
    authorized = frozenset(config.authorized_imports)
    real = builtins.__import__

    def guarded(name: str, *args: Any, **kwargs: Any) -> Any:
        """Enforcement point: every import compiles to this."""
        if not _allowed(name, authorized):
            raise ImportError(f"import of {name!r} not allowed")
        return real(name, *args, **kwargs)

    safe["__import__"] = guarded
    safe["open"] = _guarded_open(config)
    return safe


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


def _on_alarm(*_args: Any) -> None:
    """Raise timeout."""
    raise _Timeout()


def _execute(
    code: str, namespace: dict[str, Any], config: SandboxConfig
) -> dict[str, Any]:
    """Run one snippet and describe what happened, as a dict."""
    timeout = config.max_execution_time_seconds
    tree = ast.parse(code)
    tail = (tree.body.pop()
            if tree.body and isinstance(tree.body[-1], ast.Expr) else None)
    body = compile(tree, "<sandbox>", "exec")

    out, err = io.StringIO(), io.StringIO()
    result: dict[str, Any] = {"kind": "ok", "value": None}
    signal.setitimer(signal.ITIMER_REAL, float(timeout))
    try:
        with redirect_stdout(out), redirect_stderr(err):
            exec(body, namespace)
            if tail is not None:
                expr = compile(
                    ast.Expression(tail.value), "<sandbox>", "eval"
                )
                value = eval(expr, namespace)
                if value is not None:
                    result["value"] = repr(value)
    except FinalAnswer as answer:
        result = {"kind": "final_answer", "value": str(answer.value)}
    except _Timeout:
        result = {"kind": "error", "error": (
            f"timeout after {timeout}s; any output above is partial"
        )}
    except MemoryError:
        result = {"kind": "error", "error": "memory limit exceeded"}
    except KeyboardInterrupt:
        result = {"kind": "interrupt"}
    except SystemExit as exc:
        result = {"kind": "exit", "code": str(exc.code or 0)}
    except BaseException:
        result = {"kind": "error", "error": traceback.format_exc(limit=5)}
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)

    limit = config.max_output_chars
    result["stdout"] = _truncate(out.getvalue(), limit)
    result["stderr"] = _truncate(err.getvalue(), limit)
    return result


def _child_main(
        config: SandboxConfig,
        cmd_fd: int,
        res_fd: int,
        tool_names: list[str]
) -> None:
    """Worker entry point. Never returns."""
    os.setsid()
    signal.signal(signal.SIGALRM, _on_alarm)
    _disable_network()

    def final_answer(value: Any = None) -> Any:
        """Flag for final answer."""
        raise FinalAnswer(value)

    namespace: dict[str, Any] = {
        "__name__": "__sandbox__",
        "__builtins__": _safe_builtins(config),
        "final_answer": final_answer,
    }
    for name in tool_names:
        namespace[name] = _tool_proxy(name, res_fd, cmd_fd)

    _apply_limits(config)

    while True:
        try:
            message = _recv(cmd_fd)
        except (EOFError, OSError):
            os._exit(0)
        if message.get("kind") != "run":
            os._exit(0)
        outcome = _execute(message["code"], namespace, config)
        try:
            _send(res_fd, outcome)
        except OSError:
            os._exit(1)


class Sandbox:
    """Runs snippets in an isolated child with a persistent namespace."""
    def __init__(
        self,
        config: SandboxConfig | None = None,
        tools: dict[str, Callable[..., Any]] | None = None
    ) -> None:
        """Init the Sandbox and fork its worker."""
        self.config = config or SandboxConfig()
        self.tools = tools or {}
        self._pid: int | None = None
        self._cmd_w = -1
        self._res_r = -1
        self._spawn()

    def _spawn(self) -> None:
        """Fork a worker and keep the parent endsd of both pipes."""
        sys.stdout.flush()
        sys.stderr.flush()
        cmd_r, cmd_w = os.pipe()
        res_r, res_w = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(cmd_w)
            os.close(res_r)
            try:
                _child_main(self.config, cmd_r, res_w, sorted(self.tools))
            finally:
                os._exit(1)
        os.close(cmd_r)
        os.close(res_w)
        self._pid, self._cmd_w, self._res_r = pid, cmd_w, res_r

    def reset(self) -> None:
        """Kill the worker and start a clean one (namespace is lost)."""
        self.close()
        self._spawn()

    def close(self) -> None:
        """Kill the worker's whole process group and reap it."""
        if self._pid is None:
            return
        try:
            os.close(self._cmd_w)
        except OSError:
            pass
        for kill in (
            lambda: os.killpg(self._pid, signal.SIGKILL),  # type: ignore[arg-type]
            lambda: os.kill(self._pid, signal.SIGKILL),  # type: ignore[arg-type]
        ):
            try:
                kill()
            except (ProcessLookupError, PermissionError):
                continue
        try:
            os.waitpid(self._pid, 0)
        except ChildProcessError:
            pass
        for fd in (self._cmd_w, self._res_r):
            try:
                os.close(fd)
            except OSError:
                pass
        self._pid = None

    def __enter__(self) -> "Sandbox":
        """Enter a context manager."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """Leave a context manager, killing the worker."""
        self.close()

    def run(self, code: str) -> ExecuteResult:
        """Check, exectue, and service tool calls untill the snippet ends."""
        rejection = check_code(code, self.config, frozenset(self.tools))
        if rejection:
            return ExecuteResult(error=rejection)

        try:
            _send(self._cmd_w, {"kind": "run", "code": code})
        except OSError:
            self.reset()
            return ExecuteResult(error="worker was dead; restarted")

        grace = self.config.max_execution_time_seconds + 5
        while True:
            ready, _, _ = select.select([self._res_r], [], [], grace)
            if not ready:
                self.reset()
                return ExecuteResult(
                    error="worker unresponsive; killed and restarted"
                )
            try:
                message = _recv(self._res_r)
            except (EOFError, OSError, ValueError):
                self.reset()
                return ExecuteResult(
                    error="worker died (likely memory limit); restarted"
                )
            if message.get("kind") == "tool_call":
                self._dispatch(message)
                continue
            return self._to_result(message)

    def _dispatch(self, message: dict[str, Any]) -> None:
        """Run one tool in the parent and send the reply back."""
        name = str(message.get("name", ""))
        handler = self.tools.get(name)
        reply: dict[str, Any] = {"result": None, "error": None}
        if handler is None:
            reply["error"] = f"unknown tool {name!r}"
        else:
            try:
                raw = handler(**(message.get("arguments") or {}))
                reply["result"] = (
                    _truncate(raw, self.config.max_output_chars)
                    if isinstance(raw, str) else raw
                )
            except Exception as exc:
                reply["error"] = f"{type(exc).__name__}: {exc}"
        _send(self._cmd_w, reply)

    @staticmethod
    def _to_result(message: dict[str, Any]) -> ExecuteResult:
        """Turn a terminal worker message into an ExecuteResult."""
        base = {
            "stdout": message.get("stdout", ""),
            "stderr": message.get("stderr", "")
        }
        kind = message.get("kind")
        if kind == "final_answer":
            return ExecuteResult(final_answer=message.get("value"), **base)
        if kind == "error":
            return ExecuteResult(error=message.get("error"), **base)
        if kind == "interrupt":
            raise KeyboardInterrupt
        if kind == "exit":
            raise SystemExit(message.get("code", 0))
        return ExecuteResult(value=message.get("value"), **base)


def _show(result: ExecuteResult) -> None:
    """Shows the result of the executed code."""
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="")
    if result.error:
        print(result.error)
    elif result.final_answer is not None:
        print(f"[final_answer] {result.final_answer}")
    elif result.value is not None:
        print(result.value)


def _repl(sandbox: Sandbox) -> int:
    """REPL-style mode: one entry per iteration, shared namespace."""
    print("sandbox - 'exit' or Ctrl-D to quit")
    while True:
        try:
            line = input(">>> ")
        except EOFError:
            print()
            return 0
        if line.strip() in {"exit", "quit"}:
            return 0
        if not line.strip():
            continue
        buffer = [line]
        while True:
            try:
                ast.parse("\n".join(buffer))
                break
            except SyntaxError:
                try:
                    more = input("... ")
                except EOFError:
                    return 0
                if not more.strip():
                    break
                buffer.append(more)
        try:
            _show(sandbox.run("\n".join(buffer)))
        except KeyboardInterrupt:
            print("\n[interrupted]")


def main() -> int:
    """Parse arguments and run a snippet, a file, or the REPL."""
    parser = argparse.ArgumentParser(prog="sandbox")
    parser.add_argument("config", nargs="?", help="JSON config file")
    parser.add_argument("--mcp-stdio", metavar="CMD",
                        help="command launching an MCP server over stdio")
    parser.add_argument("--mcp-server", metavar="URL",
                        help="streamable HTTP MCP server endpoint")
    parser.add_argument("-c", "--command", help="run one snippet and exit")
    parser.add_argument("-f", "--file", help="run a file and exit")
    args = parser.parse_args()

    config = (
        SandboxConfig.model_validate_json(
            Path(args.config).read_text(encoding="utf-8")
        )
        if args.config else SandboxConfig()
    )
    sandbox = Sandbox(config)
    try:
        if args.command is not None:
            _show(sandbox.run(args.command))
        elif args.file is not None:
            _show(sandbox.run(Path(args.file).read_text(encoding="utf-8")))
        else:
            return _repl(sandbox)
    finally:
        sandbox.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

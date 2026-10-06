"""The main entry for the sandbox."""

from __future__ import annotations
from src.models.sandbox_config import SandboxConfig
from src.sandbox.code_lint import check_code, _BLOCKED
from src.sandbox.sandbox_helper import _send, _recv, _truncate
from src.sandbox.sandbox_child import _child_main
from src.models.output import ExecuteResult
from src.sandbox.mcp_tool_function import MCPToolFunction
from src.sandbox.client import StdioMCPClient
from typing import Any, Callable
from pathlib import Path
import os
import ast
import sys
import select
import signal
import argparse


class Sandbox:
    """Runs snippets in an isolated child with a persistent namespace."""
    def __init__(
        self,
        config: SandboxConfig | None = None,
        tools: dict[str, Callable[..., Any]] | None = None
    ) -> None:
        """Init the Sandbox and fork its worker."""
        self.config = config or SandboxConfig()
        self.tools: dict[str, Callable[..., Any]] = tools or {}
        self._pid: int | None = None
        self._cmd_w = -1
        self._res_r = -1
        self._tool_truncated = False
        # self._spawn()

    def __enter__(self) -> "Sandbox":
        """Enter a context manager."""
        self.client = StdioMCPClient("python mcp_tools_mbpp.py")
        self.client.connect()
        self.tools = {t.name: MCPToolFunction(self.client, t) for t in self.client.list_tools()}
        self._spawn()

        return self

    def __exit__(self, *_exc: object) -> None:
        """Leave a context manager, killing the worker."""
        self.close()
        self.client.close()

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

    def run(self, code: str) -> ExecuteResult:
        """Check, exectue, and service tool calls untill the snippet ends."""
        rejection = check_code(code, self.config, frozenset(self.tools))
        if rejection:
            return ExecuteResult(error=rejection)

        self._tool_truncated = False
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

    def _tool_doc(self, name: str, tool: Any) -> str:
        """Render one tool as a Python-looking signature plus its docs."""
        input_schema: dict[str, Any] = getattr(tool, "input_schema", None) or {}
        props: dict[str, Any] = input_schema.get("properties") or {}
        required = set(input_schema.get("required") or [])
        types = {"string": "str", "integer": "int", "number": "float",
                 "boolean": "bool", "array": "list", "object": "dict"}

        params = []
        for arg, spec in props.items():
            hint = types.get(spec.get("type", ""), "Any")
            params.append(f"{arg}: {hint}" if arg in required
                          else f"{arg}: {hint} = ...")

        out = [f"{name}({', '.join(params)})"]
        description = getattr(tool, "description", "") or ""
        if description:
            out.append(f"   {description.strip()}")
        for arg, spec in props.items():
            if spec.get("description"):
                out.append(f"   - {arg}: {spec['description']}")
        return "\n".join(out)

    def manual(self) -> str:
        """Render the sandbox manual for the LLM's first prompt.

        Made from connected server.
        """
        lines = [
            "# Sandbox",
            "",
            "Your code runs in a restricted Python namespace.",
            "State persists between steps: names you define stay defined.",
            "",
            "## Rules",
            f"- Imports allowed: "
            f"{', '.join(sorted(self.config.authorized_imports))}",
            f"- File access limited to: "
            f"{', '.join(sorted(self.config.allowed_directories))}",
            "- No network access.",
            f"- Execution time limit: {self.config.max_execution_time_seconds}s "
            f"(tool calls are not counted against this limit).",
            f"- Memory limit: {self.config.max_memory_mb}MB.",
            "- Unavaiable: " + ", ".join(sorted(_BLOCKED)) + ", ",
            "- Dunder attribute access (__class__, __globals__) is blocked.",
            "",
            "## final_answer",
            ""
            "final_answer(value) ends the task. It is always available and",
            "is not an MCP tool. Call it once you have a verified answer.",
            "",
            "## Tools",
            "",
            "Call these as normal Python functions, keywords arguments only.",
            "",
        ]
        if not self.tools:
            lines.append("No MCP server connected.")
            return "\n".join(lines)
        for name in sorted(self.tools):
            lines.append(self._tool_doc(name, self.tools[name]))
            lines.append("")
        return "\n".join(lines)

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
                if isinstance(raw, str):
                    raw, was_cut = _truncate(
                        raw, self.config.max_output_chars
                    )
                    self._tool_truncated = self._tool_truncated or was_cut
                reply["result"] = raw
            except Exception as exc:
                reply["error"] = f"{type(exc).__name__}: {exc}"
        _send(self._cmd_w, reply)

    def _to_result(self, message: dict[str, Any]) -> ExecuteResult:
        """Turn a terminal worker message into an ExecuteResult."""
        base = {
            "stdout": message.get("stdout", ""),
            "stderr": message.get("stderr", ""),
            "timeout": bool(message.get("timeout", False)),
            "truncated": bool(message.get("truncated", False) or self._tool_truncated),
        }
        kind = message.get("kind")
        if kind == "final_answer":
            return ExecuteResult(
                final_answer=message.get("value"),
                final_answer_bool=True,  # This is for cases where final answer is ""
                **base
            )
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

    with Sandbox(config=config) as sandbox:
        print(sandbox.manual())
        print(sandbox.client.list_tools())
        if args.command is not None:
            _show(sandbox.run(args.command))
        elif args.file is not None:
            _show(sandbox.run(Path(args.file).read_text(encoding="utf-8")))
        else:
            return _repl(sandbox)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

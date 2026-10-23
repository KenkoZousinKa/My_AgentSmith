"""The main entry for the sandbox."""

from __future__ import annotations
from src.models.sandbox_config import SandboxConfig
from src.sandbox.code_lint import check_code, _BLOCKED
from src.sandbox.sandbox_helper import send, recv, py_name
from src.sandbox.sandbox_child import child_main
from src.models.output import ExecuteResult
from src.mcp.client.mcp_tool_function import MCPToolFunction
from src.mcp.client.client import MCPClient
from src.mcp.client.stdio import StdioClientTransport
from src.mcp.client.http import HttpClientTransport
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
        tools: dict[str, Callable[..., Any]] | None = None,
        mcp_stdio: str | None = None,
        mcp_server: str | None = None
    ) -> None:
        """Init the Sandbox and fork its worker."""
        self.config = config or SandboxConfig()
        self.tools: dict[str, Callable[..., Any]] = tools or {}
        self.client: MCPClient | None = None
        self._pid: int | None = None
        self._cmd_w = -1
        self._res_r = -1
        self._tool_truncated = False
        self.resources: list[Any] = []
        self.prompts: list[Any] = []
        if mcp_stdio:
            self.client = MCPClient(StdioClientTransport(mcp_stdio))
        elif mcp_server:
            self.client = MCPClient(HttpClientTransport(mcp_server))
        if self.client is not None:
            try:
                self.client.connect()
                self.tools = {
                    py_name(tool.name): MCPToolFunction(self.client, tool)
                    for tool in self.client.list_tools()
                }
                self.resources = self.client.list_resources()
                self.prompts = self.client.list_prompts()
            except Exception:
                self.client.close()
                self.client = None
                raise

        for d in self.config.allowed_directories:
            try:
                os.makedirs(d, exist_ok=True)
            except OSError:
                pass

        self._spawn()

    def __enter__(self) -> "Sandbox":
        """Enter a context manager."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """Leave a context manager, killing the worker."""
        self.close()

    def _spawn(self) -> None:
        """Fork a worker and keep the parent endsd of both pipes."""
        sys.stdout.flush()
        sys.stderr.flush()
        cmd_r, cmd_w = os.pipe()
        res_r, res_w = os.pipe()
        has_catalog = bool(self.resources or self.prompts)
        pid = os.fork()
        if pid == 0:
            os.close(cmd_w)
            os.close(res_r)
            try:
                child_main(self.config, cmd_r, res_w, sorted(self.tools), has_catalog)
            finally:
                os._exit(1)
        os.close(cmd_r)
        os.close(res_w)
        self._pid, self._cmd_w, self._res_r = pid, cmd_w, res_r

    def reset(self) -> None:
        """Restart the worker, keeping the MCP client connected.

        Only the sandboxed namespace is lost. The cline belongs to
        the session.
        """
        self._close_worker()
        self._spawn()

    def close(self) -> None:
        """Shut down the worker and the MCP client.

        Safe to call twice; the orchestrator should call it in a finaly
        block.
        """
        self._close_worker()
        if self.client is not None:
            self.client.close()
            self.client = None

    def _close_worker(self) -> None:
        """Kill the worker's process group, reap it, and close pipes.

        Each descriptor is closed exactly once then blanked:
        a freed fd number can be reused.
        """
        if self._pid is None:
            return
        pid = self._pid
        self._pid = None

        for fd in (self._cmd_w, self._res_r):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass

        self._cmd_w = self._res_r = -1

        for kill in (
            lambda: os.killpg(pid, signal.SIGKILL),
            lambda: os.kill(pid, signal.SIGKILL)
        ):
            try:
                kill()
                break
            except (ProcessLookupError, PermissionError):
                continue
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass

    def _catalog_text(self, result: Any) -> Any:
        """Make an MCP result JSON-safe for the pipe."""
        if hasattr(result, "model_dump"):
            try:
                return result.model_dump(mode="json")
            except Exception:
                return str(result)
        return result

    def _dispatch_catalog(self, message: dict[str, Any]) -> None:
        """Serve a read_resource / get_prompt relay from the child."""
        kind = message.get("kind")
        reply: dict[str, Any] = {"result": None, "error": None}
        if self.client is None:
            reply["error"] = "no MCP server connected"
        else:
            try:
                if kind == "resource_read":
                    res = self.client.read_resource(message["uri"])
                else:
                    res = self.client.get_prompt(
                        message["name"], message.get("arguments")
                    )
                reply["result"] = self._catalog_text(res)
            except Exception as exc:
                reply["error"] = f"{type(exc).__name__}: {exc}"
        try:
            send(self._cmd_w, reply)
        except OSError:
            pass

    def run(self, code: str) -> ExecuteResult:
        """Check, exectue, and service tool calls untill the snippet ends."""
        # ===== debug =====
        print(code)
        print("=======================")
        # ===== debug =====
        rejection = check_code(code, self.config, frozenset(self.tools))
        if rejection:
            return ExecuteResult(error=rejection)

        self._tool_truncated = False
        try:
            send(self._cmd_w, {"kind": "run", "code": code})
        except OSError:
            self.reset()
            return ExecuteResult(error="worker was dead; restarted")

        grace = self.config.max_execution_time_seconds + 5
        while True:
            ready, _, _ = select.select([self._res_r], [], [], grace)
            if not ready:
                self.reset()
                return ExecuteResult(
                    error="timed out and the worker was restarted: all"
                          "Names from previous steps are gone - redefine "
                          "anything you still need.",
                    timeout=True
                )
            try:
                message = recv(self._res_r)
            except (EOFError, OSError, ValueError):
                self.reset()
                return ExecuteResult(
                    error="the worker died (likely the memory limit) and "
                          "was restarted; all names from previous steps "
                          "are gone - redefine anything you still need."
                )
            kind = message.get("kind")
            if kind == "tool_call":
                self._dispatch(message)
                continue
            if kind in ("resource_read", "prompt_get"):
                self._dispatch_catalog(message)
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

    def _resource_doc(self, res: Any) -> str:
        """Render one resource as uri plus its description."""
        uri = getattr(res, "uri", "")
        name = getattr(res, "name", "") or ""
        desc = getattr(res, "description", "") or ""
        head = f"{uri}" + (f" ({name})" if name else "")
        return head + (f"\n  {desc.strip()}" if desc else "")

    def _prompt_doc(self, prompt: Any) -> str:
        """Render one prompt as a name plus its arguments."""
        name = getattr(prompt, "name", "")
        desc = getattr(prompt, "description", "") or ""
        args = getattr(prompt, "arguments", "") or []
        arg_names = ", ".join(getattr(a, "name", str(a)) for a in args)
        head = f"{name}({arg_names})"
        return head + (f"\n  {desc.strip()}" if desc else "")

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
            "- Unavaiable: " + ", ".join(sorted(_BLOCKED)),
            "- Dunder attribute access (__class__, __globals__) is blocked.",
            "",
            "## final_answer",
            "",
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
        if self.resources:
            lines.append("")
            lines.append("## Resources")
            lines.append("")
            lines.append(
                "Read with read_resource(uri=...) Available:"
            )
            for res in self.resources:
                lines.append(self._resource_doc(res))
            lines.append("")
        if self.prompts:
            lines.append("## Prompts")
            lines.append("")
            lines.append(
                "Fetch with get_prompt(name=..., arguments={...}). Available:"
            )
            for prompt in self.prompts:
                lines.append(self._prompt_doc(prompt))
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
                # sympy-18189: config.max_output_charsを超える出力は切り詰められてるので、
                # get_patch()の戻り値をそのまま提出させるためにツールの戻り値をそのまま返すようにする。
                reply["result"] = handler(**(message.get("arguments") or {}))
                # raw = handler(**(message.get("arguments") or {}))
                # if isinstance(raw, str):
                #     raw, was_cut = _truncate(
                #         raw, self.config.max_output_chars
                #     )
                #     self._tool_truncated = self._tool_truncated or was_cut
                # reply["result"] = raw
            except Exception as exc:
                reply["error"] = f"{type(exc).__name__}: {exc}"
        try:
            send(self._cmd_w, reply)
        except OSError:
            pass

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
    """Show the result of the executed code."""
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

    with Sandbox(
        config=config,
        mcp_stdio=args.mcp_stdio,
        mcp_server=args.mcp_server
    ) as sandbox:
        if args.command is not None:
            _show(sandbox.run(args.command))
        elif args.file is not None:
            _show(sandbox.run(Path(args.file).read_text(encoding="utf-8")))
        else:
            return _repl(sandbox)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

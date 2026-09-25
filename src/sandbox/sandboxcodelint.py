"""A test version of the Sandbox. much looser error checks."""

from __future__ import annotations

import argparse
import ast
import builtins
import io
import signal
import traceback
from contextlib import redirect_stdout
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
    """Task complete signal."""
    def __init__(self, value: Any) -> None:
        """Init self with base exception inheritance."""
        super().__init__(value)
        self.value = value


class _Timeout(Exception):
    """Raised for timeout when too long."""


_BLOCKED = frozenset({
    "eval", "exec", "compile", "__import__", "globals", "locals", "vars",
    "getattr", "setattr", "breakpoint", "input", "open", "exit", "quit",
})


def _allowed(name: str, authorized: frozenset[str]) -> bool:
    """'collections.*' permits collection s and its submodules."""
    return name in authorized or any(
        e.endswith(".*") and (name == e[:-2] or name.startswith(e[:-1]))
        for e in authorized
    )


class _Checker(ast.NodeVisitor):
    """Static pass: cheap rejection before anything happens if anything is not allowed."""
    def __init__(
        self,
        authorized: frozenset[str],
        tools_names: frozenset[str] = frozenset()
    ) -> None:
        """Checks what is accepted and if errors records them."""
        self.authorized: frozenset[str] = authorized
        self.tools_names = tools_names
        self.errors: list[str] = []

    def _check_module(self, name: str) -> None:
        """Check if importing named module is allowed."""
        if not _allowed(name, self.authorized):
            self.errors.append(f"import of {name!r} is not allowed")

    def visit_import(self, node: ast.Import) -> None:
        """Visit all nodes."""
        for alias in node.names:
            self._check_module(alias.name)
        self.generic_visit(node)

    def visit_importfrom(self, node: ast.ImportFrom) -> None:
        """Visit relative imports."""
        if node.level:
            self.errors.append("relative imports are not allowed")
        elif node.module:
            self._check_module(node.module)
        self.generic_visit(node)

    def visit_attribute(self, node: ast.Attribute) -> None:
        """Blocks globals."""
        if node.attr.startswith("__") and node.attr.endswith("__"):
            self.errors.append(f"access to dunder attribute {node.attr!r}")
        self.generic_visit(node)

    def visit_name(self, node: ast.Name) -> None:
        """Check node names."""
        if node.id in _BLOCKED:
            self.errors.append(f"use of {node.id!r} is not allowed")
        self.generic_visit(node)


def check_code(code: str, config: SandboxConfig) -> str | None:
    """Return a rejection reason, or None if the code is okay."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"SyntaxError: {exc.msg} (line {exc.lineno})"
    checker = _Checker(frozenset(config.authorized_imports))
    checker.visit(tree)
    return ": ".join(checker.errors) or None


def _safe_builtins(config: SandboxConfig) -> dict[str, Any]:
    """Builtins minus the dangerous ones, plus guarded __import__."""
    safe: dict[str, Any] = {
        n: getattr(builtins, n)
        for n in dir(builtins) if not n.startswith("_") and n not in _BLOCKED
    }
    authorized = frozenset(config.authorized_imports)
    real = builtins.__import__

    def guarded(name: str, *args: Any, **kwargs: Any) -> Any:
        """Enforcement point: every import is guared."""
        if not _allowed(name, authorized):
            raise ImportError(f"import of {name!r} not allowed")
        return real(name, *args, **kwargs)

    safe["__import__"] = guarded
    return safe


class Sandbox:
    """Runs code and checks if they are legal."""
    def __init__(
        self,
        config: SandboxConfig | None = None,
        tools: dict[str, Callable[..., Any]] | None = None
    ) -> None:
        """Init the Sandbox for testing code."""
        self.config = config or SandboxConfig()
        self.tools = tools or {}
        self.reset()

    def reset(self) -> None:
        """Fresh namespace with builtins, final answer, and tools."""
        def final_answer(value: Any = None) -> Any:
            raise FinalAnswer(value)

        self.namespace: dict[str, Any] = {
            "__name__": "__sandbox__",
            "__builtins__": _safe_builtins(self.config),
            "final_answer": final_answer,
            **self.tools,
        }

    def run(self, code: str) -> ExecuteResult:
        """Check then execute. Never raises for errors inside the snippet."""
        rejection = check_code(code, self.config)
        if rejection:
            return ExecuteResult(error=rejection)
        tree = ast.parse(code)
        tail = (tree.body.pop()
                if tree.body and isinstance(tree.body[-1], ast.Expr) else None)
        body = compile(tree, "<sandbox>", "exec")
        out = io.StringIO()
        result = ExecuteResult()
        signal.signal(signal.SIGALRM, _on_alarm)
        signal.alarm(self.config.max_execution_time_seconds)
        try:
            with redirect_stdout(out):
                exec(body, self.namespace)
                if tail is not None:
                    expr = compile(
                        ast.Expression(tail.value), "<sandbox>", "eval"
                    )
                    value = eval(expr, self.namespace)
                    if value is not None:
                        result.value = repr(value)
        except FinalAnswer as answer:
            result.final_answer = str(answer.value)
        except _Timeout:
            result.error = (
                f"timeout after {self.config.max_execution_time_seconds}s"
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException:
            result.error = traceback.format_exc(limit=5)
        finally:
            signal.alarm(0)
        result.stdout = out.getvalue()
        return result


def _on_alarm(*_args: Any) -> None:
    """Raise timeout."""
    raise _Timeout()


def main() -> int:
    """Main tester to see if it is working.

    Runs argparser to get all the arguments for the testing code.
    """
    parser = argparse.ArgumentParser(prog="sandbox")
    parser.add_argument("config", nargs="?", help="JSON config file")
    parser.add_argument("-c", "--command", help="run one sniippet and exit")
    parser.add_argument("-f", "--file", help="run a file and exit")
    args = parser.parse_args()

    config = (
        SandboxConfig.model_validate_json(
            Path(args.config).read_text(encoding="utf-8")
        )
        if args.config else SandboxConfig()
    )
    sandbox = Sandbox(config)

    if args.command is not None:
        sources = [args.command]
    elif args.file is not None:
        sources = [Path(args.file).read_text(encoding="utf-8")]
    else:
        return _repl(sandbox)

    for source in sources:
        _show(sandbox.run(source))
    return 0


def _show(result: ExecuteResult) -> None:
    """Shows the result of the executed code."""
    if result.stdout:
        print(result.stdout, end="")
    if result.error:
        print(result.error)
    elif result.final_answer is not None:
        print(f"[final_answer] {result.final_answer}")
    elif result.value is not None:
        print(result.value)


def _repl(sandbox: Sandbox) -> int:
    """The CLI for the AI to interact and exit or input the code."""
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
        _show(sandbox.run("\n".join(buffer)))


if __name__ == "__main__":
    raise SystemExit(main())

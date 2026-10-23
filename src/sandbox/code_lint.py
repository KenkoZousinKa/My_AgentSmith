"""The main checker for code. Checks AI code for imports and syntax."""
from __future__ import annotations
from src.models.sandbox_config import SandboxConfig
from typing import Any, Callable
from pathlib import Path
import builtins
import os
import ast


_BLOCKED = frozenset({
    "eval", "exec", "compile", "__import__", "globals", "locals", "vars",
    "getattr", "setattr", "breakpoint", "input", "exit", "quit",
})


_IMPLICIT_IMPORTS = frozenset({"_strptime"})


def _allowed(name: str, authorized: frozenset[str]) -> bool:
    """Match a module name against the allowlist."""
    return name in authorized or any(
        e.endswith(".*") and (name == e[:-2] or name.startswith(e[:-1]))
        for e in authorized
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
        self.module_names: set[str] = set()

    def _check_module(self, name: str) -> None:
        """Check if importing named module is allowed."""
        if not _allowed(name, self.authorized):
            self.errors.append(f"import of {name!r} is not allowed")

    #  Visit methods so need the capital letter to match the AST node names.
    #  Or else the generic_visit() will not call them.
    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        """Visit all nodes."""
        for alias in node.names:
            self._check_module(alias.name)
            bound = alias.asname or alias.name.split(".")[0]
            self.module_names.add(bound)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        """Visit from-imports and reject relative ones."""
        if node.level:
            self.errors.append("relative imports are not allowed")
        elif node.module:
            self._check_module(node.module)
        for alias in node.names:
            if alias.name.startswith("_") and not (
                alias.name.startswith("__") and alias.name.endswith("__")
            ):
                self.errors.append(
                    f"import of private name {alias.name!r} is not allowed"
                )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        """Blocks dunder access, which reaches globals and subclasses."""
        if node.attr.startswith("__") and node.attr.endswith("__"):
            self.errors.append(f"access to dunder attribute {node.attr!r}")
        elif (
            node.attr.startswith("_")
            and isinstance(node.value, ast.Name)
            and node.value.id in self.module_names
        ):
            self.errors.append(
                f"access to private module attribute {node.attr!r}"
            )
        elif node.attr == "format":
            self.errors.append("use of '.format' is not allowed")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
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


def safe_builtins(config: SandboxConfig) -> dict[str, Any]:
    """Bultins minus the dangerous ones, plus guarded __import__.

    This must be set explicitly: exec() given a globals dict with no
    '__bultins__' key silently inserts the real bultins module.
    """
    safe: dict[str, Any] = {
        n: getattr(builtins, n)
        for n in dir(builtins) if not n.startswith("_") and n not in _BLOCKED
    }
    safe["__build_class__"] = builtins.__build_class__
    authorized = frozenset(config.authorized_imports)
    real = builtins.__import__

    def guarded(name: str, *args: Any, **kwargs: Any) -> Any:
        """Enforcement point: every import compiles to this."""
        if name in _IMPLICIT_IMPORTS:
            return real(name, *args, **kwargs)
        if not _allowed(name, authorized):
            raise ImportError(f"import of {name!r} not allowed")
        return real(name, *args, **kwargs)

    safe["__import__"] = guarded
    safe["open"] = _guarded_open(config)
    return safe

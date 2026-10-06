"""The child sandbox process that runs student code in a safe environment and its helpers."""

from __future__ import annotations
from src.models.sandbox_config import SandboxConfig
from src.sandbox.code_lint import _safe_builtins
from src.sandbox.sandbox_result import FinalAnswer, _truncate
from src.sandbox.sandbox_helper import (
    _apply_limits,
    _disable_network,
    _tool_proxy,
    _recv,
    _send,
    _on_alarm,
    _Timeout
)
from typing import Any
from contextlib import redirect_stdout, redirect_stderr
import os
import signal
import io
import traceback
import ast


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
    result: dict[str, Any] = {"kind": "ok", "value": None, "timeout": False}
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
        result = {"kind": "error", "timeout": True, "error": (
            f"timeout after {timeout}s; any output above is partial"
        )}
    except MemoryError:
        result = {"kind": "error", "error": "memory limit exceeded"}
    except KeyboardInterrupt:
        result = {"kind": "interrupt"}
    except SystemExit as exc:
        result = {"kind": "exit", "code": str(exc.code or 0)}
    except BaseException:  # noqa: B036 - KeyboardInterrupt/SystemExit
        # are caught above; this is needed to catch LLM code that can
        # raise any exception.
        result = {"kind": "error", "error": traceback.format_exc(limit=5)}
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)

    limit = config.max_output_chars
    out_text, out_cut = _truncate(out.getvalue(), limit)
    err_text, err_cut = _truncate(err.getvalue(), limit)
    result["stdout"] = out_text
    result["stderr"] = err_text
    result["truncated"] = out_cut or err_cut
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

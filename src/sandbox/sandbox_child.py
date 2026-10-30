"""The child sandbox process that runs student code in a safe environment and its helpers."""

from __future__ import annotations
from src.models.sandbox_config import SandboxConfig
from src.sandbox.code_lint import safe_builtins, check_code
from src.sandbox.sandbox_result import FinalAnswer
from src.sandbox.sandbox_helper import (
    apply_limits,
    disable_network,
    catalog_relays,
    scrub_environment,
    install_audit_hook,
    tool_proxy,
    recv,
    send,
    on_alarm,
    truncate,
    Timeout
)
from typing import Any
from contextlib import redirect_stdout, redirect_stderr
import os
import signal
import io
import traceback
import ast


def _exit_code(code: Any) -> int:
    """Map a systemexit code to an int the way Python itself does.

    None -> 0, int -> itself, anything else (a string message) + 1.
    """
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    return 1


def _execute(
    code: str, namespace: dict[str, Any], config: SandboxConfig
) -> dict[str, Any]:
    """Run one snippet and describe what happened, as a dict."""
    reject = check_code(code, config, frozenset(namespace))
    if reject:
        return {"kind": "error", "error": reject,
                "stdout": "", "stderr": "", "timeout": False,
                "truncated": False, "value": None}
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
                assert isinstance(tail, ast.Expr)
                expr = compile(
                    ast.Expression(tail.value), "<sandbox>", "eval"
                )
                value = eval(expr, namespace)
                if value is not None:
                    result["value"] = (
                        value if isinstance(value, str) else repr(value)
                    )
    except FinalAnswer as answer:
        result = {"kind": "final_answer", "value": str(answer.value)}
    except Timeout:
        result = {"kind": "error", "timeout": True, "error": (
            f"timeout after {timeout}s; any output above is partial"
        )}
    except MemoryError:
        result = {"kind": "error", "error": "memory limit exceeded"}
    except (PermissionError, ImportError) as exc:
        result = {"kind": "error", "error": f"{type(exc).__name__}: {exc}"}
    except KeyboardInterrupt:
        result = {"kind": "interrupt"}
    except SystemExit as exc:
        result = {"kind": "exit", "code": _exit_code(exc.code)}
    except BaseException:  # noqa: B036 - KeyboardInterrupt/SystemExit
        # are caught above; this is needed to catch LLM code that can
        # raise any exception.
        result = {"kind": "error", "error": traceback.format_exc(limit=5)}
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)

    limit = config.max_output_chars
    out_text, out_cut = truncate(out.getvalue(), limit)
    err_text, err_cut = truncate(err.getvalue(), limit)
    result["stdout"] = out_text
    result["stderr"] = err_text
    result["truncated"] = out_cut or err_cut
    return result


def child_main(
        config: SandboxConfig,
        cmd_fd: int,
        res_fd: int,
        tool_params: dict[str, list[str]],
        has_catalog: bool = False
) -> None:
    """Worker entry point. Never returns."""
    os.setsid()
    signal.signal(signal.SIGALRM, on_alarm)
    disable_network()

    def final_answer(value: Any = None) -> Any:
        """Flag for final answer."""
        raise FinalAnswer(value)

    namespace: dict[str, Any] = {
        "__name__": "__sandbox__",
        "__builtins__": safe_builtins(config),
        "final_answer": final_answer,
    }
    for name, params in tool_params.items():
        namespace[name] = tool_proxy(name, params, res_fd, cmd_fd)
    if has_catalog:
        namespace.update(catalog_relays(res_fd, cmd_fd))

    scrub_environment()
    apply_limits(config)
    install_audit_hook(config)

    while True:
        try:
            message = recv(cmd_fd)
        except (EOFError, OSError):
            os._exit(0)
        if message.get("kind") != "run":
            os._exit(0)
        outcome = _execute(message["code"], namespace, config)
        try:
            send(res_fd, outcome)
        except OSError:
            os._exit(1)

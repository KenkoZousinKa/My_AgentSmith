"""mcp_tools_mbpp.py"""

import ast
import sys
import json
import subprocess
import tempfile
import argparse
from pathlib import Path

from src.mcp.server.server import MCPServer
from src.mcp.server.http import HttpServerTransport

server = MCPServer(name="agent-smith-mbpp", version="0.1.0")
TIMEOUT = 10


@server.tool()
def run_tests(code: str, test_list: list[str]) -> str:
    """Run candidate solution code against a list of assert statements.

    Returns a JSON string with "success" (True if all tests passed),
    "message" and "output" (stdout and stderr of the run).
    """
    # 1. 実行するスクリプトを用意（各 assert に got/expected 表示を付与）
    script = f"{code}\n" + "\n".join(_enrich(t) for t in test_list)

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            # 2. 自動で削除されるtemp_dir内にファイルを作って実行
            script_path = Path(temp_dir) / "test_run.py"
            script_path.write_text(script, encoding="utf-8")
            result = subprocess.run([sys.executable, '-I', str(script_path)], cwd=temp_dir, env={},
                                    capture_output=True, text=True, timeout=TIMEOUT, check=True)
    except subprocess.TimeoutExpired:
        return json.dumps({"success": False, "message": "Timeout",
                           "output": f"Execution did not finish within {TIMEOUT} seconds."})
    except subprocess.CalledProcessError as e:
        return json.dumps({"success": False, "message": "Tests failed", "output": e.stdout + e.stderr})
    except Exception as e:
        return json.dumps({"success": False, "message": type(e).__name__, "output": str(e)})

    # 3. json形式のstrにして返す。
    return json.dumps({"success": True, "message": "passed", "output": result.stdout + result.stderr})


def _enrich(stmt: str) -> str:
    """'assert A == B' に失敗時の値表示（got / expected）を付ける."""
    try:
        node = ast.parse(stmt).body[0]
        # Assert文であり、比較されているか
        if isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare):
            # 比較演算子が一つであり、==であるか
            if len(node.test.ops) == 1 and isinstance(node.test.ops[0], ast.Eq):
                a = ast.unparse(node.test.left)
                b = ast.unparse(node.test.comparators[0])
                return f'assert (_g := ({a})) == (_e := ({b})), f"got {{_g!r}}, expected {{_e!r}}"'
                # ({a}) :式順序を崩さないため。 {{_g!r}} :埋め込み展開。 !r :intなら12 strなら'12'
                # _g _e :LLMのコードと被らせないため
    except Exception:
        pass
    return stmt


@server.resource("mbpp://guide/run_tests", mime_type="text/markdown")
def run_tests_guide() -> str:
    """How to call run_tests and read its result."""
    return (
        "# run_tests\n"
        "- Pass the full function source as `code` and the assert lines as `test_list`.\n"
        "- `code` must contain real newlines and indentation, not a single line.\n"
        "- The result is a JSON string: `success` is true only if every assert passed.\n"
        "- On failure, read `output`: it holds the traceback (SyntaxError, NameError, AssertionError...).\n"
    )


@server.prompt()
def solve_task(task_definition: str, function_definition: str, tests: str = "") -> str:
    """Build the instruction for solving one MBPP task."""
    lines = [
        f"Task: {task_definition}",
        f"Write this function: {function_definition}",
        "Check your solution with run_tests before calling final_answer.",
    ]
    if tests:
        lines.append(f"Example tests:\n{tests}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="MBPP MCP Server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    print("[Server] MCP_TOOLS_MBPPを起動します。", file=sys.stderr)
    if args.transport == "http":
        server.run(HttpServerTransport(host=args.host, port=args.port))
    else:
        server.run()
    print("[Server] MCP_TOOLS_MBPPを終了しました。", file=sys.stderr)


if __name__ == "__main__":
    main()

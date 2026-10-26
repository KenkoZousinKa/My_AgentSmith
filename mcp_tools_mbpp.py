"""mcp_tools_mbpp.py"""

import sys
import json
import subprocess
import tempfile
import argparse

from src.mcp.server.server import MCPServer
from src.mcp.server.http import HttpServerTransport

server = MCPServer(name="agent-smith-mbpp", version="0.1.0")
TIMEOUT = 30


@server.tool()
def run_tests(code: str, test_list: list[str]) -> str:
    """Run candidate solution code against a list of assert statements.

    Returns a JSON string with "success" (True if all tests passed),
    "message" and "output" (stdout and stderr of the run).
    """
    # 1. 実行するスクリプトを用意
    script = f"{code}\n" + '\n'.join(test_list)

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            # 2. 自動で削除されるtemp_dir内で実行
            result = subprocess.run([sys.executable, '-I', '-c', script], cwd=temp_dir, env={},
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


    print(f"[Server] MCP_TOOLS_SWEBENCHを起動します。", file=sys.stderr)
    if args.transport == "http":
        server.run(HttpServerTransport(host=args.host, port=args.port))
    else:
        server.run()
    print(f"[Server] MCP_TOOLS_SWEBENCHを終了しました。", file=sys.stderr)


if __name__ == "__main__":
    main()

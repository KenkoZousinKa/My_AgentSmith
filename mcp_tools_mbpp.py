"""mcp_tools_mbpp.py"""

import sys
import json
import subprocess
import tempfile
import argparse

from src.mcp_core.server.server import MCPServer
# from src.mcp_core.server.transport import HttpServerTransport

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


def main() -> None:
    parser = argparse.ArgumentParser(description="MBPP MCP Server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.transport == "http":
        # server.run(HttpServerTransport(host=args.host, port=args.port))
        pass
    else:
        server.run()


if __name__ == "__main__":
    main()

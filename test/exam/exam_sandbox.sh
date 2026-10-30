#!/usr/bin/env bash
# 課題 PDF Chapter VI Table VI.1 に基づく exam_sandbox.sh の模擬スクリプト
# 検査項目 (Pass: ALL):
#   1. import block
#   2. builtin block
#   3. network block
#   4. path restrict
#   5. timeout
#   6. memory limit
#   7. MCP protocol (stdio + HTTP + unknown server)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STUDENT_PATH="$(cd "$SCRIPT_DIR/../.." && pwd)"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --student-path) STUDENT_PATH="$(cd "$2" && pwd)"; shift 2 ;;
        --moulinette-path) shift 2 ;;
        --env-file) shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

cd "$STUDENT_PATH"
uv run python - <<'PY'
import sys
from src.sandbox.sandbox_main import Sandbox
from src.models.sandbox_config import SandboxConfig
from src.mcp.client.client import MCPClient, MBPP_SERVER_COMMAND, DEFAULT_URL
from src.mcp.client.stdio import StdioClientTransport
from src.mcp.client.http import HttpClientTransport
from src.mcp.client.mcp_tool_function import MCPToolFunction

passed = 0
failed = 0

def check(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}: {detail}")

config = SandboxConfig(max_execution_time_seconds=2, max_memory_mb=256)

with Sandbox(config=config) as sb:
    # 1. import block
    r = sb.run("import os\nprint(os.getcwd())")
    check("1. import block (import os)", r.error is not None, f"got {r}")

    # 2. builtin block
    r = sb.run("print(open('/etc/passwd').read())")
    check("2. builtin block (open)", r.error is not None, f"got {r}")
    r2 = sb.run("print(eval('1+1'))")
    check("2. builtin block (eval)", r2.error is not None, f"got {r2}")

    # 3. network block
    r = sb.run("import urllib.request\nurllib.request.urlopen('http://example.com')")
    check("3. network block", r.error is not None, f"got {r}")

    # 4. path restrict (dunder / module escape check)
    r = sb.run("x = ().__class__.__base__")
    check("4. path / dunder restrict", r.error is not None, f"got {r}")

    # 5. timeout
    r = sb.run("while True:\n    pass")
    check("5. timeout", r.timeout or (r.error is not None and "timeout" in r.error.lower()), f"got {r}")

    # 6. memory limit
    r = sb.run("a = 'x' * (400 * 1024 * 1024)")
    check("6. memory limit", r.error is not None, f"got {r}")

# 7. MCP protocol (stdio & HTTP)
try:
    with MCPClient(StdioClientTransport(MBPP_SERVER_COMMAND)) as c:
        tools = {t.name: MCPToolFunction(c, t) for t in c.list_tools()}
        with Sandbox(config=config, tools=tools) as sb:
            r = sb.run("print(run_tests(code='def f(x): return x+1', test_list=['assert f(1)==2']))")
            check("7a. MCP protocol (stdio tool call in sandbox)", r.error is None and '"success": true' in r.stdout, f"got {r}")
except Exception as e:
    check("7a. MCP protocol (stdio tool call in sandbox)", False, str(e))

try:
    with MCPClient(HttpClientTransport(DEFAULT_URL, command=MBPP_SERVER_COMMAND + " --transport http")) as c:
        tools = {t.name: MCPToolFunction(c, t) for t in c.list_tools()}
        with Sandbox(config=config, tools=tools) as sb:
            r = sb.run("print(run_tests(code='def f(x): return x+1', test_list=['assert f(1)==2']))")
            check("7b. MCP protocol (HTTP tool call in sandbox)", r.error is None and '"success": true' in r.stdout, f"got {r}")
except Exception as e:
    check("7b. MCP protocol (HTTP tool call in sandbox)", False, str(e))

print("==========================================")
print(f" Sandbox Exam Summary: {passed} passed, {failed} failed (Pass: ALL)")
print("==========================================")
sys.exit(0 if failed == 0 else 1)
PY

#!/usr/bin/env bash
# exam_sandbox.sh の Strict（高難度・意地悪）バージョン
# 通常の7項目に加え、許可モジュール経由のOS脱獄・APIキー漏洩・シンボリックリンク脱出・
# BaseException以外の例外握りつぶし無限ループ・未知のMCPサーバー・Resources/Prompts 等を徹底検証する
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
if command -v uv >/dev/null 2>&1; then
    RUN_PY=(uv run python)
elif [ -x "$STUDENT_PATH/.venv/bin/python" ]; then
    export PATH="$STUDENT_PATH/.venv/bin:$PATH"
    RUN_PY=("$STUDENT_PATH/.venv/bin/python")
else
    RUN_PY=(python3)
fi

"${RUN_PY[@]}" - <<'PY'
import os
import sys
import tempfile
from pathlib import Path
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

print("==========================================")
print(" EXAM SANDBOX STRICT (Hard Security & MCP)")
print("==========================================")

# 親プロセスにダミーの秘密キーを仕込む（子プロセスから見えてはいけない）
os.environ["STRICT_EXAM_SECRET_API_KEY"] = "sk-strict-secret-do-not-leak"

with tempfile.TemporaryDirectory(prefix="agentsmith_strict_") as allowed_tmp:
    config = SandboxConfig(
        max_execution_time_seconds=2,
        max_memory_mb=256,
        allowed_directories=[allowed_tmp, "/tmp/agent"],
    )

    with Sandbox(config=config) as sb:
        # --- 1. Import Restrictions (Direct & Indirect) ---
        r = sb.run("import os, subprocess, socket, ctypes, sys, builtins, importlib")
        check("1a. direct forbidden imports blocked", r.error is not None, f"got {r}")

        r = sb.run("from . import something")
        check("1b. relative import blocked", r.error is not None, f"got {r}")

        r = sb.run("from collections import _Link")
        check("1c. private symbol import (from mod import _x) blocked", r.error is not None, f"got {r}")

        r = sb.run("import datetime\nprint(datetime.datetime.strptime('2026-01-01', '%Y-%m-%d').year)")
        check("1d. allowed lazy import (datetime.strptime / _strptime) works", r.error is None and "2026" in r.stdout, f"got {r}")

        # --- 2. Escape via Allowed Modules (Audit Hook & AST Private Attr) ---
        r = sb.run("import random\nprint(random._os.listdir('/'))")
        check("2a. escape via random._os blocked", r.error is not None and "bin" not in r.stdout, f"got {r}")

        r = sb.run("import json\nprint(json.codecs.open('/etc/hostname').read())")
        check("2b. escape via json.codecs.open('/etc/hostname') blocked", r.error is not None and r.stdout == "", f"got {r}")

        r = sb.run("import typing\nprint(typing.sys.modules['os'].listdir('/'))")
        check("2c. escape via typing.sys.modules['os'] blocked", r.error is not None and r.stdout == "", f"got {r}")

        r = sb.run("import functools, typing\nf = functools.partial(typing.sys.modules['os'].system, 'id')\nf()")
        check("2d. escape via functools.partial + sys.modules['os'].system blocked", r.error is not None, f"got {r}")

        # --- 3. Builtins & Dunder / Format Gadgets ---
        for b in ("eval('1')", "exec('x=1')", "compile('1','','eval')", "__import__('os')", "globals()", "locals()", "vars()", "getattr(int, 'real')", "setattr(int, 'x', 1)", "input()"):
            r = sb.run(b)
            if r.error is None:
                check(f"3a. dangerous builtin blocked ({b})", False, f"got {r}")
                break
        else:
            check("3a. all dangerous builtins blocked (eval/exec/compile/__import__/globals/getattr...)", True)

        r = sb.run("x = ().__class__.__mro__[1].__subclasses__()")
        check("3b. dunder attribute gadget (__class__.__mro__.__subclasses__) blocked", r.error is not None, f"got {r}")

        r = sb.run("print('{0.__class__}'.format(1))")
        check("3c. str.format attribute traversal blocked", r.error is not None, f"got {r}")

        r = sb.run("class Counter:\n    def __init__(self, v): self.v = v\nprint(Counter(42).v)")
        check("3d. user class definition (__build_class__) works", r.error is None and "42" in r.stdout, f"got {r}")

        # --- 4. Environment Variable / API Key Scrubbing ---
        r = sb.run("import typing\nprint('STRICT_EXAM_SECRET_API_KEY' in typing.sys.modules['os'].environ)")
        check("4. parent API keys / environment variables scrubbed in child", r.error is not None or "True" not in r.stdout, f"got {r}")

        # --- 5. Filesystem & Symlink / Traversal / Raw FD Restrictions ---
        ok_file = Path(allowed_tmp) / "allowed.txt"
        r = sb.run(f"with open({str(ok_file)!r}, 'w') as f:\n    f.write('hello_sandbox')\nwith open({str(ok_file)!r}) as f:\n    print(f.read())")
        check("5a. read/write inside allowed_directories works", r.error is None and "hello_sandbox" in r.stdout, f"got {r}")

        r = sb.run(f"with open('{allowed_tmp}/../../../../etc/passwd') as f:\n    print(f.read())")
        check("5b. path traversal (../) outside allowlist blocked", r.error is not None and "root:" not in r.stdout, f"got {r}")

        symlink_path = Path(allowed_tmp) / "sneaky_link"
        try:
            symlink_path.symlink_to("/etc/passwd")
        except OSError:
            pass
        r = sb.run(f"with open({str(symlink_path)!r}) as f:\n    print(f.read())")
        check("5c. symlink pointing outside allowlist blocked", r.error is not None and "root:" not in r.stdout, f"got {r}")

        r = sb.run("open(1, 'w').write('hacked')")
        check("5d. raw file descriptor open(int) blocked", r.error is not None, f"got {r}")

        # --- 6. Network Isolation ---
        r = sb.run("import urllib.request\nurllib.request.urlopen('http://127.0.0.1:80', timeout=1)")
        check("6. network access blocked", r.error is not None, f"got {r}")

        # --- 7. Timeout & Uncatchable Timeout / State Reset ---
        r = sb.run("x_persisted = 999")
        r = sb.run("try:\n    while True:\n        pass\nexcept Exception:\n    print('swallowed!')")
        check("7a. timeout cannot be swallowed by 'except Exception: pass'", r.timeout and "swallowed!" not in r.stdout, f"got {r}")

        r = sb.run("print('still_alive')")
        check("7b. sandbox recovers immediately after timeout", r.error is None and "still_alive" in r.stdout, f"got {r}")

        # --- 8. Memory Limit & Worker Recovery ---
        r = sb.run("big = bytearray(450 * 1024 * 1024)")
        check("8a. memory limit enforced", r.error is not None, f"got {r}")

        r = sb.run("print('recovered_after_oom')")
        check("8b. sandbox recovers after memory limit error", r.error is None and "recovered_after_oom" in r.stdout, f"got {r}")

        # --- 9. Output Truncation & final_answer ---
        r = sb.run("print('A' * 20000)")
        check("9a. huge stdout is truncated with explicit marker", r.truncated and "truncated" in r.stdout.lower(), f"got {r}")

        r = sb.run("final_answer('')")
        check("9b. final_answer('') with empty string sets final_answer_bool=True", r.final_answer_bool and r.final_answer == "", f"got {r}")

    # --- 10. MCP Protocol: Positional Args, Import Skipping, Resources, Prompts, HTTP, Unknown Server ---
    with Sandbox(config=config, mcp_stdio=MBPP_SERVER_COMMAND) as sb:
        code = (
            "import json, run_tests\n"
            "res = json.loads(run_tests('def add(a, b): return a + b', ['assert add(2, 3) == 5']))\n"
            "print('POS_OK:', res['success'])\n"
        )
        r = sb.run(code)
        check("10a. MCP tool positional args + 'import <tool>' auto-skip works",
              r.error is None and "POS_OK: True" in r.stdout and "[NOTE]" in r.stdout, f"got {r}")

        r = sb.run("guide = read_resource('mbpp://guide/run_tests')\nprint(guide)")
        check("10b. MCP read_resource works inside sandbox", r.error is None and "run_tests" in r.stdout, f"got {r}")

        r = sb.run("p = get_prompt('solve_task', {'task_definition': 'sum', 'function_definition': 'def s(a,b):'})\nprint(p)")
        check("10c. MCP get_prompt works inside sandbox", r.error is None and "def s(a,b):" in r.stdout, f"got {r}")

        manual_text = sb.manual()
        check("10d. sandbox.manual() includes Tools, Resources, and Prompts sections",
              all(h in manual_text for h in ("## Tools", "## Resources", "## Prompts", "run_tests")),
              f"manual missing sections:\n{manual_text}")

    # Unknown MCP Server test (dynamically generated server with custom tools, resources, prompts, and blocked-builtin name 'eval')
    unknown_server_path = Path(allowed_tmp) / "unknown_mcp_server.py"
    unknown_server_path.write_text(
        "import os, sys\n"
        "sys.path.insert(0, os.getcwd())\n"
        "from src.mcp.server.server import MCPServer\n"
        "server = MCPServer(name='unknown-strict-server', version='9.9.9')\n"
        "@server.tool()\n"
        "def mystery_multiply(x: int, y: int = 3) -> str:\n"
        "    '''Multiply two ints.'''\n"
        "    return str(x * y)\n"
        "@server.tool()\n"
        "def eval(expr: str) -> str:\n"
        "    '''Tool named eval (shadows blocked builtin when connected).'''\n"
        "    return 'tool_eval:' + expr\n"
        "if __name__ == '__main__':\n"
        "    server.run()\n",
        encoding="utf-8",
    )
    with Sandbox(config=config, mcp_stdio=f"python {unknown_server_path}") as sb:
        manual_text = sb.manual()
        r1 = sb.run("print(mystery_multiply(7, 6))")
        r2 = sb.run("print(eval('hello'))")
        check("10e. unknown MCP server dynamic discovery, execution & blocked-builtin shadowing",
              r1.error is None and "42" in r1.stdout
              and r2.error is None and "tool_eval:hello" in r2.stdout
              and "mystery_multiply" in manual_text and "run_tests" not in manual_text,
              f"got r1={r1}, r2={r2}")

print("==========================================")
print(f" Strict Sandbox Exam Summary: {passed} passed, {failed} failed (Pass: ALL)")
print("==========================================")
sys.exit(0 if failed == 0 else 1)
PY

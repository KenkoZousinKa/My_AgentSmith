"""SWE-bench の MCP ツール9個を、自作クライアントから通しで呼ぶ確認用スクリプト.

testbed に確認用のファイル agentsmith_check/sample.py を作ってコミットし、
それを相手に各ツールの出力形式・エラー時の返り値を確かめる。

使い方（リポジトリの直下で）:
    # Docker（task.json の docker_image のコンテナ。終了時にコンテナは消える）
    uv run python -m test.mcp.swebench_tools_check --task-file ../cache/swebench_task.json
    # HTTP で（127.0.0.1:8000 が空いていれば、サーバーを自動起動する）
    uv run python -m test.mcp.swebench_tools_check --task-file ../cache/swebench_task.json --http
    # Docker なし（一時フォルダに git リポジトリを作って testbed にする。手元のリポジトリは触らない）
    uv run python -m test.mcp.swebench_tools_check --local
"""

import sys
import shlex
import argparse
import subprocess
import tempfile
from pathlib import Path

from src.models.input import SWEBenchTaskInput
from src.mcp.client.client import MCPClient, DEFAULT_URL
from src.mcp.client.stdio import StdioClientTransport
from src.mcp.client.http import HttpClientTransport
from mcp_tools_swebench import META_KEY

SERVER = f"{shlex.quote(sys.executable)} -c 'import mcp_tools_swebench as m; m.main()'"
# __main__ がデバッグ用に書きかえられていても動くよう、main() を直接呼ぶ

EXPECTED_TOOLS = {
    "read_file", "edit_file", "list_files", "search_code",
    "search_function_or_class_definition_in_code", "find_references",
    "run_tests", "get_patch", "run_command",
}

SAMPLE = '''import os


class Greeter:
    def greet(self, name):
        return "hello:" + name


def make_greeter():
    return Greeter()


async def fetch():
    flag = "-v flag"
    return make_greeter().greet(flag)
'''

LOCAL_EVAL = """#!/bin/bash
echo "setup log"
echo '>>>>> Start Test Output'
echo "TESTS_OK"
echo '>>>>> End Test Output'
echo "cleanup log"
"""

passed = failed = 0


def check(name: str, cond: bool, got: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {name}")
    else:
        failed += 1
        print(f"FAIL {name}\n----- got -----\n{got}\n---------------")


def text(client: MCPClient, tool: str, **args: object) -> str:
    result = client.call_tool(tool, args)
    return "".join(getattr(c, "text", "") or "" for c in result.content)


def agentsmith_containers() -> list[str]:
    r = subprocess.run(["docker", "ps", "-aq", "--filter", "label=agentsmith=1"],
                       capture_output=True, text=True)
    return r.stdout.split()


def run_checks(c: MCPClient, tb: str, docker: bool) -> None:
    sample = f"{tb}/agentsmith_check/sample.py"

    # --- tools/list ---
    names = {t.name for t in c.list_tools()}
    check("tools/list: 必須の9個がある", EXPECTED_TOOLS <= names, str(sorted(EXPECTED_TOOLS - names)))
    check("tools/list: 余計なツールが無い（_grep など）", names <= EXPECTED_TOOLS, str(sorted(names - EXPECTED_TOOLS)))

    # --- 準備：確認用ファイルを作ってコミット（get_patch の差分を確かめるため）---
    setup = (f"mkdir -p agentsmith_check && cat > agentsmith_check/sample.py <<'EOF'\n{SAMPLE}EOF\n"
             "git add agentsmith_check && "
             "git -c user.name=check -c user.email=check@example.com commit -qm agentsmith-check")
    out = text(c, "run_command", command=setup)
    check("準備: sample.py を作ってコミット", "exit_code: 0" in out, out)

    # --- run_command ---
    out = text(c, "run_command", command="pwd")
    check("run_command: 既定の workdir は testbed", f"--- stdout ---\n{tb}\n" in out, out)
    out = text(c, "run_command", command="pwd", workdir=f"{tb}/agentsmith_check")
    check("run_command: workdir を指定できる", f"{tb}/agentsmith_check\n" in out, out)
    out = text(c, "run_command", command="echo err >&2; exit 3")
    check("run_command: stderr と exit_code を返す", "exit_code: 3" in out and "err" in out, out)
    out = text(c, "run_command", command="cat")
    check("run_command: stdin を読むコマンドがすぐ終わる（MCP の stdin を奪わない）", "exit_code: 0" in out, out)
    # ↑ 直後の呼び出しが通ることも、MCP の通信が壊れていない証拠になる

    # --- read_file ---
    out = text(c, "read_file", filepath="agentsmith_check/sample.py", start_line=4, end_line=6)
    check("read_file: 範囲指定で '<n>: <line>' 形式",
          out == '4: class Greeter:\n5:     def greet(self, name):\n6:         return "hello:" + name', out)
    out = text(c, "read_file", filepath=sample)
    check("read_file: 絶対パス・全体", out.startswith("1: import os\n") and out.endswith("15:     return make_greeter().greet(flag)"), out)
    out = text(c, "read_file", filepath="agentsmith_check/nope.py")
    check("read_file: 無いファイルはメッセージを返す", "失敗" in out, out)

    # --- list_files ---
    out = text(c, "list_files", directory="agentsmith_check", pattern="*.py")
    check("list_files: 絶対パスで返す", out == sample, out)
    out = text(c, "list_files", directory="agentsmith_check", pattern="*.nothing")
    check("list_files: 0件はメッセージ", out.startswith("No files matched"), out)
    out = text(c, "list_files", directory="no_such_dir")
    check("list_files: 無いディレクトリはメッセージ", "失敗" in out, out)
    out = text(c, "list_files")
    check("list_files: 引数なしでも動き、.git を含まない", sample in out.splitlines() and "/.git/" not in out, out[:500])

    # --- search_code ---
    out = text(c, "search_code", pattern="hello:", file_pattern="*.py")
    check("search_code: '/abs/path:<n> <line>' 形式（中身の ':' を保つ）",
          f'{sample}:6         return "hello:" + name' in out.splitlines(), out)
    out = text(c, "search_code", pattern="-v flag")
    check("search_code: '-' で始まるパターン", f'{sample}:14     flag = "-v flag"' in out.splitlines(), out)
    out = text(c, "search_code", pattern="zzz_no_such_text_zzz")
    check("search_code: 0件はメッセージ", out.startswith("No matches"), out)
    out = text(c, "search_code", pattern="(")
    check("search_code: 正規表現の誤りはメッセージ", "失敗" in out, out)

    # --- search_function_or_class_definition_in_code ---
    tool = "search_function_or_class_definition_in_code"
    mine = lambda s: [l for l in s.splitlines() if l.startswith(sample + ":")]  # noqa: E731
    out = text(c, tool, name="Greeter")
    check("definition: class", mine(out) == [f"{sample}:4 class Greeter:"], out)
    out = text(c, tool, name="Greeter.greet")
    check("definition: 'Class.method' 形式", mine(out) == [f"{sample}:5     def greet(self, name):"], out)
    out = text(c, tool, name="fetch")
    check("definition: async def", f"{sample}:13 async def fetch():" in mine(out), out)
    out = text(c, tool, name="bad name(")
    check("definition: 不正な名前はメッセージ", "不正" in out, out)

    # --- find_references ---
    out = text(c, "find_references", name="make_greeter", filepath=sample, line=9)
    check("find_references: 定義と使用箇所", [l.split(" ", 1)[0] for l in mine(out)] == [f"{sample}:9", f"{sample}:15"], out)

    # --- edit_file → get_patch ---
    out = text(c, "edit_file", filepath="agentsmith_check/sample.py",
               old_str='return "hello:" + name', new_str='return "hi:" + name')
    check("edit_file: 置きかえ成功", "失敗" not in out and "exit_code" not in out, out)
    out = text(c, "read_file", filepath="agentsmith_check/sample.py", start_line=6, end_line=6)
    check("edit_file: 中身が変わっている", out == '6:         return "hi:" + name', out)
    out = text(c, "edit_file", filepath="agentsmith_check/sample.py", old_str="no such text", new_str="x")
    check("edit_file: 見つからない old_str はメッセージ", out != "" and "hi:" not in out, out)
    out = text(c, "get_patch")
    check("get_patch: unified diff",
          out.startswith("diff --git a/agentsmith_check/sample.py") and
          '-        return "hello:" + name' in out and '+        return "hi:" + name' in out, out)

    # --- run_tests ---（出力は抽出せず全部返す仕様）
    out = text(c, "run_tests")
    check("run_tests: 時間内に終わる", not out.startswith("Timeout"), out[:800])
    if docker:
        check("run_tests: eval_script の出力（テスト結果の印を含む）を返す", "Start Test Output" in out, out[-800:])
        lines = out.splitlines()
        start = next(i for i, line in enumerate(lines) if "Start Test Output" in line)
        print("----- run_tests の出力（テスト部分）-----")
        print("\n".join(lines[start:start + 60]))  # 印の行から（長いタスクでも 60 行まで）
    else:
        check("run_tests: eval_script の出力を全部返す",
              out == "setup log\n>>>>> Start Test Output\nTESTS_OK\n>>>>> End Test Output\ncleanup log", out)


def main() -> int:
    parser = argparse.ArgumentParser(description="SWE-bench MCP tools check")
    parser.add_argument("--task-file", default="../cache/swebench_task.json")
    parser.add_argument("--local", action="store_true", help="Docker を使わず、一時フォルダの git リポジトリで確かめる")
    parser.add_argument("--http", action="store_true", help="stdio ではなく HTTP でつなぐ")
    args = parser.parse_args()

    if args.local:
        tb = tempfile.mkdtemp(prefix="agentsmith_tb_")
        subprocess.run(["git", "init", "-q", tb], check=True)
        meta = {META_KEY: {"testbed_path": tb, "eval_script": LOCAL_EVAL}}
    else:
        task = SWEBenchTaskInput.model_validate_json(Path(args.task_file).read_text(encoding="utf-8"))
        tb = "/testbed"
        meta = {META_KEY: {"docker_image": task.docker_image, "eval_script": task.eval_script}}
        print(f"image: {task.docker_image}")

    transport: StdioClientTransport | HttpClientTransport
    if args.http:
        transport = HttpClientTransport(DEFAULT_URL, command=f"{SERVER} --transport http", timeout=610)
    else:
        transport = StdioClientTransport(SERVER)

    with MCPClient(transport, init_meta=meta) as client:
        if not args.local:
            check("Docker: initialize でコンテナが1つ起動", len(agentsmith_containers()) == 1, str(agentsmith_containers()))
        run_checks(client, tb, docker=not args.local)

    if not args.local:
        check("Docker: 終了後にコンテナが残っていない", agentsmith_containers() == [], str(agentsmith_containers()))
    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

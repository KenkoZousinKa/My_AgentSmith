"""mcp_tools_swebench.py"""

import os
import posixpath
import signal
import argparse
import shlex
import base64
from typing import Any

from src.mcp.server.server import MCPServer
from src.mcp.server.http import HttpServerTransport
from src.mcp.swe_bench.executor import DockerExecutor, Executor, LocalExecutor
from src.mcp.swe_bench.edit_script import EDIT_SCRIPT

COMMAND_TIMEOUT = 120
META_KEY = "agentsmith/swebench"

server = MCPServer(name="agent-smith-swebench", version="0.1.0")
executor: Executor = LocalExecutor()

# testbed_path: str = "/testbed"
testbed_path: str = "."
eval_script: str | None = None
# on_initializeで環境変数から動的に代入される


# ====== File System Tools ======


@server.tool()
def read_file(filepath: str, start_line: int | None = None, end_line: int | None = None) -> str:
    """Read a file with line numbers (like `cat -n`).

    start_line/end_line are 1-based and inclusive; omit them to read from the start or to the end.
    """
    if (start_line is not None and start_line < 0) or (end_line is not None and end_line < 0):
        return f"負の値が入力されました。 start_line: {start_line} end_line: {end_line}"
    if start_line is not None and end_line is not None and end_line < start_line:
        return f"start_lineがend_lineを超えています。 start_line: {start_line} end_line: {end_line}"

    r = executor.run(f"cat -n {shlex.quote(filepath)}", testbed_path, COMMAND_TIMEOUT)
    if r.exit_code != 0:
        return f"ファイル読み込みに失敗しました。 {r.stderr}"

    all_lines = r.stdout.split("\n")
    if all_lines and all_lines[-1] == "":
        all_lines.pop()
    if start_line is None and end_line is None:
        return "\n".join(_format_line(line) for line in all_lines)

    lines = all_lines[start_line - 1 if start_line else start_line:end_line]
    if "\n".join(lines) == "":
        return f"ファイルは{len(all_lines)}行です。"

    return "\n".join(_format_line(line) for line in lines)


def _format_line(line: str) -> str:
    """cat -n の中身を指定フォーマットに整える."""
    number, _, content = line.partition("\t")
    return f"{number.strip()}: {content}"


@server.tool()
def edit_file(filepath: str, old_str: str, new_str: str) -> str:
    """Replace an exact string in a file with a new string.

    old_str must match exactly once (including whitespace); include surrounding lines to make it unique.
    """
    # エスケープをしなくていい英数字だけで表せるbase64に一度変換する。
    old_b64 = base64.b64encode(old_str.encode("utf-8")).decode("ascii")
    new_b64 = base64.b64encode(new_str.encode("utf-8")).decode("ascii")

    args = " ".join(shlex.quote(a) for a in [EDIT_SCRIPT, filepath, old_b64, new_b64])
    command = f"python3 -c {args}"

    r = executor.run(command, testbed_path, COMMAND_TIMEOUT)
    if r.exit_code in (0, 1) and r.stdout.strip():
        return r.stdout.strip()
    return f"exit_code: {r.exit_code}\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"


@server.tool()
def list_files(directory: str = ".", pattern: str = "*") -> str:
    """List files under a directory whose name matches a glob pattern (e.g. "*.py")."""
    base = posixpath.normpath(posixpath.join(testbed_path, directory))
    # normpath："/testbed/." → "/testbed"
    command = (f"set -o pipefail; find {shlex.quote(base)} -path '*/.git' -prune -o "
               f"-type f -name {shlex.quote(pattern)} -print | sort")
    #   -path '*/.git' -prune -o .gitには入らないでそれ以外で
    #   -type f -name '*' -print  ファイルかつ名前を指定してプリントする
    #   -print 式終了後の全てのファイルをprintさせないため
    #   pipefail どのパイプラインでerrorが起きても終了コードは1になる

    r = executor.run(command, testbed_path, COMMAND_TIMEOUT)

    files = r.stdout.splitlines()
    if r.exit_code != 0 and not files:  # 一部のサブフォルダが読めないだけならエラーにしない
        return f"ファイル一覧の取得に失敗しました。 {r.stderr.strip()}"
    if not files:
        return f"No files matched '{pattern}' under {base}"
    return "\n".join(files)


# ====== Code Search Tools ======


@server.tool()
def search_code(pattern: str, file_pattern: str | None = None) -> str:
    """Search the repository for a regex (grep -E). file_pattern filters file names (e.g. "*.py")."""
    return _grep(pattern, file_pattern)


@server.tool()
def search_function_or_class_definition_in_code(name: str) -> str:
    """Find where a function or class is defined (e.g. "Add" or "Add._eval_is_zero")."""
    name = name.rsplit(".", 1)[-1]  # "Class.method" -> "method"
    if not name.isidentifier():  # Pythonの名前として正しいか
        return f"'{name}' は Python の名前として不正です。"
    regex = rf"^[[:space:]]*(async[[:space:]]+)?(def|class)[[:space:]]+{name}\b"
    # ^[[:space:]]*         行の先頭（^）から、スペースやタブ（[[:space:]]*）が0文字以上続く状態。-> インデント
    # (async[[:space:]]+)? asyncがあってもなくても良い（?）。 -> async defもヒット
    # (def|class)          -> def | class
    # [[:space:]]          (def|class)の後ろに1文字以上のスペースがあること。 -> def _grep
    # {name}\b             {name}という単語で始まり、終わっている。 -> ✅def swe() ❌def swe_bench()
    return _grep(regex, "*.py")


@server.tool()
def find_references(name: str, filepath: str | None = None, line: int | None = None) -> str:
    """Find all usages of a function or class name in *.py files (word match, includes the definition)."""
    name = name.rsplit(".", 1)[-1]  # "Class.method" → "method"
    if not name.isidentifier():
        return f"'{name}' は Python の名前として不正です。"
    return _grep(rf"\b{name}\b", "*.py")
    # \b：単語の境界。"Add" で "AddSubContext" や "_Add" に一致しない


def _grep(regex: str, file_pattern: str | None) -> str:
    """testbed を grep して search_code 形式（/abs/path:<n> <line>）の文字列を返す."""
    include = f"--include={shlex.quote(file_pattern)} " if file_pattern else ""
    command = (f"grep -rnIEZ --exclude-dir=.git {include}"
               f"-e {shlex.quote(regex)} -- {shlex.quote(testbed_path)}")
    # -r ディレクトリ指定 / -n 行番号 / -I バイナリを飛ばす / -E 拡張正規表現（| や + がそのまま使える）
    # -Z：ファイル名の直後を ":" ではなく NUL 文字にする → パスや中身に ":" があっても確実に区切れる
    # -e：pattern が "-" で始まっても、オプションと誤解されないようにする
    # --：ここから先はオプションではなくパス、という区切り
    # --include: ファイル名を指定
    # testbed_path を絶対パスで渡すので、出力のパスも絶対パスになる

    r = executor.run(command, testbed_path, COMMAND_TIMEOUT)

    hits: list[tuple[str, int, str]] = []
    for line in r.stdout.splitlines():
        path, _, rest = line.partition("\0")        # "path" と "12:中身" に分ける
        number, _, content = rest.partition(":")   # 最初の ":" で行番号と中身に分ける
        hits.append((path, int(number), content))

    if r.exit_code == 2 and not hits:
        return f"検索に失敗しました。 {r.stderr.strip()}"  # 0 = 見つかった / 1 = 0件 / 2 = エラー（正規表現の誤り、パスが無いなど）
    if not hits:
        return f"No matches for '{regex}' (file_path: {file_pattern})"
    hits.sort(key=lambda h: (h[0], h[1]))  # パス → 行番号の順に並べる

    return "\n".join(f"{path}:{number} {content}" for path, number, content in hits)


# ====== Execution Tools ======


EVAL_TIMEOUT = 300
EVAL_PATH = "/tmp/agentsmith_eval.sh"
TEST_START, TEST_END = ">>>>> Start Test Output", ">>>>> End Test Output"


@server.tool()
def run_tests() -> str:
    """Run the task's evaluation script and return its test output."""
    if not eval_script:
        return "eval_script が設定されていません。"

    command = f"cat > {EVAL_PATH} && bash {EVAL_PATH} 2>&1"
    # eval_scriptをstdinに流してEVAL_PATHに書き込んでそこから実行する -> 引数のバイト上限
    # 2>&1： stderrをstdoutに流して一つにまとめる
    r = executor.run(command, testbed_path, EVAL_TIMEOUT, input=eval_script)

    lines = r.stdout.splitlines()
    # 結果が冗長なら追加
    # marks = [i for i, line in enumerate(lines) if TEST_START in line or TEST_END in line]
    # if len(marks) >= 2:
    #     lines = lines[marks[0] + 1:marks[-1]]  # 印の間（採点と同じ範囲）だけ
    output = "\n".join(lines)

    if r.exit_code == 124:  # timeout コマンドの終了コード
        return f"Timeout after {EVAL_TIMEOUT}s\n{output}"
    return output
    # exit_code は使わない：テストが失敗しても最後の git checkout が成功すると 0 になる


@server.tool()
def get_patch() -> str:
    """Return the unified git diff of all changes in the repository."""
    r = executor.run("git -c core.fileMode=false diff", testbed_path, COMMAND_TIMEOUT)
    # core.fileMode=false：パーミッションだけの変更を無視する
    if r.exit_code != 0:
        return f"パッチの取得に失敗しました。 {r.stderr.strip()}"
    return r.stdout  # 変更なしなら ""（final_answer にそのまま渡すので、メッセージは混ぜない）


@server.tool()
def run_command(command: str, workdir: str | None = None) -> str:
    """Execute a shell command in the given working directory.

    Returns the command's stdout, stderr and exit code.
    """
    r = executor.run(command, workdir or testbed_path, COMMAND_TIMEOUT)
    return f"exit_code: {r.exit_code}\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"


# ====== Private ======


def _on_sigterm(signum: int, frame: object) -> None:
    raise SystemExit(0)
    # ↑ SIGTERM を受けたら、SystemExit を起こす。これで main() の finally が動き、コンテナを片付けられる
    #   （何もしないと、Python は SIGTERM で即座に終わり、finally が動かない）


@server.on_initialize()
def setup(meta: dict[str, Any] | None) -> None:
    global executor, testbed_path, eval_script
    conf = (meta or {}).get(META_KEY) or {}
    image = conf.get("docker_image") or os.environ.get("SWE_DOCKER_IMAGE")
    testbed_path = conf.get("testbed_path") or os.environ.get("TESTBED_PATH", "/testbed")
    eval_script = conf.get("eval_script") or os.environ.get("SWE_EVAL_SCRIPT")

    executor.close()          # ★ 2回目の initialize（作り直し）に備えて、古いコンテナを先に片付ける
    executor = LocalExecutor()
    if image:
        docker = DockerExecutor(image)
        docker.start()        # 失敗したら例外 → initialize がエラーで返る
        executor = docker


def main() -> None:
    parser = argparse.ArgumentParser(description="SWE-bench MCP Server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # on_initilaizeにコンテナ立ち上げは以降
    # global executor
    # image = os.environ.get("SWE_DOCKER_IMAGE")
    # if image:
    #     docker = DockerExecutor(image)
    #     docker.start()
    #     executor = docker
    signal.signal(signal.SIGTERM, _on_sigterm)
    try:
        if args.transport == "http":
            server.run(HttpServerTransport(host=args.host, port=args.port))
        else:
            server.run()
    finally:
        executor.close()


if __name__ == "__main__":
    # print(read_file("./Makefile", 20, 40))
    # print(edit_file("test.py", "Makefile", "test.py"))
    # print(list_files())
    # print(search_code("aaa", "bbb"))
    # print(search_function_or_class_definition_in_code("_grep"))
    # print(find_references("_grep"))
    # print(run_tests())
    print(get_patch())
    # main()

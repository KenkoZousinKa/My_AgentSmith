"""mcp_tools_swebench.py."""

import re
import os
import sys
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

testbed_path: str = "/testbed"
# testbed_path: str = "."
eval_script: str | None = None
# on_initializeで環境変数から動的に代入される

LOGICAL_ROOT = "/testbed"  # エージェントやテストから見えるリポジトリの場所


def _resolve(path: str) -> str:
    """/testbed 始まりのパスを、実際の testbed_path の下のパスに読み替える."""
    # normpathはパスを整理、pathが絶対パスならLOGICAL_ROOTは捨てられる。相対なら後ろに繋げる
    norm = posixpath.normpath(posixpath.join(LOGICAL_ROOT, path))
    # "/testbed"そのもの or ”testbed/”より下層をpathが指定していた場合
    if norm == LOGICAL_ROOT or norm.startswith(LOGICAL_ROOT + "/"):
        # "/testbed"に、関数に渡されたpathのうち"/testbed"以降を繋げて返す
        return testbed_path + norm[len(LOGICAL_ROOT):]
    return norm  # "/testbed"までのパスも一緒に返す


# ====== File System Tools ======


@server.tool()
def read_file(filepath: str, start_line: int | None = None, end_line: int | None = None) -> str:
    """Read a file with line numbers (like `cat -n`).

    start_line/end_line are 1-based and inclusive; omit them to read from the start or to the end.
    """
    # 引数のバリデーションを行う。負の値やstart_lineがend_lineを超える場合はエラーを返す。
    if (start_line is not None and start_line < 0) or (end_line is not None and end_line < 0):
        return f"Negative values were given. start_line: {start_line} end_line: {end_line}"
    if start_line is not None and end_line is not None and end_line < start_line:
        return f"start_line is greater than end_line. start_line: {start_line} end_line: {end_line}"

    # ファイルの内容を取得して行ごとに分割する。
    r = executor.run(f"cat -n {shlex.quote(_resolve(filepath))}", testbed_path, COMMAND_TIMEOUT)
    if r.exit_code != 0:
        return f"Failed to read the file. {r.stderr}"

    # 空行を取り除く。
    all_lines = r.stdout.split("\n")
    if all_lines and all_lines[-1] == "":
        all_lines.pop()

    # start_line/end_lineが指定されていない場合は全行を返す。
    if start_line is None and end_line is None:
        return "\n".join(_format_line(line) for line in all_lines)

    # start_line/end_lineが指定されている場合はその範囲の行を抽出する。
    lines = all_lines[start_line - 1 if start_line else start_line:end_line]
    if "\n".join(lines) == "":
        return f"The file has {len(all_lines)} lines."

    return "\n".join(_format_line(line) for line in lines)


def _format_line(line: str) -> str:
    """'cat -n 'の中身を指定フォーマットに整える."""
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

    # ファイル内の文字列を置換するためのコマンドを組み立てる。
    args = " ".join(shlex.quote(a) for a in [EDIT_SCRIPT, _resolve(filepath), old_b64, new_b64])
    command = f"python3 -c {args}"

    # コマンドを実行してファイルを編集。
    r = executor.run(command, testbed_path, COMMAND_TIMEOUT)
    if r.exit_code in (0, 1) and r.stdout.strip():
        return r.stdout.strip()
    return f"exit_code: {r.exit_code}\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"


@server.tool()
def list_files(directory: str = ".", pattern: str = "*") -> str:
    """List files under a directory whose name matches a glob pattern (e.g. "*.py")."""
    # ディレクトリのパスを正規化して取得。 "/testbed/." → "/testbed"
    base = _resolve(directory)

    command = (f"set -o pipefail; find {shlex.quote(base)} -path '*/.git' -prune -o "
               f"-type f -name {shlex.quote(pattern)} -print | sort")
    #   -path '*/.git' -prune -o .gitには入らないでそれ以外で
    #   -type f -name '*' -print  ファイルかつ名前を指定してプリントする
    #   -print 式終了後であれば.gitもプリントしてしまうためこの位置でprintする
    #   pipefail どのパイプラインでerrorが起きても終了コードは1になる

    r = executor.run(command, testbed_path, COMMAND_TIMEOUT)

    # コマンド実行後の標準出力を行ごとに分割してファイル一覧を取得する。
    files = r.stdout.splitlines()
    # 一部のサブフォルダが読めないだけならエラーにはしない
    if r.exit_code != 0 and not files:
        return f"Failed to list files. {r.stderr.strip()}"
    if not files:
        return f"No files matched '{pattern}' under {base}"
    return "\n".join(files)


# ====== Code Search Tools ======


@server.tool()
def search_code(pattern: str, file_pattern: str | None = None) -> str:
    """Search the repository for a regex (grep -E). file_pattern filters file names (e.g. "*.py")."""
    # codeパターンとファイル名を指定してコードを検索する。
    return _grep(pattern, file_pattern)


@server.tool()
def search_function_or_class_definition_in_code(name: str) -> str:
    """Find where a function or class is defined (e.g. "Add" or "Add._eval_is_zero")."""
    name = name.rsplit(".", 1)[-1]  # "Class.method" -> "method"
    if not name.isidentifier():  # Pythonの名前として正しいか
        return f"'{name}' is not a valid Python name."
    # 関数やクラスの定義を検索するための正規表現を作成する。
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
        return f"'{name}' is not a valid Python name."
    # 指定された名前を単語単位で検索する正規表現を作成してgrepする。
    # \b：単語の境界。"Add" で "AddSubContext" や "_Add" に一致しない
    return _grep(rf"\b{name}\b", "*.py")


def _grep(regex: str, file_pattern: str | None) -> str:
    """testbedをgrepしてsearch_code 形式（/abs/path:<n> <line>）の文字列を返す."""
    # grepコマンドのオプションや引数を組み立てる。
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

    # grepの出力を解析して、(path, line_number, content) のタプルのリストに変換する。
    hits: list[tuple[str, int, str]] = []
    for line in r.stdout.splitlines():
        path, _, rest = line.partition("\0")        # "path" と "12:中身" に分ける
        number, _, content = rest.partition(":")   # 最初の ":" で行番号と中身に分ける
        hits.append((path, int(number), content))

    # タプルのリストをパスと行番号でソートする。
    if r.exit_code == 2 and not hits:
        return f"Search failed. {r.stderr.strip()}"  # 0 = 見つかった / 1 = 0件 / 2 = エラー（正規表現の誤り、パスが無いなど）
    # grepがエラーを返した場合の処理（exit_code == 2 は正規表現の誤りやパスが無いなど）
    if not hits:
        return f"No matches for '{regex}' (file_path: {file_pattern})"
    hits.sort(key=lambda h: (h[0], h[1]))  # パス → 行番号の順に並べる

    # ソート後のタプルのリストを文字列に変換して返す。
    return "\n".join(f"{path}:{number} {content}" for path, number, content in hits)


# ====== Execution Tools ======


EVAL_TIMEOUT = 300  # run_tests のタイムアウト時間（秒）
EVAL_PATH = "/tmp/agentsmith_eval.sh"  # 評価スクリプトを一時的に保存するパス
TEST_START, TEST_END = ">>>>> Start Test Output", ">>>>> End Test Output"  # テスト出力の開始・終了マーカー

# === add iroha ===
# run_tests の最後の行(判定)の書き出し。エージェントは "RESULT: PASSED" in run_tests() で通ったかをコードで確かめる
VERDICT_PASSED, VERDICT_FAILED, VERDICT_UNKNOWN = "RESULT: PASSED", "RESULT: FAILED", "RESULT: UNKNOWN"
# pytest の要約行。例: "==== 1 failed, 3 passed, 2 warnings in 0.12s ====" （古い版は "in 0.12 seconds"）
PYTEST_SUMMARY = re.compile(
    r"^=+ (?P<counts>.*\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?).*)"
    r" in [\d.]+ ?s(?:econds)?\b.*=+$"
)
# sympy の bin/test の要約行。例: "==== tests finished: 3 passed, 1 failed, 1 exceptions, in 0.52 seconds ===="
# 長いと "in 40.47 seconds" が次の行へ折り返されるので、"in ... seconds" は無くてもよい
SYMPY_SUMMARY = re.compile(r"tests finished: (?P<counts>.*?),?(?: in [\d.]+ seconds)?\s*=*$")
# django の runtests.py の要約。"Ran 5 tests in 0.010s" の次の "OK" / "OK (skipped=1)" / "FAILED (failures=1, errors=2)"
DJANGO_RAN = re.compile(r"^Ran (?P<total>\d+) tests? in [\d.]+s$")
DJANGO_RESULT = re.compile(r"^(?P<status>OK|FAILED)(?: \((?P<details>[^)]*)\))?$")
SUMMARY_COUNT = re.compile(r"(\d+) ([a-z][a-z ]*?)(?=,|$)")  # 要約の中の「数 種類」。"1 failed" "2 expected to fail" など
FAILURE_WORDS = ("failed", "error", "errors", "exceptions")  # 1つでもあれば「落ちた」とする種類
# === add iroha ===

@server.tool()
def run_tests() -> str:
    """Run the task's evaluation script and return its test output."""
    if not eval_script:
        return "eval_script is not set."

    # 評価スクリプトを一時ファイルに書き込み、そこから実行するコマンドを組み立てる。 -> 引数のバイト上限
    command = f"cat > {EVAL_PATH} && bash {EVAL_PATH} 2>&1"
    # 2>&1： stderrをstdoutに流して一つにまとめる
    r = executor.run(command, testbed_path, EVAL_TIMEOUT, input=eval_script)

    # コマンドの実行結果を行単位で取得する。
    lines = r.stdout.splitlines()
    # テスト出力の開始・終了マーカーを探す。
    marks = [i for i, line in enumerate(lines) if TEST_START in line or TEST_END in line]
    if len(marks) >= 2:
        lines = lines[marks[0] + 1:marks[-1]]  # 印の間（採点と同じ範囲）だけ
    output = "\n".join(lines)

    # タイムアウトの場合はテストファイルを元に戻す処理を行う。
    if r.exit_code in (124, 137):  # timeout コマンドの終了コード or SIGKILL
        for line in reversed(eval_script.splitlines()):
            if line.startswith("git checkout "):
                executor.run(line, testbed_path, COMMAND_TIMEOUT)  # テストファイルを元に戻す
                break
        return f"Timeout after {EVAL_TIMEOUT}s\n{output}\n{VERDICT_FAILED} (timeout after {EVAL_TIMEOUT}s)"
    return f"--- result run_tests ---\n{output}\n{_test_verdict(output)}"
    # exit_code は使わない：テストが失敗しても最後の git checkout が成功すると 0 になる


def _test_verdict(output: str) -> str:
    """テストの出力の要約行から、全部通ったかを1行で返す.

    LLM は出力の一部（末尾の1500字など）だけを見ることが多く、通ったかを読むのに1反復使ってから提出していた。
    判定を決まった1行にしておけば、エージェントは通った同じ反復のコードの中で提出できる。

    Args:
        output (str): テスト出力の開始・終了マーカーの間の出力。

    Returns:
        str: "RESULT: PASSED (4 passed)" / "RESULT: FAILED (1 failed, 3 passed)" / "RESULT: UNKNOWN (...)" の1行。
    """
    counts = _summary_counts(output.splitlines())
    if counts is None:
        return f"{VERDICT_UNKNOWN} (no test summary line found; read the output above)"
    shown = ", ".join(f"{number} {word}" for word, number in counts.items())
    if sum(counts.get(word, 0) for word in FAILURE_WORDS) > 0:
        return f"{VERDICT_FAILED} ({shown})"
    if counts.get("passed", 0) == 0:
        return f"{VERDICT_UNKNOWN} (no test passed: {shown})"
    return f"{VERDICT_PASSED} ({shown})"


def _summary_counts(lines: list[str]) -> dict[str, int] | None:
    """テストの出力を下から見て、最後の要約行の {種類: 数} を返す.

    pytest（xarray・scikit-learn など）・sympy の bin/test・django の runtests.py の3つの形を読む。

    Args:
        lines (list[str]): テストの出力の行。

    Returns:
        dict[str, int] | None: {"passed": 3, "failed": 1} のような数。要約行がなければ None。
    """
    for index in range(len(lines) - 1, -1, -1):
        line = lines[index].strip()
        summary = PYTEST_SUMMARY.match(line) or SYMPY_SUMMARY.search(line)
        if summary:
            counts: dict[str, int] = {}
            for number, word in SUMMARY_COUNT.findall(summary.group("counts")):
                counts[word.strip()] = counts.get(word.strip(), 0) + int(number)
            return counts
        ran = DJANGO_RAN.match(line)
        if ran:
            return _django_counts(int(ran.group("total")), lines[index + 1:])
    return None


def _django_counts(total: int, rest: list[str]) -> dict[str, int] | None:
    """Django の "Ran N tests" の後の "OK" / "FAILED (...)" の行から {種類: 数} を返す.

    Args:
        total (int): "Ran N tests" の N。
        rest (list[str]): "Ran N tests" の行より後ろの行。

    Returns:
        dict[str, int] | None: {"passed": 4} / {"passed": 3, "failed": 1} のような数。OK / FAILED の行がなければ None。
    """
    result = next((DJANGO_RESULT.match(line.strip()) for line in rest if line.strip()), None)
    if result is None:
        return None
    details: dict[str, int] = {}
    for item in (result.group("details") or "").split(","):
        if "=" in item:
            key, value = item.split("=", 1)
            details[key.strip()] = int(value)
    failed = details.get("failures", 0) + details.get("errors", 0)
    if result.group("status") == "FAILED" and failed == 0:
        failed = 1  # 内訳のない FAILED も落ちたとみなす
    counts = {"passed": total - failed - details.get("skipped", 0)}
    if failed:
        counts["failed"] = failed
    return counts


@server.tool()
def get_patch() -> str:
    """Return the unified git diff of all changes in the repository."""
    command = "git add -N . && git -c core.fileMode=false diff HEAD"
    # add -N：新規ファイルを「追加予定」として登録し diff に出す（.gitignore 対象は自動で除外）
    # core.fileMode=false：パーミッションだけの変更を無視する
    # diff HEAD：最後のコミットとの差分を取る（git add 済みの変更も漏らさない）
    # core.fileMode=false：パーミッションだけの変更を無視する
    r = executor.run(command, testbed_path, COMMAND_TIMEOUT)
    if r.exit_code != 0:
        return f"Failed to get the patch. {r.stderr.strip()}"
    return r.stdout  # 変更なしなら ""（final_answer にそのまま渡すので、メッセージは混ぜない）


@server.tool()
def run_command(command: str, workdir: str | None = None) -> str:
    """Execute a shell command in the given working directory.

    Returns the command's stdout, stderr and exit code.
    """
    r = executor.run(command, _resolve(workdir) if workdir else testbed_path, COMMAND_TIMEOUT)
    return f"exit_code: {r.exit_code}\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"


# ====== Private ======


def _on_sigterm(signum: int, frame: object) -> None:
    print("[Server] MCP_TOOLS_SWEBENCHを終了します。", file=sys.stderr)
    raise SystemExit(0)
    # ↑ SIGTERM を受けたら、SystemExit を起こす。これで main() の finally が動き、コンテナを片付けられる
    #   （何もしないと、Python は SIGTERM で即座に終わり、finally が動かない）


@server.on_initialize()
def setup(meta: dict[str, Any] | None) -> None:
    """初期化時にツールが実行する環境を設定する.

    Args:
        meta (dict[str, Any] | None): 初期化時に渡されるメタ情報。None の場合もある。
    """
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
    """LLMがSWE-benchテストに使用するツールを提供するサーバーを作成する."""
    parser = argparse.ArgumentParser(description="SWE-bench MCP Server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _on_sigterm)  # SIGTERMを受け取ったら_on_sigterm()を実行する
    try:
        print("[Server] MCP_TOOLS_SWEBENCHを起動します。", file=sys.stderr)
        if args.transport == "http":
            server.run(HttpServerTransport(host=args.host, port=args.port))
        else:
            server.run()
    except Exception as e:
        print(f"[Server] Error: {e}", file=sys.stderr)
    except KeyboardInterrupt:
        print("[Server] Interrupted by user.", file=sys.stderr)
    finally:
        executor.close()
        print("[Server] MCP_TOOLS_SWEBENCHを終了しました。", file=sys.stderr)


if __name__ == "__main__":
    main()

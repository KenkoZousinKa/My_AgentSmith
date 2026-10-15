"""mcp_tools_swebench.py"""

import os
import signal
import argparse
import shlex
import base64

from src.mcp.server.server import MCPServer
from src.mcp.server.http import HttpServerTransport
from src.mcp.swe_bench.executor import DockerExecutor, Executor, LocalExecutor
from src.mcp.swe_bench.edit_script import EDIT_SCRIPT

server = MCPServer(name="agent-smith-swebench", version="0.1.0")
TESTBED_PATH = os.environ.get("TESTBED_PATH", "/testbed")
COMMAND_TIMEOUT = 120
executor: Executor = LocalExecutor()


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

    r = executor.run(f"cat -n {shlex.quote(filepath)}", TESTBED_PATH, COMMAND_TIMEOUT)
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
    """cat -n の1行 '     2\\t中身' を '2: 中身' にする."""
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

    # r = executor.run(command, TESTBED_PATH, COMMAND_TIMEOUT)
    r = executor.run(command, ".", COMMAND_TIMEOUT)
    if r.exit_code in (0, 1) and r.stdout.strip():
        return r.stdout.strip()
    return f"exit_code: {r.exit_code}\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"


# ====== Execution Tools ======


@server.tool()
def run_command(command: str, workdir: str = TESTBED_PATH) -> str:
    """Execute a shell command in the given working directory.

    Returns the command's stdout, stderr and exit code.
    """
    r = executor.run(command, workdir, COMMAND_TIMEOUT)
    return f"exit_code: {r.exit_code}\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"


# ====== Private ======


def _on_sigterm(signum: int, frame: object) -> None:
    raise SystemExit(0)
    # ↑ SIGTERM を受けたら、SystemExit を起こす。これで main() の finally が動き、コンテナを片付けられる
    #   （何もしないと、Python は SIGTERM で即座に終わり、finally が動かない）


def main() -> None:
    parser = argparse.ArgumentParser(description="SWE-bench MCP Server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    global executor
    image = os.environ.get("SWE_DOCKER_IMAGE")
    if image:
        docker = DockerExecutor(image)
        docker.start()
        executor = docker
    signal.signal(signal.SIGTERM, _on_sigterm)
    try:
        if args.transport == "http":
            server.run(HttpServerTransport(host=args.host, port=args.port))
        else:
            server.run()
    finally:
        executor.close()


if __name__ == "__main__":
    # print(edit_file("test.py", "Makefile", "test.py"))
    # print(read_file("./Makefile", 20, 40))
    main()

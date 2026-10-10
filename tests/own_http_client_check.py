"""自作クライアント（HttpClientTransport）を、JSON と SSE の両方のサーバーで確かめる.

実行: uv run --with "mcp==1.26.0" python -m tests.own_http_client_check
    （-m で起動すると、リポジトリの一番上が探索先になり、src を import できる）
  1. SSE の読み取り（サーバーなし）
  2. 自作サーバー（JSON で返す）… 8000 番が空いていれば、自動起動から確かめる
  3. FastMCP（SSE で返す）       … このスクリプトが 8001 番で起動して、終わったら止める
  4. 起動していない別の URL       … 自作サーバーを勝手に起動しないこと
"""

import io
import socket
import subprocess
import sys
import time
from typing import Any

from src.mcp_core.client.client import MCPClient
from src.mcp_core.client.http import HttpClientTransport
from src.mcp_core.models import mcpmodel as mcp

OWN_URL = "http://127.0.0.1:8000/mcp"
FAST_PORT = 8001
FAST_URL = f"http://127.0.0.1:{FAST_PORT}/mcp"
results = {"PASS": 0, "FAIL": 0}


def check(ok: bool, what: str, detail: Any = "") -> None:
    """結果を1行で表示して数える."""
    mark = "\033[32mPASS\033[0m" if ok else "\033[31mFAIL\033[0m"
    print(f"  {mark}  {what}" + ("" if ok else f"（実際: {detail!r}）"))
    results["PASS" if ok else "FAIL"] += 1


def is_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def own_server_pids() -> set[str]:
    """動いている自作サーバー（mcp_tools_mbpp.py --transport http）の PID の集合."""
    out = subprocess.run(["pgrep", "-f", "mcp_tools_mbpp.py --transport http"],
                         capture_output=True, text=True)
    return set(out.stdout.split())
    # 手で起動したサーバーも含まれるので、「動いているか」ではなく
    # 「確認の前後で増えたか」で判定する


def test_read_event() -> None:
    print("== 1. SSE の読み取り（サーバーなし）")
    t = HttpClientTransport(OWN_URL)
    fake = io.BytesIO(
        b'event: message\r\ndata: {"a":1}\r\n\r\n'        # 普通のイベント（行末 \r\n）
        b": ping\r\n\r\n"                                  # コメントだけのイベント → 飛ばす
        b"data: {\r\ndata:   \"b\": 2\r\ndata: }\r\n\r\n"  # data が 3 行 → \n でつなぐ
        b'data:{"c":3}\n\n'                                # 空白なし、行末 \n
    )
    check(t._read_event(fake) == '{"a":1}', "普通のイベントを読める")  # type: ignore[arg-type]
    check(t._read_event(fake) == '{\n  "b": 2\n}', "複数の data 行を \\n でつなぐ（コメントは飛ばす）")  # type: ignore[arg-type]
    check(t._read_event(fake) == '{"c":3}', "data: の後に空白が無くても読める")  # type: ignore[arg-type]
    check(t._read_event(fake) is None, "本文が終わったら None")  # type: ignore[arg-type]


def test_own_server() -> None:
    print("== 2. 自作サーバー（JSON で返す）")
    already = is_listening(8000)
    if already:
        print("  （8000 番で既にサーバーが動いているので、自動起動は確かめず、それにつなぐ）")
    before = own_server_pids()
    with MCPClient(HttpClientTransport(OWN_URL)) as c:
        check([t.name for t in c.list_tools()] == ["run_tests"], "tools/list に run_tests だけがある")
        ok = c.call_tool("run_tests", {"code": "x=1", "test_list": ["assert x==1"]})
        check('"success": true' in ok.content[0].text, "正しいコードで success: true", ok)
        ng = c.call_tool("run_tests", {"code": "x=2", "test_list": ["assert x==1"]})
        check('"success": false' in ng.content[0].text, "間違ったコードで success: false", ng)
        c.ping()
        check(True, "ping")
    if not already:
        time.sleep(0.5)
        left = own_server_pids() - before
        check(not left, "自動起動したサーバーが、終了後に残っていない", left)


def test_fastmcp() -> None:
    print("== 3. FastMCP（SSE で返す）")
    server = subprocess.Popen([sys.executable, "tests/sdk_fastmcp_server.py", "--http", str(FAST_PORT)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 15
        while not is_listening(FAST_PORT):
            if time.monotonic() > deadline or server.poll() is not None:
                check(False, "FastMCP が起動する", "起動しませんでした")
                return
            time.sleep(0.2)

        transport = HttpClientTransport(FAST_URL)
        with MCPClient(transport) as c:
            check(c.server_info.name == "sdk-test-server", "initialize の返事（SSE）を読める", c.server_info)
            check(transport.session_id is not None, "セッション ID を受け取った", transport.session_id)
            check(transport.protocol_version == "2025-06-18", "バージョンを教えられた", transport.protocol_version)
            check(sorted(t.name for t in c.list_tools()) == ["add", "fail"], "tools/list（SSE）")
            add = c.call_tool("add", {"a": 2, "b": 3})
            check(add.content[0].text == "5" and not add.is_error, "add(2, 3) = 5", add)
            fail = c.call_tool("fail", {})
            check(fail.is_error, "例外を出す tool は is_error=True", fail)
            c.ping()
            check(True, "ping（SSE）")
    finally:
        server.terminate()
        server.wait(timeout=5)


def test_unknown_url() -> None:
    print("== 4. 起動していない別の URL")
    before = own_server_pids()
    try:
        with MCPClient(HttpClientTransport("http://127.0.0.1:8002/mcp")):
            check(False, "つながらずに MCPConnectionError になる", "つながってしまった")
    except mcp.MCPConnectionError:
        check(True, "つながらずに MCPConnectionError になる")
    started = own_server_pids() - before
    check(not started, "既定以外の URL では、自作サーバーを起動しない", started)


if __name__ == "__main__":
    for test in (test_read_event, test_own_server, test_fastmcp, test_unknown_url):
        try:
            test()
        except Exception as e:  # 1 つの確認が落ちても、残りは続ける
            check(False, f"{test.__name__} の途中で例外", f"{type(e).__name__}: {e}")
    print(f"\n合計: PASS {results['PASS']} / FAIL {results['FAIL']}")
    sys.exit(1 if results["FAIL"] else 0)

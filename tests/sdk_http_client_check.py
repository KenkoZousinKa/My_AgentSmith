"""公式 SDK のクライアントから、自作の MCP サーバーを Streamable HTTP で呼ぶ確認用スクリプト.

サーバーはこのスクリプトが起動し、終わったら止める。
実行: uv run --with "mcp==1.26.0" python tests/sdk_http_client_check.py [ポート]
"""

import asyncio
import logging
import socket
import subprocess
import sys
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
URL = f"http://127.0.0.1:{PORT}/mcp"


def wait_until_listening(port: int, timeout: float = 10) -> None:
    """サーバーがポートで待ち受けを始めるまで待つ."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"サーバーが {port} 番で待ち受けを始めません")


async def main() -> None:
    # timeout は run_tests（最大 30 秒）より長くする
    async with streamablehttp_client(URL, timeout=60) as (read, write, get_session_id):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("initialize :", init.serverInfo, init.capabilities.tools)
            print("session id :", get_session_id())

            await session.send_ping()
            print("ping       : OK")

            tools = await session.list_tools()
            for t in tools.tools:
                print("tool       :", t.name, t.inputSchema.get("required"))

            ok = await session.call_tool("run_tests", {"code": "def f(x): return x*2",
                                                       "test_list": ["assert f(2) == 4"]})
            print("call (ok)  :", ok.isError, ok.content[0].text)

            ng = await session.call_tool("run_tests", {"code": "def f(x): return x*3",
                                                       "test_list": ["assert f(2) == 4"]})
            print("call (ng)  :", ng.isError, ng.content[0].text[:80], "...")


if __name__ == "__main__":
    # httpx が送ったリクエストとステータスを1行ずつ表示する（GET と DELETE への 405 も見える）
    logging.basicConfig(level=logging.WARNING, format="  [httpx] %(message)s")
    logging.getLogger("httpx").setLevel(logging.INFO)

    server = subprocess.Popen([sys.executable, "mcp_tools_mbpp.py", "--transport", "http",
                               "--port", str(PORT)])
    try:
        wait_until_listening(PORT)
        asyncio.run(main())
    finally:
        server.terminate()
        server.wait(timeout=5)

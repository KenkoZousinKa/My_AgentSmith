import http.client
import subprocess
import shlex
import time
import sys
from collections import deque
from urllib.parse import urlsplit, SplitResult
from pydantic import ValidationError

from src.mcp_core.models import jsonrpc as rpc
from src.mcp_core.models import mcpmodel as mcp
from src.mcp_core.server.server import MCPServer
from src.mcp_core.server.http import HttpServerTransport


class HttpClientTransport:
    def __init__(self, url: str, timeout: int = 60) -> None:
        self.process: subprocess.Popen[bytes] | None = None
        self.url: str = url
        parts: SplitResult = urlsplit(url)
        if parts.scheme != "http" or parts.hostname is None:
            raise ValueError(f"http://ホスト:ポート/パス の形で指定してください: {url!r}")

        self.hostname: str = parts.hostname
        self.path: str = parts.path or "/"
        self.port: int | None = parts.port
        self.session_id: str | None = None
        self.protocol_version: str | None = None

        self.timeout: int = timeout
        self.mcp_version: str
        self.conn: http.client.HTTPConnection
        self.inbox: deque[rpc.JSONRPCMessage] = deque()

    def open(self) -> None:
        """MCPサーバーとの接続をHTTPで確立する."""
        try:
            self.conn = http.client.HTTPConnection(host=self.hostname, port=self.port,
                                                   timeout=3)
            self.conn.connect()
        except OSError as e:
            command = "python mcp_tools_mbpp.py --transport http"
            self.process = subprocess.Popen(args=shlex.split(command))
            deadline = time.monotonic() + 10
            while self.url == "http://127.0.0.1:8000/mcp":
                try:
                    time.sleep(0.1)
                    self.conn.connect()
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise mcp.MCPConnectionError(f"サーバーが 10 秒以内に待ち受けを始めませんでした コマンド: {command} URL: {self.url}") from e
                    time.sleep(0.1)
                    print('サーバーの起動に再度試みています...', file=sys.stderr)
            else:
                raise mcp.MCPConnectionError(f"サーバーの起動に失敗しました。 Command: {command} URL: {self.url}")

        self.conn.timeout = self.timeout
        self.conn.sock.settimeout(self.timeout)

    def send(self, message: rpc.JSONRPCMessage) -> None:
        """渡されたJSON-RPCオブジェクトサーバーの HTTP に書き込む."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            }
        if self.session_id is not None:
            headers["Mcp-Session-Id"] = self.session_id
        if self.protocol_version is not None:
            headers["MCP-Protocol-Version"] = self.protocol_version
        self.conn.request(method="POST", url=self.path,
                          headers=headers, body=message.model_dump_json().encode("utf-8"))
        resp = self._resp()
        if resp is None:
            return
        self.inbox.append(resp)

    def receive(self) -> rpc.JSONRPCMessage:
        """サーバーの HTTP から1通読み、JSON-RPCの型に変換して返す."""
        return self.inbox.popleft()

    def set_protocol_version(self, version: str) -> None:
        """MCPプロトコルのバージョンを設定する."""
        self.protocol_version = version

    def close(self) -> None:
        """プロセスを安全に終了させて、接続を切る."""
        if self.process is not None:
            # 1. 正常終了信号を送る SIGTERM=-15
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:

                # 2. 強制終了信号を送る terminater「Hasta la vista, baby.」 SIGKILL=-9
                self.process.kill()
                self.process.wait()
        return

    def _resp(self) -> rpc.JSONRPCMessage | None:
        """responceを解析する."""
        try:
            resp = self.conn.getresponse()
        except (http.client.RemoteDisconnected, http.client.HTTPException, OSError) as e:
            raise mcp.MCPConnectionError("サーバとの接続が切断されました") from e
        headers = resp.headers
        body = resp.read().decode("utf-8")
        if self.session_id is None:
            self.session_id = headers.get("Mcp-Session-Id")

        if resp.status == http.HTTPStatus.ACCEPTED:
            resp.close()
            return None

        if resp.status == http.HTTPStatus.NOT_FOUND:
            resp.close()
            raise mcp.MCPConnectionError(f"サーバとの接続が切断されました。 Code: {resp.status}")

        if resp.status == http.HTTPStatus.OK:
            try:
                return rpc.jsonrpc_message_adapter.validate_json(body)
            except ValidationError as e:
                raise mcp.MCPProtocolError(f"サーバから不正なメッセージを受信しました。{body!r}") from e

        raise mcp.MCPConnectionError(f"予期しないメッセージです。 Code: {resp.status} Body: {body}")

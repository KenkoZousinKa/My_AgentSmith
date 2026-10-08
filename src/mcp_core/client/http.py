import http.client
from urllib.parse import urlsplit

from src.mcp_core.models import jsonrpc as rpc
from src.mcp_core.models import mcpmodel as mcp


class StdioClientTransport:
    def __init__(self, url: str, timeout: int = 60) -> None:
        self.parts = urlsplit(url)
        self.parts.port
        if self.parts.scheme != "http" or self.parts.hostname is None:
            raise ValueError(f"http://ホスト:ポート/パス の形で指定してください: {url!r}")

        self.hostname: str = self.parts.hostname
        self.path: str = self.parts.path or "/"
        self.session_id: str
        self.protocol_version: str

        self.timeout: int = timeout
        self.mcp_version: str
        self.conn: http.client.HTTPConnection

    def open(self) -> None:
        """MCPサーバーとの接続をHTTPで確立する."""
        self.conn = http.client.HTTPConnection(host=self.hostname, port=self.parts.port,
                                               timeout=self.timeout)

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
                          headers=headers, body=message.model_dump_json())

        resp = self.conn.getresponse()
        resp.read()

    def receive(self) -> rpc.JSONRPCMessage:
        """サーバーの HTTP から1通読み、JSON-RPCの型に変換して返す."""


    def set_protocol_version(self, version: str) -> None: ...
    def close(self) -> None: ...

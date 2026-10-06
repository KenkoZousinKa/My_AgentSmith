"""MCPClient:"""


import uuid
from typing import Any
from pydantic import ValidationError

from src.mcp_core.models import jsonrpc as rpc
from src.mcp_core.models import mcpmodel as mcp
from src.mcp_core.models.client_transport import ClientTransport


class MCPClient:
    def __init__(self, transport: ClientTransport):
        self.transport = transport
        self.server_info: mcp.Implementation
        self.server_capabilities: dict[str, Any]

    def __enter__(self) -> "MCPClient":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        """ガベージコレクション時のフェイルセーフ"""
        self.close()

    def connect(self) -> None:
        """MCPサーバーとの接続を確立する."""

        try:
            # transportクラスでサーバーの立ち上げと接続
            self.transport.open()

            # requestを送る
            params = mcp.InitializeRequestParams(protocol_version=mcp.MCP_VERSION,
                                                 capabilities={},
                                                 client_info=mcp.Implementation(name="SandBox", version="1.0"))
            result = self._request(mcp.Method.INITIALIZE, params)  # 送受信

            # responceを検証する
            try:
                init = mcp.InitializeResult.model_validate(result)
            except ValidationError as e:
                raise mcp.MCPProtocolError(f"initializeの応答が不正です: {result}") from e

            # versionを検証する
            if init.protocol_version != mcp.MCP_VERSION:
                raise mcp.MCPProtocolError(f"未対応のプロトコルバージョン: {init.protocol_version}")
            self.transport.set_protocol_version(mcp.MCP_VERSION)

            # 保存してサーバーへ通知
            self.server_info = init.server_info
            self.server_capabilities = init.capabilities
            self._notify(method=mcp.Method.INITIALIZED)

        except Exception:
            self.close()
            raise

    def list_tools(self) -> list[mcp.Tool]:
        """サーバーにツールリストを依頼し、結果を受け取る"""
        if "tools" not in self.server_capabilities:
            return []

        result = self._request(mcp.Method.TOOLS_LIST)

        try:
            t_list = mcp.ListToolsResult.model_validate(result)
        except ValidationError as e:
            raise mcp.MCPProtocolError(f"tools/listの応答が不正です: {result}") from e

        return t_list.tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> mcp.CallToolResult:
        """サーバーにツール実行を依頼し、結果を受け取る"""
        params = mcp.CallToolRequestParams(name=name, arguments=arguments)
        result = self._request(mcp.Method.TOOLS_CALL, params)

        try:
            result_model = mcp.CallToolResult.model_validate(result)
        except ValidationError as e:
            raise mcp.MCPProtocolError(f"tools/callの応答が不正です: {result}") from e

        return result_model

    def ping(self) -> None:
        """サーバーが応答するか確かめる。応答が無ければ例外."""
        self._request(mcp.Method.PING)        # 返ってくる result は {} なので、中身は使わない

    def close(self) -> None:
        """サーバーとの接続を閉じる."""
        self.transport.close()

    def _request(self, method: str, params: mcp.MCPModel | None = None) -> dict[str, Any]:
        """リクエストを送り、同じ id の応答の result を返す。エラー応答なら例外."""
        request = rpc.JSONRPCRequest(jsonrpc=rpc.JSONRPC_VERSION, id=uuid.uuid4().hex,
                                     method=method)
        if params is not None:
            request.params = params.model_dump(by_alias=True, exclude_none=True)
        # 送信
        self._send(request)
        while True:

            # 受信
            msg = self._receive()

            # responceとerrorで振り分け
            if isinstance(msg, rpc.JSONRPCResponse) and msg.id == request.id:
                return msg.result
            if isinstance(msg, rpc.JSONRPCError) and msg.id == request.id:
                raise mcp.MCPError(msg.error.code, msg.error.message, msg.error.data)
            if isinstance(msg, rpc.JSONRPCRequest):
                self._answer_server_request(msg)
            # それ以外（通知、他の id の応答）は読み飛ばす

    def _notify(self, method: str, params: mcp.MCPModel | None = None) -> None:
        """通知を送る。返事は待たない."""
        notification = rpc.JSONRPCNotification(jsonrpc=rpc.JSONRPC_VERSION, method=method,
                                               params=params.model_dump(by_alias=True,
                                                                        exclude_none=True) if params is not None else None)
        self._send(notification)

    def _send(self, message: rpc.JSONRPCMessage) -> None:
        """サーバーにメッセージを送る."""
        self.transport.send(message)

    def _receive(self) -> rpc.JSONRPCMessage:
        """サーバーからのレスポンスをJSON-RPCの型に変換して返す."""
        return self.transport.receive()

    def _answer_server_request(self, msg: rpc.JSONRPCRequest) -> None:
        """サーバーからのリクエストに応答する."""
        if msg.method == mcp.Method.PING:
            self._send(rpc.JSONRPCResponse(jsonrpc=rpc.JSONRPC_VERSION, id=msg.id, result={}))
        else:
            self._send(rpc.JSONRPCError(jsonrpc=rpc.JSONRPC_VERSION, id=msg.id,
                                        error=rpc.ErrorData(code=rpc.ErrorCode.METHOD_NOT_FOUND,
                                                            message=f"Method not found: {msg.method}")))


if __name__ == "__main__":
    print("[Client] MCPクライアントを起動します...")
    try:
        from src.mcp_core.client.transport import StdioClientTransport
        with MCPClient(StdioClientTransport("python mcp_tools_mbpp.py")) as c:
            c.call_tool('run_tests', {'code': 'x=1', 'test_list': ['assert x==1']})
            pass
    except Exception as e:
        print(e)

"""
class StdioMCPClient:
    # --- 生成と後片付け ---
    def __init__(self, command: str) -> None: ...
    def __enter__(self) -> "StdioMCPClient": ...
    def __exit__(self, *exc: object) -> None: ...
    def __del__(self) -> None: ...

    # --- 公開 API（使う順） ---
    def connect(self) -> None: ...
    def list_tools(self) -> list[Tool]: ...
    def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult: ...
    def close(self) -> None: ...

    # --- 上の層：意味（リクエスト / 通知） ---
    def _request(self, ...) -> ...: ...
    def _notify(self, ...) -> None: ...

    # --- 下の層：運搬（送信 / 受信） ---
    def _send(self, message) -> None: ...
    def _receive(self) -> JSONRPCMessage: ...

"""


import subprocess
import uuid
import time
import shlex
from typing import Any
from pydantic import ValidationError

from src.models.jsonrpc import (
    JSONRPC_VERSION,
    JSONRPCRequest,
    JSONRPCResponse,
    JSONRPCNotification,
    JSONRPCError,
    JSONRPCMessage,
    jsonrpc_message_adapter
    )
from src.models.mcpmodel import (
    MCPModel,
    InitializeRequestParams,
    InitializeResult,
    Implementation,
    METHOD_INITIALIZE,
    METHOD_INITIALIZED,
    MCP_VERSION
)
from src.mcp_server.error import (
    MCPConnectionError,
    MCPProtocolError,
    MCPError
)


class StdioMCPClient:
    def __init__(self, command: str):
        self.command = command
        self.server_info: Implementation
        self.server_capabilities: dict[str, Any]

    def __enter__(self) -> "StdioMCPClient":
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
            # サーバープロセスを起動し、入出力をパイプで繋ぐ
            # text=True により、バイト列ではなく文字列として扱える
            # 例: command = ["python", "mcp_tools_mbpp.py"]
            self.process = subprocess.Popen(
                args=shlex.split(self.command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True       # 送信時に文字列が壊れないように
            )
            # 起動直後の即死チェック
            time.sleep(0.1)
            if self.process.poll() is not None:
                raise RuntimeError(f"サーバーの起動に失敗しました。コマンド: {self.command}")

            # requestを送る
            params = InitializeRequestParams(protocol_version=MCP_VERSION,
                                             capabilities={},
                                             client_info=Implementation(name="SandBox", version="1.0"))
            result = self._request(METHOD_INITIALIZE, params)

            # responceを検証する
            try:
                init = InitializeResult.model_validate(result)
            except ValidationError as e:
                raise MCPProtocolError(f"initializeの応答が不正です: {result}") from e

            # versionを検証する
            if init.protocol_version != MCP_VERSION:
                raise MCPProtocolError(f"未対応のプロトコルバージョン: {init.protocol_version}")

            # 保存してサーバーへ通知
            self.server_info = init.server_info
            self.server_capabilities = init.capabilities
            self._notify(method=METHOD_INITIALIZED)

        except Exception:
            self.close()
            raise

    def list_tools(self) -> None:  # must result
        pass

    def call_tool(self, name: str, arguments: dict[str, Any]) -> None:  # Resultする必要あり
        pass

    def close(self) -> None:
        """プロセスを安全に終了させる"""
        # process属性が存在しているか　and sub_processが終了していないか
        if not hasattr(self, 'process') and self.process.poll() is not None:
            return
        assert self.process.stdin is not None
        # 1. EOFを送る
        self.process.stdin.close()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            # 2. 正常終了信号を送る
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                # 3. 強制終了信号を送る
                # terminater「Hasta la vista, baby.」
                self.process.kill()
                self.process.wait

    def _request(self, method: str, params: MCPModel | None = None) -> dict[str, Any]:
        """リクエストを送り、同じ id の応答の result を返す。エラー応答なら例外."""
        request = JSONRPCRequest(jsonrpc=JSONRPC_VERSION, id=uuid.uuid4().hex,
                                 method=method, params=params.model_dump(by_alias=True,
                                                                         exclude_none=True) if params is not None else None)
        self._send(request)
        while True:
            msg = self._receive()

            if isinstance(msg, JSONRPCResponse) and msg.id == request.id:
                return msg.result
            if isinstance(msg, JSONRPCError) and msg.id == request.id:
                raise MCPError(msg.error.code, msg.error.message, msg.error.data)
            # それ以外（通知、サーバーからのリクエスト、他の id の応答）は読み飛ばす

    def _notify(self, method: str, params: MCPModel | None = None) -> None:
        """通知を送る。返事は待たない."""
        notification = JSONRPCNotification(jsonrpc=JSONRPC_VERSION, method=method,
                                           params=params.model_dump(by_alias=True,
                                                                    exclude_none=True) if params is not None else None)
        self._send(notification)

    def _send(self, message: JSONRPCRequest | JSONRPCNotification) -> None:
        """封筒を1行の JSON にしてサーバーの stdin に書き込む."""
        assert self.process.stdin is not None
        self.process.stdin.write(message.model_dump_json(by_alias=True, exclude_none=True) + "\n")
        self.process.stdin.flush()

    def _receive(self) -> JSONRPCMessage:
        """サーバーの stdout から1通読み、JSON-RPCの型に変換して返す."""
        assert self.process.stdout is not None
        # MCPサーバーからの標準出力を待つ
        line = self.process.stdout.readline()
        if not line:
            raise MCPConnectionError("サーバーとの接続が切れました。")
        try:
            # JSON-RPCの型に変換する
            return jsonrpc_message_adapter.validate_json(line)
        except ValidationError as e:
            raise MCPProtocolError(f"サーバから不正なメッセージを受信しました。{line!r}") from e


if __name__ == "__main__":
    print("[Client] MCPクライアントを起動します...")
    with StdioMCPClient("python mcp_tools_mbpp.py") as c:
        pass

    # def call_tool(self, tool_name: str, args: dict[str, str]) -> dict[str, str]:
    #     """サーバーにツール実行を依頼し、結果を受け取る"""
    #     # 1. リクエストJSONを作成
    #     request_data = {
    #         "method": "call_tool",
    #         "tool": tool_name,
    #         "args": args
    #     }

    #     # 2. サーバーの標準入力に書き込み、改行で区切る
    #     self.process.stdin.write(json.dumps(request_data) + "\n")

    #     # 【超重要】バッファに溜めず、即座に送信を確定させる
    #     self.process.stdin.flush()

    #     # 3. サーバーからの標準出力を1行読み取る（結果が来るまで待機）
    #     response_line = self.process.stdout.readline()

    #     if not response_line:
    #         raise RuntimeError("MCPサーバーとの通信が切断されました")

    #     # 4. 受け取ったJSONを辞書に戻して返す
    #     return json.loads(response_line)

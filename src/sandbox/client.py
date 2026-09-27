import subprocess
import json
import uuid
import time
import shlex
from typing import Any

from src.models.jsonrpc import JSONRPCRequest, JSONRPCNotification, JSONRPC_VERSION, JSONRPCMessage
from src.models.mcpmodel import (
    MCPModel,
    InitializeRequestParams,
    Implementation,
    METHOD_INITIALIZE,
    MCP_VERSION
)


class StdioMCPClient:
    def __init__(self, command: str):
        self.command = command

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

            assert self.process.stdin is not None
            assert self.process.stdout is not None
            params = InitializeRequestParams(protocol_version=MCP_VERSION,
                                             capabilities={},
                                             client_info=Implementation(name="SandBox",
                                                                        version="1.0")).model_dump(by_alias=True,
                                                                                                   exclude_none=True)

            request = JSONRPCRequest(jsonrpc=JSONRPC_VERSION,
                                     id=uuid.uuid4().hex,
                                     method=METHOD_INITIALIZE,
                                     params=params)
            self.process.stdin.write(request.model_dump_json(by_alias=True, exclude_none=True))
            self.process.stdin.flush()

            self.process.stdout

        except RuntimeError as e:
            print(e)

    def close(self) -> None:
        """プロセスを安全に終了させる"""
        if hasattr(self, 'process') and self.process.poll() is None:
            self.process.terminate()
            self.process.wait()

    def list_tools(self) -> None:  # must result
        pass

    def call_tool(self, name: str, arguments: dict[str, Any]) -> None:  # Resultする必要あり
        pass

    def _send(self, message: JSONRPCRequest | JSONRPCNotification) -> None:
        """封筒を1行の JSON にしてサーバーの stdin に書き込む."""
        assert self.process.stdin is not None
        self.process.stdin.write(message.model_dump_json(by_alias=True, exclude_none=True))
        self.process.stdin.flush()

    def _receive(self) -> JSONRPCMessage:
        """サーバーの stdout から1通読み、封筒の型に変換して返す."""
        pass

    def _notify(self, method: str, params: MCPModel | None = None) -> None:
        """通知を送る。返事は待たない."""
        pass

    def _request(self, method: str, params: MCPModel | None = None) -> dict[str, Any]:
        """リクエストを送り、同じ id の応答の result を返す。エラー応答なら例外."""
        request = JSONRPCRequest(jsonrpc=JSONRPC_VERSION,
                                 id=uuid.uuid4().hex,
                                 method=method,
                                 params=params)
        return

    def _send_request(self, request: str) -> None:
        """MCPサーバーにリクエストを要求する"""

        assert self.process.stdin is not None

        # リクエストをMCPサーバーの標準入力に送る flushで即送信
        self.process.stdin.write(json.dumps(request) + '\n')
        self.process.stdin.flush()

    def _receive_responce(self) -> JSONRPCMessage:
        # 2.MCPサーバーからの標準出力を待つ
        responce_line = self.process.stdout.readline()
        if not responce_line:
            raise RuntimeError("サーバーから応答がありません。")

        data: dict[str, Any] = json.loads(responce_line)
        return data

    def __del__(self) -> None:
        """ガベージコレクション時のフェイルセーフ"""
        self.close()

    def __enter__(self) -> "StdioMCPClient":
        pass

    def __exit__(self, *exc: object) -> None:
        pass


if __name__ == "__main__":
    print("[Client] MCPクライアントを起動します...")
    client = StdioMCPClient("python mcp_tools_mbpp.py")

    try:
        client.connect()

    finally:
        # プログラムが正常終了しようと、エラーでクラッシュしようと
        # 必ず最後にここを通って、子プロセスにトドメを刺す
        client.process.terminate()
        client.process.wait()   # 完全に死ぬまで待つ
        print("[Client] サーバープロセスを終了しました。")

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

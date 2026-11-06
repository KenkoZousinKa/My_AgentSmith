"""MCPClient."""

import uuid
import sys
from typing import Any
from pydantic import ValidationError

from src.mcp.models import jsonrpc as rpc
from src.mcp.models import mcpmodel as mcp
from src.mcp.models.client_transport import ClientTransport

MBPP_SERVER_COMMAND = "python mcp_tools_mbpp.py"
SWE_SERVER_COMMAND = "python mcp_tools_swebench.py"
DEFAULT_URL = "http://127.0.0.1:8000/mcp"


class MCPClient:
    """MCPクライアントのメインクラス.

    MCPサーバーと接続し、LLMに提供する機能をMCPにリクエストする.

    Attributes:
        transport(ClientTransport): サーバーとの通信を行うトランスポートクラスのインスタンス.
        server_info(mcp.Implementation): サーバーの実装情報.
        server_capabilities(dict): サーバーの機能情報.
        init_meta(dict): 初期化時にサーバーに渡すメタ情報
    """

    def __init__(self, transport: ClientTransport, init_meta: dict[str, Any] | None = None):
        """MCPクライアントを初期化する."""
        self.transport = transport
        self.server_info: mcp.Implementation
        self.server_capabilities: dict[str, Any]
        self.init_meta = init_meta

    def __enter__(self) -> "MCPClient":
        """コンテキストマネージャーの開始処理. サーバーとの接続を確立する."""
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        """コンテキストマネージャーの終了処理. サーバーとの接続を閉じる."""
        self.close()

    def __del__(self) -> None:
        """ガベージコレクション時のフェイルセーフとして、サーバーとの接続を閉じる."""
        self.close()

    # ----- <サーバーとの接続管理> -----------------------------------------------------------------

    def connect(self) -> None:
        """サーバーと接続後、initializeリクエストを送信してサーバーの情報を取得する.

        初期化プロセスに則ってサーバーと接続し、initializeリクエストを送信する.
        Iitializeメソッドを送信する.

        Raises:
            mcp.MCPConnectionError: サーバーとの接続に失敗した場合
            mcp.MCPProtocolError: サーバーの応答が不正な場合
        """
        try:
            # transportクラスでサーバーの立ち上げと接続
            self.transport.open()

            # JSON-RPCのinitializeリクエストパラメータを作成
            params = mcp.InitializeRequestParams(protocol_version=mcp.MCP_VERSION,
                                                 capabilities={},
                                                 client_info=mcp.Implementation(name="SandBox", version="1.0"),
                                                 meta=self.init_meta)
            # サーバーへinitializeリクエストを送って、返答を受け取る
            result = self._request(mcp.Method.INITIALIZE, params)
            try:
                # 返答を検証する
                init = mcp.InitializeResult.model_validate(result)
            except ValidationError as e:
                raise mcp.MCPProtocolError(f"initializeの応答が不正です: {result}") from e

            # サーバーのMCPバージョンが2.0以外のバージョンは未対応として例外を投げる
            if init.protocol_version != mcp.MCP_VERSION:
                raise mcp.MCPProtocolError(f"未対応のプロトコルバージョン: {init.protocol_version}")
            # transportオブジェクトにバージョンを設定する
            self.transport.set_protocol_version(mcp.MCP_VERSION)

            # サーバー情報と機能情報を保存する
            self.server_info = init.server_info
            self.server_capabilities = init.capabilities

            # INITIALIZED通知を送る
            self._notify(method=mcp.Method.INITIALIZED)
            print(f"[Client] MCPクライアントが正常に起動しました。 ({self.transport.__class__.__name__})", file=sys.stderr)

        except Exception:
            # transport.open()で接続に失敗した場合や、initializeリクエストの応答が不正だった場合など
            self.close()
            print(f"[Client] MCPクライアントの起動に失敗しました。({self.transport.__class__.__name__})", file=sys.stderr)
            raise

    def close(self) -> None:
        """サーバーとの接続を閉じる。transportクラスのcloseメソッドを呼び出す."""
        self.transport.close()

    def _send(self, message: rpc.JSONRPCMessage) -> None:
        """transportを使ってサーバーにJSON-RPCメッセージを送信する.

        Args:
            message (rpc.JSONRPCMessage): 送信するJSON-RPCメッセージ
        """
        self.transport.send(message)

    def _receive(self) -> rpc.JSONRPCMessage:
        """transportを使ってサーバーからJSON-RPCメッセージを受信する.

        Returns:
            rpc.JSONRPCMessage: サーバーから受信したJSON-RPCメッセージ
        """
        return self.transport.receive()

    def _request(self, method: str, params: mcp.MCPModel | None = None) -> dict[str, Any]:
        """引数のparamsを含んだリクエスト本文を作成してサーバーに送信し、その返答を受け取る.

        サーバーからの返答が不正な場合は例外を投げる.

        Args:
            method (str): JSON-RPCのメソッド名
            params (mcp.MCPModel | None): JSON-RPCのパラメータ

        Returns:
            dict[str, Any]: サーバーからの返答のresult部分

        Raises:
            mcp.MCPConnectionError: サーバーとの接続が切れた場合
            mcp.MCPProtocolError: サーバーから不正なメッセージを受信した場合
            mcp.MCPError: サーバーからエラー応答が返ってきた場合
        """
        # JSON-RPCリクエストを作成。idはuuidで作成される
        request = rpc.JSONRPCRequest(jsonrpc=rpc.JSONRPC_VERSION, id=uuid.uuid4().hex,
                                     method=method)
        # paramsをjsonに変換してリクエストに入れる
        if params is not None:
            request.params = params.model_dump(by_alias=True, exclude_none=True)

        # リクエストを送信
        self._send(request)

        # サーバーからの応答を待つ
        while True:
            # メッセージを受信
            msg = self._receive()

            # responceかつ自分が送ったリクエストのIDと一致する場合
            if isinstance(msg, rpc.JSONRPCResponse) and msg.id == request.id:
                return msg.result
            # errorかつ自分が送ったリクエストのIDと一致する場合
            if isinstance(msg, rpc.JSONRPCError) and msg.id == request.id:
                raise mcp.MCPError(msg.error.code, msg.error.message, msg.error.data)
            # サーバーからのリクエストに応答(debug用)
            if isinstance(msg, rpc.JSONRPCRequest):
                self._answer_server_request(msg)
            # それ以外（通知、他の id の応答）は読み飛ばす

    def _notify(self, method: str, params: mcp.MCPModel | None = None) -> None:
        """transportを使ってサーバーにJSON-RPC通知を送信する.

        Args:
            method (str): 通知のメソッド名
            params (mcp.MCPModel | None): 通知のパラメータ
        """
        # JSON-RPC通知を作成
        notification = rpc.JSONRPCNotification(jsonrpc=rpc.JSONRPC_VERSION, method=method,
                                               params=params.model_dump(by_alias=True,
                                                                        exclude_none=True) if params is not None else None)
        self._send(notification)

    # ----- <アプリケーションが使用するAPI> -----------------------------------------------------------------

    # ===== tools/ Methods =====
    def list_tools(self) -> list[mcp.Tool]:
        """サーバーにtools/listリクエストを送信し、ツールの一覧を取得する.

        Returns:
            list[mcp.Tool]: サーバーが提供するツールの一覧
        Raises:
            mcp.MCPProtocolError: サーバーの応答が不正な場合
        """
        # サーバーがtools機能を持っていない場合は空リストを返す
        if "tools" not in self.server_capabilities:
            return []

        # tools/listをリクエストメソッドとしてself._requestに送信してもらい、resultを受け取る
        result = self._request(mcp.Method.TOOLS_LIST)

        try:
            # resultを検証する
            t_list = mcp.ListToolsResult.model_validate(result)
        except ValidationError as e:
            raise mcp.MCPProtocolError(f"tools/listの応答が不正です: {result}") from e

        return t_list.tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> mcp.CallToolResult:
        """サーバーにtools/callリクエストを送信し、指定されたツールを呼び出す.

        Args:
            name (str): 呼び出すツールの名前(関数名)
            arguments (dict[str, Any]): ツールに渡す引数の辞書

        Returns:
            mcp.CallToolResult: ツールの実行結果を格納したオブジェクト

        Raises:
            mcp.MCPProtocolError: サーバーの応答が不正な場合
        """
        # JSON-RPCのリクエストパラメータを作成
        params = mcp.CallToolRequestParams(name=name, arguments=arguments)
        result = self._request(mcp.Method.TOOLS_CALL, params)

        try:
            result_model = mcp.CallToolResult.model_validate(result)
        except ValidationError as e:
            raise mcp.MCPProtocolError(f"tools/callの応答が不正です: {result}") from e

        return result_model

    # ===== resources/ Methods =====
    def list_resources(self) -> list[mcp.Resource]:
        """サーバーにresources/listリクエストを送信し、資料の一覧を取得する.

        Returns:
            list[mcp.Resource]: サーバーが提供する資料の一覧
        Raises:
            mcp.MCPProtocolError: サーバーの応答が不正な場合
        """
        # 資料の機能が無いサーバーには頼まない
        if "resources" not in self.server_capabilities:
            return []
        result = self._request(mcp.Method.RESOURCES_LIST)
        try:
            return mcp.ListResourcesResult.model_validate(result).resources
        except ValidationError as e:
            raise mcp.MCPProtocolError(f"resources/listの応答が不正です: {result}") from e

    def read_resource(self, uri: str) -> mcp.ReadResourceResult:
        """サーバーにresources/readリクエストを送信し、指定された資料の中身を取得する.

        Args:
            uri (str): 読みたい資料のURI

        Returns:
            mcp.ReadResourceResult: 資料の中身を格納したオブジェクト

        Raises:
            mcp.MCPProtocolError: サーバーの応答が不正な場合
        """
        params = mcp.ReadResourceRequestParams(uri=uri)
        result = self._request(mcp.Method.RESOURCES_READ, params)

        try:
            return mcp.ReadResourceResult.model_validate(result)
        except ValidationError as e:
            raise mcp.MCPProtocolError(f"resources/readの応答が不正です: {result}") from e

    # ===== prompts/ Methods =====
    def list_prompts(self) -> list[mcp.Prompt]:
        """サーバーにprompts/listリクエストを送信し、指示の雛形の一覧を取得する.

        Returns:
            list[mcp.Prompt]: サーバーが提供する指示の雛形の一覧
        Raises:
            mcp.MCPProtocolError: サーバーの応答が不正な場合
        """
        if "prompts" not in self.server_capabilities:
            return []
        result = self._request(mcp.Method.PROMPTS_LIST)
        try:
            return mcp.ListPromptsResult.model_validate(result).prompts
        except ValidationError as e:
            raise mcp.MCPProtocolError(f"prompts/listの応答が不正です: {result}") from e

    def get_prompt(self, name: str, arguments: dict[str, str] | None = None) -> mcp.GetPromptResult:
        """サーバーにprompts/getリクエストを送信し、指定された雛形に引数を埋めたメッセージを取得する.

        例:
        get_prompt("solve_task", {"task_definition": "Example task", "function_definition": "def example(): pass", "tests": ""})

        Args:
            name (str): 雛形の名前
            arguments (dict[str, str] | None): 雛形に埋める引数

        Returns:
            mcp.GetPromptResult: 埋めたメッセージを格納したオブジェクト

        Raises:
            mcp.MCPProtocolError: サーバーの応答が不正な場合
        """
        params = mcp.GetPromptRequestParams(name=name, arguments=arguments)
        result = self._request(mcp.Method.PROMPTS_GET, params)
        try:
            return mcp.GetPromptResult.model_validate(result)
        except ValidationError as e:
            raise mcp.MCPProtocolError(f"prompts/getの応答が不正です: {result}") from e

    # ----- <デバッグ用のAPI> -----------------------------------------------------------------

    def ping(self) -> None:
        """サーバーが応答するか確かめる。debug用."""
        self._request(mcp.Method.PING)

    def _answer_server_request(self, msg: rpc.JSONRPCRequest) -> None:
        """サーバーからのリクエストに応答する(debug用).

        Args:
            msg (rpc.JSONRPCRequest): サーバーから受信したJSON-RPCリクエスト
        """
        if msg.method == mcp.Method.PING:
            self._send(rpc.JSONRPCResponse(jsonrpc=rpc.JSONRPC_VERSION, id=msg.id, result={}))
        else:
            self._send(rpc.JSONRPCError(jsonrpc=rpc.JSONRPC_VERSION, id=msg.id,
                                        error=rpc.ErrorData(code=rpc.ErrorCode.METHOD_NOT_FOUND,
                                                            message=f"Method not found: {msg.method}")))


if __name__ == "__main__":
    pass

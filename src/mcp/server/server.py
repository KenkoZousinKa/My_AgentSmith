"""MCP Server."""

import json
import inspect
from collections.abc import Callable
from typing import Any, TypeVar
from pydantic import ValidationError, create_model, BaseModel

from src.mcp.models import jsonrpc as rpc
from src.mcp.models import mcpmodel as mcp
from src.mcp.models.server_transport import ServerTransport
from src.mcp.server.stdio import StdioServerTransport
from src.mcp.server.tool_model import (
    RegisteredTool,
    RegisteredPrompt,
    RegisteredResource,
)

F = TypeVar("F", bound=Callable[..., Any])
# デコレータに渡された関数の型を制約するためのTypeVar


class MCPServer:
    """MCPサーバーのメインクラス.

    on_initializeはサーバーが立ち上がり初期化の最初の一回のみ登録した関数が実行される。
    mcp_tools_swebench.pyでのみDockerコンテナを立ち上げる関数が登録されている。

    Attributes:
        handlers (dict[str, Callable[[dict[str, Any] | None], mcp.MCPModel]]): メソッドとハンドラの対応辞書
        server_info (mcp.Implementation): サーバーの情報
        tools (dict[str, RegisteredTool]): 登録されたツール
        resources (dict[str, RegisteredResource]): 登録されたリソース
        prompts (dict[str, RegisteredPrompt]): 登録されたプロンプト
        _on_initialize (Callable[[dict[str, Any] | None], None] | None): 最初のinitializeリクエスト時に呼ばれるコールバック
    """

    def __init__(self, name: str, version: str) -> None:
        """MCPServerの初期化.

        Args:
            name (str): サーバーの名前
            version (str): サーバーのバージョン
        """
        # 各methodに対応した処理を行う関数を辞書型で登録
        self.handlers: dict[str, Callable[[dict[str, Any] | None], mcp.MCPModel]] = {
            mcp.Method.INITIALIZE: self._handle_initialize,
            mcp.Method.PING: self._handle_ping,
            mcp.Method.TOOLS_LIST: self._handle_tools_list,
            mcp.Method.TOOLS_CALL: self._handle_call_tool,
            mcp.Method.RESOURCES_LIST: self._handle_resources_list,
            mcp.Method.RESOURCES_READ: self._handle_resources_read,
            mcp.Method.PROMPTS_LIST: self._handle_prompts_list,
            mcp.Method.PROMPTS_GET: self._handle_prompts_get,
        }
        self.server_info = mcp.Implementation(name=name, version=version)

        self.tools: dict[str, RegisteredTool] = {}
        self.resources: dict[str, RegisteredResource] = {}
        self.prompts: dict[str, RegisteredPrompt] = {}

        self._on_initialize: Callable[[dict[str, Any] | None], None] | None = None

    # ----- <クライアントとの接続管理> -----------------------------------------------------------------

    def run(self, transport: ServerTransport | None = None) -> None:
        """transportでサーバーの受付を開始する.

        transportが指定されていなければ標準入出力を使用する

        Args:
            transport (ServerTransport | None): 使用するサーバートランスポート。Noneの場合は標準入出力を使用する。
        """
        if transport is None:
            transport = StdioServerTransport()
        transport.serve(self.process_message)

    # ----- <JSON-RPC作成処理> -----------------------------------------------------------------

    def process_message(self, line: str) -> rpc.JSONRPCResponse | rpc.JSONRPCError | None:
        """受け取ったJSON-RPC文字列を解析して、クライアントに返すべき応答を返す.

        transportはこのメソッドを通してしてサーバー機能を利用する。

        Args:
            line (str): 受け取ったJSON-RPC文字列
        Returns:
            rpc.JSONRPCResponse | rpc.JSONRPCError | None: クライアントに返すべきJSON-RPCオブジェクト
        """
        # 1. jsonとして正しいか
        try:
            data = json.loads(line)
        except json.JSONDecodeError as e:
            return self._error(None, rpc.ErrorCode.PARSE_ERROR, f"Parse error: {e}")

        # 2. JSON-RPCとして正しいか
        try:
            msg = rpc.jsonrpc_message_adapter.validate_python(data)
        except ValidationError as e:
            return self._error(None, rpc.ErrorCode.INVALID_REQUEST, "Invalid Request", str(e))

        # 3. 問題なければdispatchに渡してレスポンスを返す
        if isinstance(msg, rpc.JSONRPCRequest):
            return self._dispatch(msg)

        # 4. 通知などは対応しない
        return None

    def _dispatch(self, msg: rpc.JSONRPCRequest) -> rpc.JSONRPCResponse | rpc.JSONRPCError:
        """リクエストがあったメソッド別に振り分けて担当関数を実行し、結果を含んだJSON-RPCレスポンスを返す.

        Args:
            msg (rpc.JSONRPCRequest): 受け取ったJSON-RPCリクエスト

        Returns:
            rpc.JSONRPCResponse | rpc.JSONRPCError: クライアントに返すべきJSON-RPCオブジェクト
        """
        # 1. 受け取ったリクエストのmethodをkeyに関数を呼び出す
        handler = self.handlers.get(msg.method)
        if handler is None:
            return self._error(msg.id, rpc.ErrorCode.METHOD_NOT_FOUND, f"Method not found: {msg.method}")

        # 2. 担当メソッドを実行してリザルトオブジェクトを取得する
        try:
            result = handler(msg.params)

        # paramsが不正
        except ValidationError as e:
            return self._error(msg.id, rpc.ErrorCode.INVALID_PARAMS, "Invalid params", str(e))
        # MCP固有のエラー(例. tollが存在しない場合など)
        except mcp.MCPError as e:
            return self._error(msg.id, e.code, e.message, e.data)
        # その他の予期せぬ例外
        except Exception as e:
            return self._error(msg.id, rpc.ErrorCode.INTERNAL_ERROR, str(e))

        # 3. JSON-RPCのレスポンスオブジェクトを作成して返す
        else:
            return rpc.JSONRPCResponse(jsonrpc=rpc.JSONRPC_VERSION, id=msg.id,
                                       result=result.model_dump(by_alias=True, exclude_none=True))

    def _error(self, id: rpc.RequestId | None, code: int, message: str, data: Any | None = None) -> rpc.JSONRPCError:
        """エラーオブジェクトを作成して返す.

        Args:
            id: リクエストID
            code: エラーコード
            message: エラーメッセージ
            data: 追加のエラー情報（任意）

        Returns:
            作成された JSONRPCError オブジェクト
        """
        error = rpc.ErrorData(code=code, message=message)
        if data is not None:
            error.data = data
        return rpc.JSONRPCError(jsonrpc=rpc.JSONRPC_VERSION,
                                id=id,
                                error=error)

    # ----- <サーバーが提供する機能ハンドラ> -----------------------------------------------------------------

    # ===== Initialize Methods =====
    def _handle_initialize(self, params: dict[str, Any] | None) -> mcp.InitializeResult:
        """initializeメソッド時に呼び出される. Initializeリクエストのparamsを受け取り、initializeリザルトを返す.

        Args:
            params (dict[str, Any] | None): initializeリクエストのパラメータ
        Returns:
            mcp.InitializeResult: 初期化結果オブジェクト
        """
        init = mcp.InitializeRequestParams.model_validate(params)   # 戻り値を捨てずに使う
        # on_initializeに登録された関数があれば呼び出す
        if self._on_initialize is not None:
            self._on_initialize(init.meta)
        # versionが異なる場合も接続を切るかどうかはクライアント側が判断するのでエラーは吐かない
        return mcp.InitializeResult(protocol_version=mcp.MCP_VERSION,
                                    capabilities=self._capabilities(),
                                    server_info=self.server_info)

    # ===== tools/ Methods =====
    def _handle_tools_list(self, params: dict[str, Any] | None) -> mcp.ListToolsResult:
        """tools/listメソッド時に呼び出される.サーバーが提供する関数ツールの一覧を返す.

        Args:
            params (dict[str, Any] | None): tools/listリクエストのパラメータ（使用されない）

        Returns:
            mcp.ListToolsResult: 関数ツールの一覧
        """
        return mcp.ListToolsResult(tools=[tool.to_tool() for tool in self.tools.values()])

    def _handle_call_tool(self, params: dict[str, Any] | None) -> mcp.CallToolResult:
        """tools/callメソッド時に呼び出される. 指定されたツールを呼び出し、その結果を返す.

        Args:
            params (dict[str, Any] | None): tools/callリクエストのパラメータ

        Returns:
            mcp.CallToolResult: ツール呼び出しの結果
        """
        p = mcp.CallToolRequestParams.model_validate(params)
        # 1. サーバー内でツールを検索
        tool = self.tools.get(p.name)
        if tool is None:
            raise mcp.MCPError(rpc.ErrorCode.INVALID_PARAMS,
                               f"Unknown tools: {p.name} (available: {', '.join(list(self.tools.keys()))})", None)

        # 2. 与えられた引数を検証
        try:
            args = tool.arguments_model.model_validate(p.arguments or {})
        except ValidationError as e:
            detail = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
            raise mcp.MCPError(rpc.ErrorCode.INVALID_PARAMS,
                               f"Invalid arguments for tool {p.name}: {detail}", None) from e

        # 3. ツールを実行して結果を取得。引数はunpackedして渡す
        try:
            value = tool.func(**args.model_dump())
        except Exception as e:
            return mcp.CallToolResult(content=[mcp.TextContent(text=f"{type(e).__name__}: {e}")], is_error=True)

        # 4. 結果を文字列に変換してcontentに格納
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)  # 日本語をそのまま出力する
        return mcp.CallToolResult(content=[mcp.TextContent(text=text)])

    # ===== resources/ Methods =====
    def _handle_resources_list(self, params: dict[str, Any] | None) -> mcp.ListResourcesResult:
        """resources/listメソッド時に呼び出される. 登録された資料の一覧を返す.

        Args:
            params: リクエストパラメータ（未使用）

        Returns:
            登録された資料の一覧を含む ListResourcesResult オブジェクト
        """
        return mcp.ListResourcesResult(resources=[r.to_resource() for r in self.resources.values()])

    def _handle_resources_read(self, params: dict[str, Any] | None) -> mcp.ReadResourceResult:
        """resources/readメソッド時に呼び出される. 指定されたURIの資料の中身を返す.

        Args:
            params: リクエストパラメータ

        Returns:
            指定されたURIの資料の中身を含む ReadResourceResult オブジェクト
        """
        p = mcp.ReadResourceRequestParams.model_validate(params)
        resource = self.resources.get(p.uri)
        if resource is None:
            raise mcp.MCPError(mcp.RESOURCE_NOT_FOUND, f"Resource not found: {p.uri}", {"uri": p.uri})

        value = resource.func()
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return mcp.ReadResourceResult(contents=[mcp.ResourceContents(uri=p.uri, mime_type=resource.mime_type, text=text)])

    # ===== prompts/ Methods =====
    def _handle_prompts_list(self, params: dict[str, Any] | None) -> mcp.ListPromptsResult:
        """prompts/listメソッド時に呼び出される. 登録された雛形の一覧を返す.

        Args:
            params: リクエストパラメータ（未使用）

        Returns:
            登録された雛形の一覧を含む ListPromptsResult オブジェクト
        """
        return mcp.ListPromptsResult(prompts=[p.to_prompt() for p in self.prompts.values()])

    def _handle_prompts_get(self, params: dict[str, Any] | None) -> mcp.GetPromptResult:
        """prompts/getメソッド時に呼び出される. 指定された雛形に引数を埋めて、メッセージとして返す.

        Args:
            params: リクエストパラメータ

        Returns:
            指定された雛形の内容を含む GetPromptResult オブジェクト
        """
        p = mcp.GetPromptRequestParams.model_validate(params)
        prompt = self.prompts.get(p.name)
        if prompt is None:
            raise mcp.MCPError(rpc.ErrorCode.INVALID_PARAMS, f"Unknown prompt: {p.name}", None)
        args = p.arguments or {}
        missing = [a.name for a in prompt.arguments if a.required and a.name not in args]
        if missing:
            raise mcp.MCPError(rpc.ErrorCode.INVALID_PARAMS,
                               f"Missing arguments for prompt {p.name}: {', '.join(missing)}", None)
        value = prompt.func(**args)
        return mcp.GetPromptResult(description=prompt.description,
                                   messages=[mcp.PromptMessage(role="user",
                                                               content=mcp.ContentBlock(type="text", text=str(value)))])

    def _handle_ping(self, params: dict[str, Any] | None) -> mcp.EmptyResult:
        """成功応答として空のリザルトを返す(debug用)."""
        return mcp.EmptyResult()

    # ----- <機能登録用デコレータ> -----------------------------------------------------------------

    def tool(self, description: str | None = None) -> Callable[[F], F]:
        """ツールを登録するデコレータを返す.

        mcp_tools*.pyが読み込まれた際に登録される.

        Args:
            description (str | None): ツールの説明。未指定の場合は関数のdocstringを使用
        Returns:
            Callable[[F], F]: デコレータとして使用可能な関数
        """
        def register(func: F) -> F:
            name = func.__name__
            doc = description or inspect.getdoc(func)
            # 引数から検証用の型を作る
            arguments_model = self._build_argumetns_model(func)

            # 提供toolsに追加
            self.tools[name] = RegisteredTool(name, doc, func, arguments_model)

            return func
        return register

    def _build_argumetns_model(self, func: Callable[..., Any]) -> type[BaseModel]:
        """渡された関数の引数（型と初期値）を定義したPydanticの型を作る.

        この型はクライアントから渡された引数の検証とinputSchemaの生成に使用される.

        Args:
            func (Callable[..., Any]): 引数の型と初期値を取得する対象の関数

        Returns:
            type[BaseModel]: 引数情報を持つ Pydantic モデルの型
            Model名が関数名+"Arguments" で、関数の引数名を要素名、型ヒントはそのまま、デフォルト値を初期値とする Pydantic モデルである.
        """
        fields: dict[str, Any] = {}
        name = func.__name__
        # inspect.signature(func).parameters.items() で引数名と引数情報のペアを取得
        for param_name, param in inspect.signature(func).parameters.items():
            # 型ヒントが無い場合はエラーとする
            if param.annotation is inspect.Parameter.empty:
                raise TypeError(f"{name} の引数 {param_name} に型ヒントがありません")
            # デフォルト値が無い場合は必須、ある場合は省略可能として扱う(creat_modelに型だけを渡した場合は必須扱いになる)
            default = ... if param.default is inspect.Parameter.empty else param.default
            fields[param_name] = (param.annotation, default)
        # モデル名、要素(辞書型)
        return create_model(f"{name}Arguments", **fields)

    def resource(self, uri: str, description: str | None = None,
                 mime_type: str = "text/plain") -> Callable[[F], F]:
        """リソースを登録するデコレータを返す.

        Args:
            uri (str): 資料の URI
            description (str | None): 資料の説明。未指定の場合は関数の docstring を使用
            mime_type (str): 資料の MIME タイプ
        Returns:
            Callable[[F], F]: デコレータとして使用可能な関数
        """
        def register(func: F) -> F:
            doc = description or inspect.getdoc(func)
            self.resources[uri] = RegisteredResource(uri, func.__name__, doc, mime_type, func)
            # ↑ 登録簿の鍵は uri。resources/read が uri で探すため（tools は名前で探した）
            return func
        return register

    def prompt(self, description: str | None = None) -> Callable[[F], F]:
        """プロンプトを登録するデコレータを返す.

        Args:
            description (str | None): 雛形の説明。未指定の場合は関数の docstring を使用
        Returns:
            Callable[[F], F]: デコレータとして使用可能な関数
        """
        def register(func: F) -> F:
            name = func.__name__
            arguments = []
            for param in inspect.signature(func).parameters.values():
                # prompt の引数は文字列だけ
                if param.annotation is not str:
                    raise TypeError(f"{name} の引数 {param.name} は str にしてください")
                # 引数情報を作成
                arguments.append(mcp.PromptArgument(
                    name=param.name,
                    required=param.default is inspect.Parameter.empty))  # 初期値が無い引数は「必須」
            doc = description or inspect.getdoc(func)
            self.prompts[name] = RegisteredPrompt(name, doc, func, arguments)
            return func
        return register

    # ----- <サーバー内部処理> -----------------------------------------------------------------

    def _capabilities(self) -> dict[str, Any]:
        """サーバーの提供する機能を辞書型にして返す.

        Returns:
            提供されているツール、資料、雛形の情報を含む辞書
        """
        registries = {
            "tools": self.tools,
            "resources": self.resources,
            "prompts": self.prompts,
        }
        return {name: {} for name, registry in registries.items() if registry}

    def on_initialize(self) -> Callable[[F], F]:
        """初期化処理を登録するデコレータを返す."""
        def register(func: F) -> F:
            self._on_initialize = func
            return func
        return register


if __name__ == "__main__":
    pass

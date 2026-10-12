"""mbpp server.py"""


import json
import inspect
from collections.abc import Callable
from typing import Any, TypeVar
from pydantic import ValidationError, create_model, BaseModel

from src.mcp_core.models import jsonrpc as rpc
from src.mcp_core.models import mcpmodel as mcp
from src.mcp_core.models.server_transport import ServerTransport
from src.mcp_core.server.stdio import StdioServerTransport
from src.mcp_core.server.tool_model import (
    RegisteredTool,
    RegisteredPrompt,
    RegisteredResource,
)

F = TypeVar("F", bound=Callable[..., Any])


class MCPServer:
    def __init__(self, name: str, version: str) -> None:
        self.handlers: dict[str, Callable[[dict[str, Any] | None], mcp.MCPModel]] = {  # methodと関数を辞書型で定義
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

    def run(self, transport: ServerTransport | None = None) -> None:
        """サーバーの受付を担当する."""
        if transport is None:
            transport = StdioServerTransport()
        transport.serve(self.process_message)

    def process_message(self, line: str) -> rpc.JSONRPCResponse | rpc.JSONRPCError | None:
        """受け取ったデータを解析して、クライアントに返すべき応答を返す."""
        # 1. json構文チェック
        try:
            data = json.loads(line)
        except json.JSONDecodeError as e:
            return self._error(None, rpc.ErrorCode.PARSE_ERROR, f"Parse error: {e}")

        # 2. JSON-RPC構文チェック
        try:
            msg = rpc.jsonrpc_message_adapter.validate_python(data)
        except ValidationError as e:
            return self._error(None, rpc.ErrorCode.INVALID_REQUEST, "Invalid Request", str(e))

        # 3. 問題なければdispatchへ
        if isinstance(msg, rpc.JSONRPCRequest):
            return self._dispatch(msg)

        # debug notification
        # if isinstance(msg, rpc.JSONRPCNotification):
        #     sys.stderr.write(msg.model_dump_json(by_alias=True, exclude_unset=True) + "\n")

        # 4. 通知など見逃す
        return None

    def _dispatch(self, msg: rpc.JSONRPCRequest) -> rpc.JSONRPCResponse | rpc.JSONRPCError:
        """リクエストを担当メソッドへ振り分けて、書き込みを指示する."""
        # 1. 受け取ったmethodをkeyに関数を呼び出す
        handler = self.handlers.get(msg.method)
        if handler is None:
            return self._error(msg.id, rpc.ErrorCode.METHOD_NOT_FOUND, f"Method not found: {msg.method}")

        # 2. method実行と結果を受け取る
        try:
            result = handler(msg.params)

        # handlerでraiseされた例外をキャッチする
        except ValidationError as e:
            return self._error(msg.id, rpc.ErrorCode.INVALID_PARAMS, "Invalid params", str(e))
        except mcp.MCPError as e:
            return self._error(msg.id, e.code, e.message, e.data)
        except Exception as e:
            return self._error(msg.id, rpc.ErrorCode.INTERNAL_ERROR, str(e))

        # 3. 結果を返す
        else:
            return rpc.JSONRPCResponse(jsonrpc=rpc.JSONRPC_VERSION, id=msg.id,
                                       result=result.model_dump(by_alias=True, exclude_none=True))

    def _handle_initialize(self, params: dict[str, Any] | None) -> mcp.InitializeResult:
        """MCPサーバーのバージョンと機能と情報をオブジェクトにまとめて返す."""
        mcp.InitializeRequestParams.model_validate(params)
        # versionが異なる場合も接続を切るかどうかはクライアント側が判断するのでエラーは吐かない
        return mcp.InitializeResult(protocol_version=mcp.MCP_VERSION,
                                    capabilities=self._capabilities(),  # tools/listなどを追加したあとはここに情報を乗せる必要がある、動的取得を設計予定
                                    server_info=self.server_info)

    def _handle_ping(self, params: dict[str, Any] | None) -> mcp.EmptyResult:
        """成功応答として空のリザルトを返す."""
        return mcp.EmptyResult()

    def _handle_tools_list(self, params: dict[str, Any] | None) -> mcp.ListToolsResult:
        """サーバーが提供する関数ツールのリストを返す."""
        return mcp.ListToolsResult(tools=[tool.to_tool() for tool in self.tools.values()])

    def _handle_call_tool(self, params: dict[str, Any] | None) -> mcp.CallToolResult:
        """サーバーが提供する関数ツールのリストを返す."""
        p = mcp.CallToolRequestParams.model_validate(params)
        # 1. tool検索
        tool = self.tools.get(p.name)
        if tool is None:  # toolが見つからなかった
            raise mcp.MCPError(rpc.ErrorCode.INVALID_PARAMS,
                               f"Unknown tools: {p.name} (available: {', '.join(list(self.tools.keys()))})", None)

        # 2. 引数検証  argumentsはOptionalのため
        try:
            args = tool.arguments_model.model_validate(p.arguments or {})
        except ValidationError as e:
            detail = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
            raise mcp.MCPError(rpc.ErrorCode.INVALID_PARAMS,
                               f"Invalid arguments for tool {p.name}: {detail}", None) from e

        # 3. modelを辞書にして渡す
        try:
            value = tool.func(**args.model_dump())
        except Exception as e:
            return mcp.CallToolResult(content=[mcp.TextContent(text=f"{type(e).__name__}: {e}")], is_error=True)

        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)  # 日本語をそのまま出力する
        return mcp.CallToolResult(content=[mcp.TextContent(text=text)])

    def _handle_resources_list(self, params: dict[str, Any] | None) -> mcp.ListResourcesResult:
        """登録された資料の一覧を返す."""
        return mcp.ListResourcesResult(resources=[r.to_resource() for r in self.resources.values()])

    def _handle_resources_read(self, params: dict[str, Any] | None) -> mcp.ReadResourceResult:
        """uri の資料の中身を返す."""
        p = mcp.ReadResourceRequestParams.model_validate(params)
        resource = self.resources.get(p.uri)
        if resource is None:
            raise mcp.MCPError(mcp.RESOURCE_NOT_FOUND, f"Resource not found: {p.uri}", {"uri": p.uri})
        value = resource.func()
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return mcp.ReadResourceResult(contents=[mcp.ResourceContents(uri=p.uri, mime_type=resource.mime_type, text=text)])

    def _handle_prompts_list(self, params: dict[str, Any] | None) -> mcp.ListPromptsResult:
        """登録された雛形の一覧を返す."""
        return mcp.ListPromptsResult(prompts=[p.to_prompt() for p in self.prompts.values()])

    def _handle_prompts_get(self, params: dict[str, Any] | None) -> mcp.GetPromptResult:
        """雛形に引数を埋めて、メッセージとして返す."""
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

    def _capabilities(self) -> dict[str, Any]:
        """サーバーの提供する機能を動的に取得して返す."""
        registries = {
            "tools": self.tools,
            "resources": self.resources,
            "prompts": self.prompts,
        }
        return {name: {} for name, registry in registries.items() if registry}

    def _error(self, id: rpc.RequestId | None, code: int, message: str, data: Any | None = None) -> rpc.JSONRPCError:
        """エラーオブジェクトを作成して返す."""
        error = rpc.ErrorData(code=code, message=message)
        if data is not None:
            error.data = data
        return rpc.JSONRPCError(jsonrpc=rpc.JSONRPC_VERSION,
                                id=id,
                                error=error)

    def tool(self, description: str | None = None) -> Callable[[F], F]:
        """ツールを動的にリスト化するためのデコレータ."""
        def register(func: F) -> F:
            """MCPサーバーが提供するツールを動的にリスト化する."""
            name = func.__name__                                                    # 1. 名前 = 関数名
            doc = description or inspect.getdoc(func)                               # 2. 説明 = 引数で渡された説明、無ければ docstring

            arguments_model = self._build_argumetns_model(func)                      # 3. 引数から検証用モデルを作る

            self.tools[name] = RegisteredTool(name, doc, func, arguments_model)     # 4. 登録簿に載せる
            return func                                                             # 5. 関数はそのまま返す
        return register

    def resource(self, uri: str, description: str | None = None,
                 mime_type: str = "text/plain") -> Callable[[F], F]:
        """関数を、uri で読める資料として登録する."""
        def register(func: F) -> F:
            doc = description or inspect.getdoc(func)
            self.resources[uri] = RegisteredResource(uri, func.__name__, doc, mime_type, func)
            # ↑ 登録簿の鍵は uri。resources/read が uri で探すため（tools は名前で探した）
            return func
        return register

    def prompt(self, description: str | None = None) -> Callable[[F], F]:
        """関数を、指示の雛形として登録する。引数はすべて文字列."""
        def register(func: F) -> F:
            arguments = []
            for param in inspect.signature(func).parameters.values():
                if param.annotation is not str:  # prompt の引数は文字列だけ
                    raise TypeError(f"{func.__name__} の引数 {param.name} は str にしてください")
                arguments.append(mcp.PromptArgument(
                    name=param.name,
                    required=param.default is inspect.Parameter.empty))  # 初期値が無い引数は「必須」
            doc = description or inspect.getdoc(func)
            self.prompts[func.__name__] = RegisteredPrompt(func.__name__, doc, func, arguments)
            return func
        return register

    def _build_argumetns_model(self, func: Callable[..., Any]) -> type[BaseModel]:
        """渡された関数の引数（型と初期値）をまとめたモデルを動的に作る."""
        fields: dict[str, Any] = {}
        name = func.__name__
        for param_name, param in inspect.signature(func).parameters.items():    # 引数名 -> 引数の情報 -> 引数名とオブジェクト情報
            if param.annotation is inspect.Parameter.empty:
                raise TypeError(f"{name} の引数 {param_name} に型ヒントがありません")
            default = ... if param.default is inspect.Parameter.empty else param.default
            fields[param_name] = (param.annotation, default)
        return create_model(f"{name}Arguments", **fields)


if __name__ == "__main__":
    pass

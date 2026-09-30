"""
class MCPServer:
    def __init__(self) -> None:
        self.handlers = {                               # 対応表
            METHOD_INITIALIZE: self.handle_initialize,
            "ping": self.handle_ping,
        }

    def run(self) -> None:                              # 受付係
        for line in sys.stdin:                          #   EOF で自然にループが終わる
            ...                                         #   ② 封筒に変換 → 種類で分岐
                                                        #      → self._dispatch(msg)
                                                        #      → 壊れていれば self._error(None, ...)

    def _dispatch(self, msg) -> None: ...               # 振り分け係（上のコード）
                                                        #   → self.handlers[...](params)
                                                        #   → self._write(...) / self._error(...)

    def handle_initialize(self, params) -> InitializeResult: ...   # 担当課
    def handle_ping(self, params) -> EmptyResult: ...              # 担当課

    def _error(self, id, code, message) -> None: ...   # エラー応答を組み立てて → self._write
    def _write(self, message) -> None: ...                   # 発送係


if __name__ == "__main__":
    MCPServer().run()


"""


import sys
import json
import inspect
from collections.abc import Callable
from typing import Any, TypeVar
from pydantic import ValidationError, create_model, BaseModel

from src.models import jsonrpc as rpc
from src.models import mcpmodel as mcp
from src.mcp_server.tool_model import RegisteredTool

F = TypeVar("F", bound=Callable[..., Any])


class MCPServer:
    def __init__(self) -> None:
        self.handlers: dict[str, Callable[[dict[str, Any] | None], mcp.MCPModel]] = {  # methodと関数を辞書型で定義
            mcp.Method.INITIALIZE: self._handle_initialize,
            mcp.Method.PING: self._handle_ping
        }
        self.tools: dict[str, RegisteredTool]

    def run(self) -> None:
        """サーバーの受付を担当する."""
        # 1.stdinを受け取る
        for line in sys.stdin:  # EOFでループが終わる clientが異常終了した場合は子プロセスにEOFが届く
            if not line.strip():  # '\n'などのから文字を読み飛ばす
                continue
            # 2. クライアントへの返答を生成
            response = self.process_message(line)
            if response is not None:
                self._write(response)

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
                                    server_info=mcp.Implementation(name="agent-smith-mbpp", version="0.1.0"))

    def _handle_ping(self, params: dict[str, Any] | None) -> mcp.EmptyResult:
        """成功応答として空のリザルトを返す."""
        return mcp.EmptyResult()

    def _capabilities(self) -> dict[str, Any]:
        """サーバーの提供する機能を動的に取得して返す."""
        return {}  # いずれ追加

    def _error(self, id: rpc.RequestId | None, code: int, message: str, data: Any | None = None) -> rpc.JSONRPCError:
        """エラーオブジェクトを作成して返す."""
        error = rpc.ErrorData(code=code, message=message)
        if data is not None:
            error.data = data
        return rpc.JSONRPCError(jsonrpc=rpc.JSONRPC_VERSION,
                                id=id,
                                error=error)

    def _write(self, msg: rpc.JSONRPCResponse | rpc.JSONRPCError) -> None:
        """渡されたレスポンスオブジェクトをstrにして標準出力へ書き込む."""
        # exclude_unsetはコードで指定しなかった値、exclude_noneは値がNoneのものを消してjson文字列にする。
        sys.stdout.write(msg.model_dump_json(by_alias=True, exclude_unset=True) + "\n")
        sys.stdout.flush()

    def tool(self, description: str | None = None) -> callable[[F], F]:
        def register(func: F) -> F:
            name = func.__name__                                                    # 1. 名前 = 関数名
            doc = description or inspect.getdoc(func)                               # 2. 説明 = 引数で渡された説明、無ければ docstring

            arguments_model = self._build_argumets_model(func)                      # 3. 引数から検証用モデルを作る

            self.tools[name] = RegisteredTool(name, doc, func, arguments_model)     # 4. 登録簿に載せる
            return func                                                             # 5. 関数はそのまま返す
        return register

    def _build_argumets_model(self, func: Callable[..., Any]) -> type[BaseModel]:
        """関数の引数（型と初期値）をまとめたモデルを作る."""
        fields = {}
        name = func.__name__
        for param_name, param in inspect.signature(func).parameters.items():    # 引数名 -> 引数の情報 -> 引数名とオブジェクト情報
            if param.annotation is inspect.Parameter.empty:
                raise TypeError(f"{name} の引数 {param_name} に型ヒントがありません")
            default = ... if param.default is inspect.Parameter.empty else param.default
            fields[param_name] = (param.annotation, default)
        return create_model(f"{name}Arguments", **fields)
    # 3で型ヒントが無い引数を見つけたら、その場で TypeError にしています。
    # 型ヒントが無いと、スキーマを作れないからです。
    # サーバーの起動時（ファイルの読み込み時）に、すぐエラーで止まるので、「ツールを呼んで初めて問題に気づく」ことを防げます。
    # 間違いは、できるだけ早い段階で止めるのが定石です。

def main() -> None:
    MCPServer().run()


if __name__ == "__main__":
    main()

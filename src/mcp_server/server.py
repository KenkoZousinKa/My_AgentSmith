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
from collections.abc import Callable
from typing import Any
from pydantic import ValidationError

from src.models import jsonrpc as rpc
from src.models import mcpmodel as mcp


class MCPServer:
    def __init__(self) -> None:
        self.handlers: dict[str, Callable[[dict[str, Any] | None], mcp.MCPModel]] = {  # methodと関数を辞書型で定義
            mcp.Method.INITIALIZE: self._handle_initialize,
            mcp.Method.PING: self._handle_ping
        }

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


def main() -> None:
    MCPServer().run()


if __name__ == "__main__":
    main()


# def run_tests(code: str, test_list: list[str]) -> dict[str, bool | str]:
#     """実際のツール処理（ここではダミー）"""
#     return {"success": True, "output": "テスト成功しました"}

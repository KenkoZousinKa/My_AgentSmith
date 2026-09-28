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
                                                        #      → 壊れていれば self._write_error(None, ...)

    def _dispatch(self, msg) -> None: ...               # 振り分け係（上のコード）
                                                        #   → self.handlers[...](params)
                                                        #   → self._write(...) / self._write_error(...)

    def handle_initialize(self, params) -> InitializeResult: ...   # 担当課
    def handle_ping(self, params) -> EmptyResult: ...              # 担当課

    def _write_error(self, id, code, message) -> None: ...   # エラー応答を組み立てて → self._write
    def _write(self, message) -> None: ...                   # 発送係


if __name__ == "__main__":
    MCPServer().run()


"""


import sys
import json
from typing import Any
from pydantic import ValidationError

from src.models.jsonrpc import (
    JSONRPC_VERSION,
    RequestId,
    jsonrpc_message_adapter,
    JSONRPCRequest,
    JSONRPCResponse,
    ErrorData,
    JSONRPCError,
    PARSE_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    INVALID_PARAMS,
    INTERNAL_ERROR
)
from src.models.mcpmodel import (
    MCP_VERSION,
    METHOD_INITIALIZE,
    InitializeResult,
    InitializeRequestParams,
    Implementation,
    EmptyResult
)
from src.mcp_server.error import (
    MCPError
)


class MCPServer:
    def __init__(self) -> None:
        self.handlers = {
            METHOD_INITIALIZE: self.handle_initialize,
        }

    def run(self) -> None:
        """サーバーの受付を担当する."""
        for line in sys.stdin:
            if not line.strip():
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                self._write_error(None, PARSE_ERROR, f"Parse error: {e}")
                continue

            try:
                msg = jsonrpc_message_adapter.validate_python(data)
            except ValidationError as e:
                self._write_error(None, INVALID_REQUEST, str(e))
                continue

            else:
                if isinstance(msg, JSONRPCRequest):
                    self._dispatch(msg)

    def _dispatch(self, msg: JSONRPCRequest) -> None:
        """リクエストを担当メソッドへ振り分けて、書き込みを指示する."""
        handler = self.handlers.get(msg.method)
        if handler is None:
            self._write_error(msg.id, METHOD_NOT_FOUND, f"Method not found: {msg.method}")
            return
        try:
            result = handler(msg.params)

        # handlerでraiseされた例外をキャッチする
        except ValidationError as e:
            self._write_error(msg.id, INVALID_PARAMS, str(e))
        except MCPError as e:
            self._write_error(msg.id, e.code, e.message)
        except Exception as e:
            self._write_error(msg.id, INTERNAL_ERROR, str(e))
        else:
            self._write(JSONRPCResponse(jsonrpc=JSONRPC_VERSION, id=msg.id,
                                        result=result.model_dump(by_alias=True, exclude_none=True)))

    def handle_initialize(self, params: dict[str, Any] | None) -> InitializeResult:
        """MCPサーバーのバージョンと機能と情報をオブジェクトにまとめて返す."""
        InitializeRequestParams.model_validate(params)
        # versionが異なる場合も接続を切るかどうかはクライアント側が判断するのでエラーは吐かない
        return InitializeResult(protocol_version=MCP_VERSION,
                                capabilities=self._capabilities(),  # tools/listなどを追加したあとはここに情報を乗せる必要がある、動的取得を設計予定
                                server_info=Implementation(name="agent-smith-mbpp", version="0.1.0"))

    def handle_ping(self, params: dict[str, Any] | None) -> EmptyResult:
        """成功応答として空のリザルトを返す."""
        InitializeRequestParams.model_validate(params)
        return EmptyResult()

    def _capabilities(self) -> dict[str, Any]:
        """サーバーの提供する機能を動的に取得して返す."""
        return {}

    def _write_error(self, id: RequestId | None, code: int, message: str) -> None:
        """エラーオブジェクトを作成し、標準出力へ書き込む."""
        self._write(JSONRPCError(jsonrpc=JSONRPC_VERSION,
                                 id=id,
                                 error=ErrorData(code=code,
                                                 message=message)))

    def _write(self, msg: JSONRPCResponse | JSONRPCError) -> None:
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

"""JSON-RPC 2.0 モデル."""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal
from pydantic import BaseModel, Field, TypeAdapter
from enum import IntEnum

RequestId = Annotated[int, Field(strict=True)] | str
"""JSON-RPC リクエストの ID."""

JSONRPC_VERSION: Final[Literal["2.0"]] = "2.0"
"""すべての MCP メッセージに入る JSON-RPC のバージョン文字列."""


class JSONRPCRequest(BaseModel):
    """応答を期待する JSON-RPC リクエスト."""

    jsonrpc: Literal["2.0"]
    id: RequestId
    method: str
    params: dict[str, Any] | None = None


class JSONRPCNotification(BaseModel):
    """応答を期待しない JSON-RPC 通知."""

    jsonrpc: Literal["2.0"]
    method: str
    params: dict[str, Any] | None = None


class JSONRPCResponse(BaseModel):
    """リクエストに対する成功応答（エラーではないもの）。"""

    jsonrpc: Literal["2.0"]
    id: RequestId
    result: dict[str, Any]


# ===== Error Class =====


class ErrorCode(IntEnum):
    """JSON-RPC 標準のエラーコード."""
    PARSE_ERROR = -32700        # JSON-RPC 標準: 不正な JSON を受信した。
    INVALID_REQUEST = -32600    # JSON-RPC 標準: 送られてきたものが正しいリクエストオブジェクトではない。
    METHOD_NOT_FOUND = -32601   # JSON-RPC 標準: 要求されたメソッドが存在しない、または利用できない。
    INVALID_PARAMS = -32602     # JSON-RPC 標準: メソッドのパラメータが不正。
    INTERNAL_ERROR = -32603     # JSON-RPC 標準: 受信側の内部でエラーが発生した。


class ErrorData(BaseModel):
    """JSON-RPC エラー応答に入れるエラー情報。"""

    code: int
    """発生したエラーの種類。"""

    message: str
    """エラーの短い説明。簡潔な一文にとどめるべき（SHOULD）。"""

    data: Any = None
    """エラーについての追加情報。

    中身は送信側が自由に決める（詳細なエラー情報、入れ子のエラーなど）。
    """


class JSONRPCError(BaseModel):
    """リクエストの処理中にエラーが起きたことを示す応答。"""

    jsonrpc: Literal["2.0"]
    id: RequestId | None
    """このエラーが応答している元のリクエストの ID。

    JSON-RPC 2.0 では「必須だが null 可」。ID を特定できなかった場合
    （受信した JSON が壊れていた場合など）は None、つまり `"id": null` を入れる。
    """

    error: ErrorData


JSONRPCMessage = JSONRPCRequest | JSONRPCNotification | JSONRPCResponse | JSONRPCError
"""受信して解釈する、または送信のために組み立てる、あらゆる JSON-RPC の封筒。"""

jsonrpc_message_adapter: TypeAdapter[JSONRPCMessage] = TypeAdapter(JSONRPCMessage)

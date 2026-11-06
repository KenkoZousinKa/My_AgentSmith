"""JSON-RPC 2.0 モデル.

サーバーとクライアントが JSON-RPC 2.0 でやり取りするメッセージの型を定義する.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal
from pydantic import BaseModel, Field, TypeAdapter
from enum import IntEnum

RequestId = Annotated[int, Field(strict=True)] | str
"""JSON-RPC リクエストの ID. """

JSONRPC_VERSION: Final[Literal["2.0"]] = "2.0"
"""JSON-RPC のバージョン文字列."""


class JSONRPCRequest(BaseModel):
    """JSON-RPC のリクエストフォーマット.

    Attributes:
        jsonrpc (Literal["2.0"]): JSON-RPC のバージョン
        id (RequestId): リクエストの ID
        method (str): リクエストするメソッド名
        params (dict[str, Any] | None): メソッドに渡すパラメータ。省略可能。
    """

    jsonrpc: Literal["2.0"]
    id: RequestId
    method: str
    params: dict[str, Any] | None = None


class JSONRPCNotification(BaseModel):
    """JSON-RPCの通知フォーマット。返答されないためidはない.

    Attributes:
        jsonrpc (Literal["2.0"]): JSON-RPC のバージョン
        method (str): 通知するメソッド名
        params (dict[str, Any] | None): メソッドに渡すパラメータ。省略可能。
    """

    jsonrpc: Literal["2.0"]
    method: str
    params: dict[str, Any] | None = None


class JSONRPCResponse(BaseModel):
    """JSON-RPCの応答フォーマット.

    Attributes:
        jsonrpc (Literal["2.0"]): JSON-RPC のバージョン
        id (RequestId): 応答するリクエストの ID
        result (dict[str, Any]): リクエストの結果。
    """

    jsonrpc: Literal["2.0"]
    id: RequestId
    result: dict[str, Any]


# ===== Error Class =====


class ErrorCode(IntEnum):
    """JSON-RPC エラーコード."""
    PARSE_ERROR = -32700        # 不正な JSON を受信した。
    INVALID_REQUEST = -32600    # 送られてきたものが正しいリクエストオブジェクトではない。
    METHOD_NOT_FOUND = -32601   # 要求されたメソッドが存在しない、または利用できない。
    INVALID_PARAMS = -32602     # メソッドのパラメータが不正。
    INTERNAL_ERROR = -32603     # 受信側の内部でエラーが発生した。


class ErrorData(BaseModel):
    """JSONRPCErroオブジェクトのerro部.

    Attributes:
        code (int): ErrorCode の値
        message (str): エラーメッセージ
        data (Any): エラーの詳細情報。省略可能。
    """

    code: int
    message: str
    data: Any = None


class JSONRPCError(BaseModel):
    """JSONRPCのエラー応答フォーマット.

    Attributes:
        jsonrpc (Literal["2.0"]): JSON-RPC のバージョン
        id (RequestId | None): 元のリクエストの ID。なければ None。
        error (ErrorData): ErrorData オブジェクト。エラーコード、メッセージ、詳細情報を含む
    """

    jsonrpc: Literal["2.0"]
    id: RequestId | None
    error: ErrorData


JSONRPCMessage = JSONRPCRequest | JSONRPCNotification | JSONRPCResponse | JSONRPCError
"""JSON-RPC のメッセージ型。リクエスト、通知、応答、エラーのいずれか."""

jsonrpc_message_adapter: TypeAdapter[JSONRPCMessage] = TypeAdapter(JSONRPCMessage)
"""JSON文字列を対応したJSON-RPCの型に変換するためのTypeAdapter."""

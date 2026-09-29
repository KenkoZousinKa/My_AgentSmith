"""MCP プロトコルのモデル（JSON-RPC の封筒に入る中身）。"""

from __future__ import annotations

from typing import Any, Final, Literal
from pydantic import (
    BaseModel,
    ConfigDict
)
from pydantic.alias_generators import to_camel
from enum import StrEnum


MCP_VERSION: Final[Literal["2025-06-18"]] = "2025-06-18"


class Method(StrEnum):
    INITIALIZE = "initialize"
    INITIALIZED = "notifications/initialized"
    PING = "ping"
    TOOLS_LIST = "tools/list"
    TOOLS_CALL = "tools/call"


class MCPModel(BaseModel):
    """すべての MCP モデルの基底クラス。

    Python 側ではスネークケース（protocol_version）で書き、
    JSON に出し入れするときはキャメルケース（protocolVersion）に自動で変換する。
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Implementation(MCPModel):
    """MCP 実装の名前とバージョン（`clientInfo` / `serverInfo` の中身）。"""

    name: str
    version: str


class InitializeRequestParams(MCPModel):
    """`initialize` リクエストのパラメータ（クライアント → サーバー）。"""

    protocol_version: str
    """クライアントが対応している中で最新の MCP バージョン（希望する版）。"""
    capabilities: dict[str, Any]
    """クライアントが提供できる機能。"""
    client_info: Implementation


class InitializeResult(MCPModel):
    """`initialize` リクエストへの応答の中身（サーバー → クライアント）。"""

    protocol_version: str
    """サーバーが使うと決めた MCP バージョン。クライアントが対応していなければ、クライアント側が切断する（MUST）。"""
    capabilities: dict[str, Any]
    """サーバーが提供する機能（tools / resources / prompts など）。"""
    server_info: Implementation


class Tool(MCPModel):
    """ツール一つ分のモデル定義"""
    name: str
    description: str | None = None
    input_schema: dict[str, Any]


class ListToolsResult(MCPModel):
    """tools/list リクエストへの応答の中身"""
    tools: list[Tool]


class EmptyResult(MCPModel):
    """中身のない成功応答(ping)"""


# ===== Error Class =====


class MCPClientError(Exception):
    """MCP クライアントで起きたエラーの基底クラス.

    サンドボックス以上のプロセスに対してクライアントで起きたエラーを伝えるもの.
    """


class MCPConnectionError(MCPClientError):
    """サーバーが起動しない、途中で落ちた(readlineが空だった)、など接続の問題."""


class MCPProtocolError(MCPClientError):
    """サーバーが MCP / JSON-RPC の形式に合わないメッセージを送ってきた.

    サーバーが起因するエラー。It's MangoMan's fault.
    """


class MCPError(MCPClientError):
    """サーバーが JSON-RPC のエラー応答を返した.

    このエラーはサーバーサイドが起因ではないケースで使う。(LLMが構文を間違えているなど)
    ネストされたエラーオブジェクトも含めてLLMに渡すことを推奨。
    """
    def __init__(self, code: int, message: str, data: Any) -> None:
        super().__init__(code, message, data)
        self.code = code
        self.message = message
        self.data = data

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"

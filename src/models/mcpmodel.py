"""MCP プロトコルのモデル（JSON-RPC の封筒に入る中身）。"""

from __future__ import annotations

from typing import Any, Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict
)
from pydantic.alias_generators import to_camel


METHOD_INITIALIZE: Final = "initialize"
METHOD_INITIALIZED: Final = "notifications/initialized"

MCP_VERSION: Final[Literal["2025-06-18"]] = "2025-06-18"

METHODS = [
    METHOD_INITIALIZE,
    METHOD_INITIALIZED
]


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

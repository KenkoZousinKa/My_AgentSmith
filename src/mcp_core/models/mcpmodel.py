"""MCP プロトコルのモデル（JSON-RPC の封筒に入る中身）。"""

from __future__ import annotations

from typing import Any, Final, Literal
from pydantic import (
    BaseModel,
    ConfigDict,
    Field
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
    RESOURCES_LIST = "resources/list"
    RESOURCES_READ = "resources/read"
    PROMPTS_LIST = "prompts/list"
    PROMPTS_GET = "prompts/get"


class MCPModel(BaseModel):
    """すべての MCP モデルの基底クラス。

    Python 側ではスネークケース（protocol_version）で書き、
    JSON に出し入れするときはキャメルケース（protocolVersion）に自動で変換する。
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    #   alias 要素名をキャメル型に変換
    #   populate 変換前の要素名でのインポートをエラーとしない


# ===== initialize/ Class =====


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
    """`initialize` リクエストへの応答のresult（サーバー → クライアント）。"""

    protocol_version: str
    """サーバーが使うと決めた MCP バージョン。クライアントが対応していなければ、クライアント側が切断する（MUST）。"""
    capabilities: dict[str, Any]
    """サーバーが提供する機能（tools / resources / prompts など）。"""
    server_info: Implementation


# ===== tools/ Class =====


class Tool(MCPModel):
    """ツール一つ分のモデル定義"""
    name: str
    description: str | None = None
    input_schema: dict[str, Any]


class ListToolsResult(MCPModel):
    """tools/list リクエストへの応答のresult"""
    tools: list[Tool]


class CallToolRequestParams(MCPModel):
    """tools/call リクエストのパラメータ(クライアント -> サーバー)"""
    name: str
    arguments: dict[str, Any] | None = None


class TextContent(MCPModel):
    """CallToolResultの中で使われる 関数のテキスト結果."""
    type: Literal["text"] = "text"
    text: str


class CallToolResult(MCPModel):
    """tools/call リクエストへの応答のresult"""
    content: list[TextContent]
    is_error: bool = False

    @property
    def text(self) -> str:
        """content の中のテキストを、1つの文字列につなげて返す."""
        return "\n".join(c.text for c in self.content)


class EmptyResult(MCPModel):
    """中身のない成功応答(ping)"""


# ===== resources/ Class =====


class Resource(MCPModel):
    """resources/list で返される、資料1つ分の情報."""
    uri: str
    # ↑ 資料を指す名前。"file:///…"、"test://hello" など。サーバーが自由に決める
    name: str
    description: str | None = None
    mime_type: str | None = None
    # ↑ JSON では "mimeType"。"text/plain"、"application/json" など


class ListResourcesResult(MCPModel):
    """resources/list リクエストへの応答の result."""
    resources: list[Resource]


class ReadResourceRequestParams(MCPModel):
    """resources/read リクエストのパラメータ（クライアント → サーバー）."""
    uri: str


class ResourceContents(MCPModel):
    """resources/read で返される、資料の中身1つ分."""
    uri: str
    mime_type: str | None = None
    text: str | None = None
    # ↑ 文字の資料なら text に入る
    blob: str | None = None
    # ↑ 画像などのバイナリなら、base64 という形式の文字列で blob に入る（text と blob はどちらか一方）


class ReadResourceResult(MCPModel):
    """resources/read リクエストへの応答の result."""
    contents: list[ResourceContents]
    # ↑ 1つの URI に、中身が複数返ることもある（フォルダーを指す URI など）


# ===== prompts/ Class =====


class ContentBlock(MCPModel):
    """メッセージの中身の1つ分（テキスト、画像、音声など）."""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="allow")
    # ↑ extra="allow"：知らない項目（画像の data や mimeType など）も捨てずに持っておく。
    #   未知のサーバーは、テキスト以外の中身を送ってくることがあるため。
    #   model_config を書き直すと MCPModel の設定が上書きされるので、alias の設定も書き直している
    type: str
    # ↑ "text"、"image"、"audio"、"resource" など。
    text: str | None = None
    # ↑ type が "text" のときだけ入る。それ以外は None


class PromptArgument(MCPModel):
    """prompt が受け取る引数1つ分の説明."""
    name: str
    description: str | None = None
    required: bool = False


class Prompt(MCPModel):
    """prompts/list で返される、指示の1つ分の情報."""
    name: str
    description: str | None = None
    arguments: list[PromptArgument] = Field(default_factory=list)


class ListPromptsResult(MCPModel):
    """prompts/list リクエストへの応答の result."""
    prompts: list[Prompt]


class GetPromptRequestParams(MCPModel):
    """prompts/get リクエストのパラメータ（クライアント → サーバー）."""
    name: str
    arguments: dict[str, str] | None = None
    # ↑ 仕様で、prompt の引数の値は文字列だけと決まっている


class PromptMessage(MCPModel):
    """結果の、メッセージ1つ分."""
    role: Literal["user", "assistant"]
    # ↑ LLM との会話の、誰の発言か。
    content: ContentBlock


class GetPromptResult(MCPModel):
    """prompts/get リクエストへの応答の result."""
    description: str | None = None  # 完成したプロンプト全体の説明
    messages: list[PromptMessage]


# ===== Error Class =====

RESOURCE_NOT_FOUND: Final = -32002


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

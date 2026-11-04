"""MCPモデル定義.

MCPクライアントとサーバー同士でやり取りするJSON-RPCのparam部定義とerror部定義をまとめたもの.
"""

from __future__ import annotations

from typing import Any, Final, Literal
from pydantic import (
    BaseModel,
    ConfigDict,
    Field
)
from pydantic.alias_generators import to_camel
from enum import Enum

MCP_VERSION: Final[Literal["2025-06-18"]] = "2025-06-18"
"""MCPのバージョン文字列."""


class Method(str, Enum):
    """MCPが使用するJSON-RPCのメソッド部."""
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
    """MCPで使用するJSON-RPCのparam部やresult部のモデルの基底クラス.

    Attributes:
        model_config (ConfigDict): Pydanticのモデル設定。
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    #   alias_generator: JSON項目名にする際に要素名をキャメル型に変換する。
    #   populate_by_name: JSON項目名ではなくインスタンス時にキャメル型ではなく要素名で代入できる。


# ===== initialize/ Class =====

class Implementation(MCPModel):
    """InitalizeRequestParamsとInitializeResultのinfo部のモデル定義.

    Attributes:
        name (str): 実装の名前
        version (str): 実装のバージョン
    """

    name: str
    version: str


class InitializeRequestParams(MCPModel):
    """クライアントがサーバーに送るJSON_RPC initializeリクエストのparam部.

    Attributes:
        protocol_version (str): クライアントが使うMCPのバージョン
        capabilities (dict[str, Any]): クライアントが提供する機能（今回はない）
        client_info (Implementation): クライアントの情報
        meta (dict[str, Any] | None): クライアントがサーバーに提供する情報。省略可能。
    """

    protocol_version: str
    capabilities: dict[str, Any]
    client_info: Implementation
    meta: dict[str, Any] | None = Field(default=None, validation_alias="_meta", serialization_alias="_meta")
#   jsonでは_metaで扱う。
#   validation_alias：JSON から読むとき（model_validate）に "_meta" を受け付ける
#   serialization_alias： jsonへの変換時は"_meta" という名前にする。


class InitializeResult(MCPModel):
    """サーバーがクライアントに返すJSON_RPC initializeリザルトのresult部.

    Attributes:
        protocol_version (str): サーバーが使うMCPのバージョン
        capabilities (dict[str, Any]): サーバーが提供する機能（今回はない）
        server_info (Implementation): サーバーの情報
    """

    protocol_version: str
    capabilities: dict[str, Any]
    server_info: Implementation


# ===== tools/ Class =====

class Tool(MCPModel):
    """サーバーから返されるlistToolsResultのtool部、ツール1つ分の情報.

    Attributes:
        name (str): ツールの名前(関数名)
        description (str | None): ツールのDocString。省略可能。
        input_schema (dict[str, Any]): ツールの入力パラメータの JSON Schema。ツールの引数の型を定義する。
    """
    name: str
    description: str | None = None
    input_schema: dict[str, Any]


class ListToolsResult(MCPModel):
    """tools/list リクエストからサーバーが返すresult部.

    Attributes:
        tools (list[Tool]): サーバーが提供するツールのリスト
    """
    tools: list[Tool]


class CallToolRequestParams(MCPModel):
    """tools/call リクエストのparam部.

    クライアントがサーバーに送るツール呼び出しのパラメータ.

    Attributes:
        name (str): 呼び出すツールの名前(関数名)
        arguments (dict[str, Any] | None): ツールに渡す引数。省略可能。
    """
    name: str
    arguments: dict[str, Any] | None = None


class TextContent(MCPModel):
    """CallToolResultの中で使われるcontent部のモデル定義.

    例外も含めツールの実行結果がstrで記録される

    Attributes:
        type (Literal["text"]): contentの型。text固定。
        text (str): contentの中のテキスト。
    """
    type: Literal["text"] = "text"
    text: str


class CallToolResult(MCPModel):
    """tools/call リクエストからサーバーが返すresult部.

    ツールの実行結果を表す。
    他MCPサーバーではcontentの中に画像や音声なども入るが、現状はtextのみ。
    複数返ることもあるので、contentはリストになっている。自作サーバーは1つしか返さない

    Attributes:
        content (list[TextContent]): ツールの実行結果の中身。
        is_error (bool): ツールの実行がエラーだったかどうか。
    """
    content: list[TextContent]
    is_error: bool = False

    @property
    def text(self) -> str:
        """contentの中のテキストをまとめて返す.

        Returns:
            str: contentの中のテキストをまとめた文字列。
        """
        return "\n".join(c.text for c in self.content)


class EmptyResult(MCPModel):
    """中身のない成功応答(ping)."""


# ===== resources/ Class =====

class Resource(MCPModel):
    """resources/list で返される、資料の1つ分の情報.

    Attributes:
        uri (str): 資料を指す名前。"file:///…"、"test://hello" など。
        name (str): 資料の表示名。今回はDocString
        description (str | None): 資料の説明。省略可能。
        mime_type (str | None): 資料の MIME タイプ。"text/plain"、"application/json" など。省略可能
    """
    uri: str
    name: str
    description: str | None = None
    mime_type: str | None = None


class ListResourcesResult(MCPModel):
    """resources/list リクエストからサーバーが返すresult部.

    Attributes:
        resources (list[Resource]): サーバーが提供する資料のリスト
    """
    resources: list[Resource]


class ReadResourceRequestParams(MCPModel):
    """resources/read リクエストのparam部.

    Attributes:
        uri (str): 資料の URI
    """
    uri: str


class ResourceContents(MCPModel):
    """resources/read で返される、資料の中身1つ分.

    Attributes:
        uri (str): 資料の URI
        mime_type (str | None): 資料の MIME タイプ。"text/plain"、"application/json" など。省略可能
        text (str | None): 文字の資料なら text に入る。省略可能
        blob (str | None): 画像などのバイナリなら、base64 という形式の文字列で blob に入る（text と blob はどちらか一方）。省略可能
    """
    uri: str
    mime_type: str | None = None
    text: str | None = None
    blob: str | None = None


class ReadResourceResult(MCPModel):
    """resources/read リクエストから返すresult部.

    Attributes:
        contents (list[ResourceContents]): 資料の中身のリスト。ディレクトリの場合複数の中身が返る.
    """
    contents: list[ResourceContents]


# ===== prompts/ Class =====

class ContentBlock(MCPModel):
    """contentの中の1ブロック分。text、image、audio、resourceなどがあるが、現状はtextのみ.

    Attributes:
        type (str): contentの型。text、image、audio、resourceなど。
        text (str | None): contentの中のテキスト。省略可能。
    """
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="allow")
    # ↑ extra="allow"：知らない項目（画像の data や mimeType など）も捨てずに持っておく。
    #   未知のサーバーは、テキスト以外の中身を送ってくることがあるため。
    type: str
    text: str | None = None


class PromptArgument(MCPModel):
    """prompts/list で返される、プロンプト引数の1つ分の情報.

    Attributes:
        name (str): 引数の名前
        description (str | None): 引数の説明。省略可能。
        required (bool): 引数が必須かどうか。
    """
    name: str
    description: str | None = None
    required: bool = False


class Prompt(MCPModel):
    """prompts/list で返される、プロンプト1つ分の情報.

    Attributes:
        name (str): プロンプトの名前（今回は関数名）
        description (str | None): プロンプトの説明。省略可能。
        arguments (list[PromptArgument]): プロンプトの引数のリスト。
    """
    name: str
    description: str | None = None
    arguments: list[PromptArgument] = Field(default_factory=list)


class ListPromptsResult(MCPModel):
    """prompts/list の result部.

    Attributes:
        prompts (list[Prompt]): サーバーが提供するプロンプトのリスト
    """
    prompts: list[Prompt]


class GetPromptRequestParams(MCPModel):
    """prompts/get リクエストの param部.

    Attributes:
        name (str): プロンプトの名前（今回は関数名）
        arguments (dict[str, str] | None): プロンプトに渡す引数。省略可能。
    """
    name: str
    arguments: dict[str, str] | None = None


class PromptMessage(MCPModel):
    """プロンプトの中の1メッセージ分。text、image、audio、resourceなどがあるが、現状はtextのみ.

    Attributes:
        role (Literal["user", "assistant"]): メッセージの送信者
        content (ContentBlock): メッセージの中身。text、image、audio、resourceなどがあるが、textのみ.
    """
    role: Literal["user", "assistant"]
    content: ContentBlock


class GetPromptResult(MCPModel):
    """getPrompt リクエストから返す result部.

    Attributes:
        description (str | None): 完成したプロンプトの説明。省略可能。
        messages (list[PromptMessage]): プロンプトのメッセージのリスト。
    """
    description: str | None = None
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
    """サーバーが MCP / JSON-RPC の形式に合わないメッセージを送ってきた."""


class MCPError(MCPClientError):
    """サーバーが JSON-RPC のエラー応答を返した.

    このエラーはサーバーサイドが起因ではないケースで使う。(LLMが構文を間違えているなど)
    ネストされたエラーオブジェクトも含めてLLMに渡すことを推奨。

    Attributes:
        code (int): JSON-RPC のエラーコード
        message (str): JSON-RPC のエラーメッセージ
        data (Any): JSON-RPC のエラー詳細情報
    """

    def __init__(self, code: int, message: str, data: Any) -> None:
        """MCPErrorを初期化する."""
        super().__init__(code, message, data)
        self.code = code
        self.message = message
        self.data = data

    def __str__(self) -> str:
        """MCPErrorの文字列表現を返す.

        Returns:
            str: MCPErrorの文字列表現。"[code] message" の形式。
        """
        return f"[{self.code}] {self.message}"

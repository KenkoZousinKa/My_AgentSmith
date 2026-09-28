"""
todo

・try/exceptをクライアントの外部呼び出しメソッドに設ける。
・close()関数を読んでから、そのまま例外を返すならraiseのみ
・翻訳が必要なら以下のErrorオブジェクトにfrom eをつけて返す。
try:
    self.process.stdin.write(line)
    self.process.stdin.flush()
except BrokenPipeError as e:
    raise MCPConnectionError("サーバーとの接続が切れました") from e

try:
    result = client.call_tool("run_tests", {...})
except MCPConnectionError:
    ...  # サーバーを再起動するか、エージェントを止める
except MCPError as e:
    ...  # 「ツールの呼び出しに失敗: {e}」と LLM に伝える

・その場でスルーする場合。リクエスト中のnotificationはスルーするなど


・1つだけ、例外にしてはいけないもの

**`CallToolResult` の `is_error=True` は、例外にしません。**
これは「ツールは正常に呼べたが、ツールの処理が失敗した」（テストが落ちた、など）という**正常な応答**です。
クライアントはそのまま返し、どう扱うかはサンドボックスのラッパーが決めます。

| 状況 | クライアントの動き |
|---|---|
| サーバーが落ちた | `MCPConnectionError` を投げる |
| JSON-RPC のエラー応答（存在しないツール、引数の型が違う） | `MCPError` を投げる |
| `CallToolResult(is_error=True)`（テスト失敗など） | **例外にせず、そのまま返す** |

"""

from typing import Any


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

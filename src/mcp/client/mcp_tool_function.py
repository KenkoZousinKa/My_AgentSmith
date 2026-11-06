"""MCPツールをラッパーとして提供するクラス."""

from typing import Any

from src.mcp.models import mcpmodel as mcp
from src.mcp.client.client import MCPClient


class MCPToolFunction:
    """MCPのツール1つを、サンドボックスから普通の関数として呼べるようにする.

    Attributes:
        client (MCPClient): MCPクライアントのインスタンス
        name (str): ツールの名前
        description (str): ツールの説明
        input_schema (dict): ツールの入力スキーマ
    """

    def __init__(self, client: MCPClient, tool: mcp.Tool) -> None:
        """ツール情報をもとに初期化する.

        Args:
            client (MCPClient): MCPクライアントのインスタンス
            tool (mcp.Tool): ツールの情報
        """
        self.client = client
        self.name = tool.name
        self.description = tool.description
        self.input_schema = tool.input_schema

    def __call__(self, **arguments: Any) -> str:
        """このクラスを呼び出すと、対応するMCPツールを実行する.

        Args:
            **arguments: ツールに渡す引数
        Returns:
            str: ツールの実行結果のテキスト
        """
        result = self.client.call_tool(self.name, arguments)
        text = "\n".join(c.text for c in result.content)
        if result.is_error:
            raise RuntimeError(f"func: {self.name} ({text})")
        return text

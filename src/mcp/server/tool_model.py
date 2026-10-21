
from collections.abc import Callable
from typing import Any
from pydantic import BaseModel
from dataclasses import dataclass

from src.mcp.models import mcpmodel as mcp


@dataclass  # __init__を自動作成してくれる。データを入れておくだけのクラス
class RegisteredTool:
    """サーバーに登録されたツール1つ分の情報（サーバー内部用）."""
    name: str
    description: str | None
    func: Callable[..., Any]            # 実行する関数
    arguments_model: type[BaseModel]    # 引数の検証と inputSchema の生成に使うクラスそのもの

    def to_tool(self) -> mcp.Tool:
        """クライアントに送る形（mcp.Tool）に変換する."""
        return mcp.Tool(name=self.name,
                        description=self.description,
                        input_schema=self.arguments_model.model_json_schema())


@dataclass
class RegisteredResource:
    """サーバーに登録された資料1つ分の情報（サーバー内部用）."""
    uri: str
    name: str
    description: str | None
    mime_type: str
    func: Callable[[], Any]       # 引数なしで呼ぶと、資料の中身を返す関数

    def to_resource(self) -> mcp.Resource:
        """クライアントに送る形（mcp.Resource）に変換する."""
        return mcp.Resource(uri=self.uri, name=self.name,
                            description=self.description, mime_type=self.mime_type)


@dataclass
class RegisteredPrompt:
    """サーバーに登録された指示の雛形1つ分の情報（サーバー内部用）."""
    name: str
    description: str | None
    func: Callable[..., Any]                   # 引数を渡すと、埋めた指示を返す関数
    arguments: list[mcp.PromptArgument]        # 関数の引数から作った説明

    def to_prompt(self) -> mcp.Prompt:
        return mcp.Prompt(name=self.name, description=self.description, arguments=self.arguments)

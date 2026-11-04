"""サーバーに登録されるツール、資料、プロンプトの内部用モデル."""

from collections.abc import Callable
from typing import Any
from pydantic import BaseModel
from dataclasses import dataclass

from src.mcp.models import mcpmodel as mcp


@dataclass
class RegisteredTool:
    """serverクラスが保持するツールの情報.

    Attributes:
        name (str): ツールの名前
        description (str | None): ツールの説明
        func (Callable[..., Any]): ツールの関数自体
        arguments_model (type[BaseModel]): 引数の検証とinputSchemaの生成に使うクラス。
    """
    name: str
    description: str | None
    func: Callable[..., Any]
    arguments_model: type[BaseModel]

    def to_tool(self) -> mcp.Tool:
        """クライアントへ返すresultオブジェクトを作る."""
        return mcp.Tool(name=self.name,
                        description=self.description,
                        input_schema=self.arguments_model.model_json_schema())


@dataclass
class RegisteredResource:
    """serverクラスが保持する資料の情報.

    Attributes:
        uri (str): 資料の URI
        name (str): 資料の名前
        description (str | None): 資料の説明
        mime_type (str): 資料の MIME タイプ
        func (Callable[[], Any]): 資料の中身を返す関数
    """
    uri: str
    name: str
    description: str | None
    mime_type: str
    func: Callable[[], Any]

    def to_resource(self) -> mcp.Resource:
        """クライアントへ返すresultオブジェクトを作る."""
        return mcp.Resource(uri=self.uri, name=self.name,
                            description=self.description, mime_type=self.mime_type)


@dataclass
class RegisteredPrompt:
    """serverクラスが保持する指示の雛形の情報.

    Attributes:
        name (str): 指示の名前
        description (str | None): 指示の説明
        func (Callable[..., Any]): 引数を渡すと、埋めた指示を返す関数
        arguments (list[mcp.PromptArgument]): 関数の引数から作った説明
    """
    name: str
    description: str | None
    func: Callable[..., Any]                   # 引数を渡すと、埋めた指示を返す関数
    arguments: list[mcp.PromptArgument]        # 関数の引数から作った説明

    def to_prompt(self) -> mcp.Prompt:
        """クライアントへ返すresultオブジェクトを作る."""
        return mcp.Prompt(name=self.name, description=self.description, arguments=self.arguments)

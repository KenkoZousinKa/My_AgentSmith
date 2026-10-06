
from collections.abc import Callable
from typing import Any
from pydantic import BaseModel
from dataclasses import dataclass

from src.mcp_core.models import mcpmodel as mcp


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

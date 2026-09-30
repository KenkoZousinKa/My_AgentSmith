from typing import Callable, Any
from pydantic import BaseModel
from dataclasses import dataclass

from src.models import jsonrpc as rpc
from src.models import mcpmodel as mcp


@dataclass
class RegisteredTool:
    """サーバーに登録されたツール1つ分の情報（サーバー内部用）."""
    name: str
    description: str | None
    func: Callable[..., Any]            # 実行する関数
    arguments_model: type[BaseModel]    # 引数の検証と inputSchema の生成に使うモデル

    def to_tool(self) -> mcp.Tool:
        """クライアントに送る形（mcp.Tool）に変換する."""
        return mcp.Tool(name=self.name,
                        description=self.description,
                        input_schema=self.arguments_model.model_json_schema())

# def register(func: F) -> F:
#     name = func.__name__                                        # 1. 名前 = 関数名
#     doc = description or inspect.getdoc(func)                   # 2. 説明 = 引数で渡された説明、無ければ docstring

#     fields = {}                                                 # 3. 引数から検証用モデルを作る
#     for param_name, param in inspect.signature(func).parameters.items():
#         if param.annotation is inspect.Parameter.empty:
#             raise TypeError(f"{name} の引数 {param_name} に型ヒントがありません")
#         default = ... if param.default is inspect.Parameter.empty else param.default
#         fields[param_name] = (param.annotation, default)
#     arguments_model = create_model(f"{name}Arguments", **fields)

#     self.tools[name] = RegisteredTool(name, doc, func, arguments_model)   # 4. 登録簿に載せる
#     return func                                                           # 5. 関数はそのまま返す

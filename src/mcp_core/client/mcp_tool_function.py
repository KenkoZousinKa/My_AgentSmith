from typing import Any

from src.mcp_core.models import mcpmodel as mcp
from src.mcp_core.client.client import MCPClient


class MCPToolFunction:
    """MCP のツール1つを、サンドボックスから普通の関数として呼べるようにする."""

    def __init__(self, client: MCPClient, tool: mcp.Tool) -> None:
        self.client = client
        self.name = tool.name
        self.description = tool.description          # ← _tool_doc が読む
        self.input_schema = tool.input_schema        # ← _tool_doc が読む

    def __call__(self, **arguments: Any) -> str:     # ← _dispatch が呼ぶ
        result = self.client.call_tool(self.name, arguments)
        text = "\n".join(c.text for c in result.content)
        if result.is_error:
            raise RuntimeError(text)                 # ツールの失敗は例外にして、_dispatch に伝える
        return text

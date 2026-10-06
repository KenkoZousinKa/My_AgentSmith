"""自作クライアントから、公式 SDK（FastMCP）のサーバーを呼ぶ確認用スクリプト."""

from src.mcp_core.models import mcpmodel as mcp
from src.mcp_core.client.client import StdioMCPClient

with StdioMCPClient("python tests/sdk_fastmcp_server.py") as client:
    print("server_info :", client.server_info)
    print("capabilities:", client.server_capabilities)

    for tool in client.list_tools():
        print("tool        :", tool.name, tool.input_schema.get("required"))

    print("add         :", client.call_tool("add", {"a": 2, "b": 3}))
    print("fail        :", client.call_tool("fail", {}))

    try:
        print("nope        :", client.call_tool("nope", {}))
    except mcp.MCPError as e:
        print("nope        : MCPError", e)

    client.ping()
    print("ping        : OK")

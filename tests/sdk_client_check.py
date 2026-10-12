"""公式 SDK のクライアントから、自作の MCP サーバーを呼ぶ確認用スクリプト."""

import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    params = StdioServerParameters(command="python", args=["mcp_tools_mbpp.py"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("initialize :", init.serverInfo, init.capabilities.tools)

            tools = await session.list_tools()
            for t in tools.tools:
                print("tool       :", t.name, t.inputSchema.get("required"))

            result = await session.call_tool("run_tests", {"code": "def f(x): return x*2",
                                                           "test_list": ["assert f(2) == 4"]})
            print("call_tool  :", result.isError, result.content[0].text)


asyncio.run(main())

"""公式 SDK（FastMCP）で作った、確認用の MCP サーバー.

stdio:  uv run --with "mcp==1.26.0" python tests/sdk_fastmcp_server.py
HTTP:   uv run --with "mcp==1.26.0" python tests/sdk_fastmcp_server.py --http [ポート]
"""

import sys

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("sdk-test-server")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@mcp.tool()
def fail() -> str:
    """Always raises an error."""
    raise ValueError("this tool always fails")


if __name__ == "__main__":
    if "--http" in sys.argv:
        rest = sys.argv[sys.argv.index("--http") + 1:]
        mcp.settings.port = int(rest[0]) if rest else 8001
        mcp.run(transport="streamable-http")      # 待ち受けは 127.0.0.1、パスは /mcp
    else:
        mcp.run()

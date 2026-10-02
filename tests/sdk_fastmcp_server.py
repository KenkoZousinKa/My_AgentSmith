"""公式 SDK（FastMCP）で作った、確認用の MCP サーバー."""

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
    mcp.run()

"""サーバーのトランスポート層のプロトコル."""

from typing import Protocol, Callable

from src.mcp.models import jsonrpc as rpc


class ServerTransport(Protocol):
    """サーバーのトランスポート層のプロトコル."""

    def serve(self, handle: Callable[[str], rpc.JSONRPCResponse | rpc.JSONRPCError | None]) -> None:
        """クライアントからのリクエストを読み込んで、handlで作成したレスポンスを返す."""
        ...

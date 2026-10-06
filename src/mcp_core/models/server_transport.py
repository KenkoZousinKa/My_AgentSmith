from typing import Protocol, Callable

from src.mcp_core.models import jsonrpc as rpc


class ServerTransport(Protocol):
    def serve(self, handle: Callable[[str], rpc.JSONRPCResponse | rpc.JSONRPCError | None]) -> None: ...

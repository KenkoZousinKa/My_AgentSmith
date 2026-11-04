"""クライアントのトランスポート層のプロトコル."""

from typing import Protocol

from src.mcp.models import jsonrpc as rpc


class ClientTransport(Protocol):
    """クライアントのトランスポート層のプロトコル."""

    def open(self) -> None:
        """MCPサーバーと接続する."""
        ...

    def send(self, message: rpc.JSONRPCMessage) -> None:
        """MCPサーバーへJSON-RPCを送る."""
        ...

    def receive(self) -> rpc.JSONRPCMessage:
        """MCPサーバーからJSON-RPCを受け取る."""
        ...

    def set_protocol_version(self, version: str) -> None:
        """MCPサーバーのバージョンを記録する."""
        ...

    def close(self) -> None:
        """MCPサーバーとの接続を断つ."""
        ...

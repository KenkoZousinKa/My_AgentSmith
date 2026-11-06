"""Agent、Sandbox両方が従うSandboxのProtocol."""
from typing import Protocol
from src.models.output import ExecuteResult


class SandboxBase(Protocol):
    """Agent、Sandbox両方が従うSandboxのProtocolのクラス."""
    def run(self, code: str) -> ExecuteResult:
        """Check then execute. Never raises for errors inside the snippet."""
        ...

    def manual(self) -> str:
        """接続中MCPサーバーのツールスキーマから動的生成した、LLM向けツールマニュアル."""
        ...

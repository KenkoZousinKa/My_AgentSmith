from typing import Protocol
from src.models.output import ExecuteResult


class SandboxBase(Protocol):
    def run(self, code: str) -> ExecuteResult:
        """Check then execute. Never raises for errors inside the snippet."""
        ...

    def manual(self) -> str:
        """接続中MCPサーバーのツールスキーマから動的生成した、LLM向けツールマニュアル。"""
        ...

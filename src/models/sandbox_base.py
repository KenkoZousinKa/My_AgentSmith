from pydantic import BaseModel
from typing import Protocol


class ExecutionResult(BaseModel):
    stdout: str
    stderr: str
    exception: str | None  # 実行中に送出された例外の文字列（無ければ None）
    timed_out: bool  # サンドボックスのtimeoutで打ち切られたか
    truncated: bool  # 出力がサイズ制限で切り詰められたか
    final_answer_called: bool  # final_answer() が呼ばれたか
    final_value: str | None  # 呼ばれた場合の引数（MBPP=コード, SWE=patch）


class SandboxBase(Protocol):
    def run(self, code: str) -> ExecutionResult:
        """Check then execute. Never raises for errors inside the snippet."""
        ...

    def manual(self) -> str:
        """接続中MCPサーバーのツールスキーマから動的生成した、LLM向けツールマニュアル。"""
        ...

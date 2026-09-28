from pydantic import BaseModel
from typing import Protocol


class ExecuteResult(BaseModel):
    """Outcome of one part.

    Its either pass error or standard code compile.
    """
    stdout: str = ""  # same
    stderr: str = ""  # same
    value: str | None = None  # same / final_value
    error: str | None = None  # -> exception, timed_out, truncated
    final_answer: str | None = None  # -> final_answer_called, final_value


class Sandbox_Base(Protocol):
    def run(self, code: str) -> ExecuteResult:
        """Check then execute. Never raises for errors inside the snippet."""
        ...

    # def manual(self) -> str:
        # """接続中MCPサーバーのツールスキーマから動的生成した、LLM向けツールマニュアル。"""
        # ...

    # def execute(self, code: str) -> ExecutionResult:
        # """コード文字列を実行し結果を返す。名前空間にはMCPツール群 + final_answer が注入済み。"""
# class ExecutionResult(BaseModel):
    # stdout: str
    # stderr: str
    # exception: str | None  # 実行中に送出された例外の文字列（無ければ None）
    # timed_out: bool  # サンドボックスのtimeoutで打ち切られたか
    # truncated: bool  # 出力がサイズ制限で切り詰められたか
    # final_answer_called: bool  # final_answer() が呼ばれたか
    # final_value: str | None  # 呼ばれた場合の引数（MBPP=コード, SWE=patch）

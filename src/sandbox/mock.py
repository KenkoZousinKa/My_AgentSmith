"""Agent開発用のサンドボックスのモックを提供するモジュール.

本物のサンドボックス前に、Orchestratorの縦通しを回すための最小実装。
SandboxBase契約(run / manual)を満たし、コードを永続名前空間でexecして
stdout / stderr / 例外を捕捉し、final_answer() の呼び出しを ExecuteResult に反映する。
import / FS / timeout / memory の制限は本物のサンドボックスの責務なのでモックでは課さない(縦通し用の素通し実行)。
状態は1タスク=1インスタンスで保持し、run()間で変数 / import / 定義が永続する。
"""
import io
import traceback
import contextlib
from typing import Any

from src.models.sandbox_base import ExecuteResult


class _FinalAnswerSignal(Exception):
    """final_answer() が呼ばれたことを run() へ伝えるための内部シグナル例外."""

    def __init__(self, value: str) -> None:
        """提出値を保持して送出する.

        Args:
            value (str): final_answer に渡された文字列化済みの提出値。
        """
        super().__init__("final_answer called")
        self.value = value


class MockSandbox:
    """開発用の素通しサンドボックス。exec で実行し final_answer を捕捉する(SandboxBase準拠)."""

    def __init__(self) -> None:
        """1タスク分の永続名前空間を用意し、final_answer を注入する."""
        self._namespace: dict[str, Any] = {"final_answer": self._final_answer}

    @staticmethod
    def _final_answer(value: Any = "") -> None:
        """名前空間に注入する final_answer。値を文字列化しシグナルで実行を止める.

        Args:
            value (Any): 提出する最終回答(MBPPは関数ソース文字列)。

        Raises:
            _FinalAnswerSignal: 常に送出して現在のコード実行を終了させる。
        """
        raise _FinalAnswerSignal("" if value is None else str(value))

    def run(self, code: str) -> ExecuteResult:
        """コードを永続名前空間で実行し、結果を ExecuteResult にまとめて返す(例外は投げない).

        Args:
            code (str): 実行する Python コード(抽出済み)。

        Returns:
            ExecuteResult: stdout / stderr / error / final_answer_* を埋めた結果。
        """
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        error: str | None = None
        final_answer_called = False
        final_answer_value: str | None = None
        try:
            with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                exec(code, self._namespace)
        except _FinalAnswerSignal as signal:
            final_answer_called = True
            final_answer_value = signal.value
        except Exception:  # LLM生成コードの実行時例外は観測に載せる。run自体は決して投げない(契約)
            error = traceback.format_exc()
        return ExecuteResult(
            stdout=stdout_buffer.getvalue(),
            stderr=stderr_buffer.getvalue(),
            error=error,
            value=None,
            timeout=False,
            truncated=False,
            final_answer_bool=final_answer_called,
            final_answer=final_answer_value,
        )

    def manual(self) -> str:
        """このサンドボックスで使えるツールの簡潔なマニュアルを返す(SandboxBase準拠)."""
        return (
            "Available tools (call them inside a ```python``` block):\n"
            "- print(*args): write to stdout; only what you print is returned in the Observation.\n"
            "- final_answer(answer): submit your final solution (as a string) and end the task.\n"
            "You may import Python standard-library modules (e.g. `import math`) as needed."
        )

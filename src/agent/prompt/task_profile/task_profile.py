"""TaskProfileのベースクラスを定義するモジュール.

- [x] models/以下に移動可能性あり。
- [ ] MBPPProfile, SWEBenchProfileが継承、他にタスクを増やしたい時用。
- [ ] few-shotを1例、各プロファイルごとに定義する。
- [ ] manualはname(args) -> ret: + 1行説明。非自明のものは小例をつける。
    - [ ] sandbox.manual()から動的差し込みし、実際のツール数に合わせる。
"""
from abc import ABC, abstractmethod

from src.models.sandbox_base import SandboxBase


class TaskProfile(ABC):
    """タスクのプロファイルを定義するクラス."""

    @abstractmethod
    def task_instructions(self, task_name: str) -> str:
        """タスクの指示を取得する.

        Args:
            task_name (str): タスク名(mbpp / swebench)

        Returns:
            str: タスクの指示
        """

    @abstractmethod
    def final_answer_specification(self) -> str:
        """最終的な回答の仕様を取得する.

        Returns:
            str: 最終的な回答の仕様
        """

    @abstractmethod
    def few_shot_examples(self) -> list:
        """Few-shotの例を取得する.

        Returns:
            list: Few-shotの例
        """

    @abstractmethod
    def manual(self, sandbox: SandboxBase) -> str:
        """接続中MCPサーバーのツールスキーマから動的生成した、LLM向けツールマニュアルを取得する.

        Args:
            sandbox (SandboxBase): サンドボックスのインスタンス

        Returns:
            str: LLM向けツールマニュアル
        """

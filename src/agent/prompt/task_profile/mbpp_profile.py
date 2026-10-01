"""MBPPのタスクプロファイルを定義するモジュール."""
from src.models.sandbox_base import SandboxBase
from src.agent.prompt.task_profile.task_profile import TaskProfile


class MBPPProfile(TaskProfile):
    """MBPPのタスクプロファイルを定義するクラス."""

    def task_instructions(self, task_name: str) -> str:
        """MBPPのタスクの指示を取得する.

        Args:
            task_name (str): タスク名(mbpp)

        Returns:
            str: タスクの指示
        """
        return "Please solve the following MBPP task."

    def final_answer_specification(self) -> str:
        """最終的な回答の仕様を取得する.

        Returns:
            str: 最終的な回答の仕様
        """
        return "The final answer should be a valid Python code snippet."

    def few_shot_examples(self) -> list:
        """Few-shotの例を取得する.

        Returns:
            list: Few-shotの例
        """
        return [
            {
                "input": "Write a function to add two numbers.",
                "output": "def add(a, b):\n    return a + b"
            },
            {
                "input": "Write a function to check if a number is prime.",
                "output": "def is_prime(n):\n    if n <= 1:\n        return False\n    "
                "for i in range(2, int(n**0.5) + 1):\n        if n % i == 0:\n            return False\n    return True"
            }
        ]

    def manual(self, sandbox: SandboxBase) -> str:
        """接続中MCPサーバーのツールスキーマから動的生成した、LLM向けツールマニュアルを取得する.

        Args:
            sandbox (SandboxBase): サンドボックスのインスタンス

        Returns:
            str: LLM向けツールマニュアル
        """
        # サンドボックスからツールスキーマを取得し、マニュアルを生成するロジックを実装する
        return "Tool manual for MBPP tasks."

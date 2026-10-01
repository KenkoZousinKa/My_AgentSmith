"""SWEBenchのタスクプロファイルを定義するモジュール."""
from src.models.sandbox_base import SandboxBase
from src.agent.prompt.task_profile.task_profile import TaskProfile


class SWEBenchProfile(TaskProfile):
    """SWEBenchのタスクプロファイルを定義するクラス."""

    def task_instructions(self, task_name: str) -> str:
        """SWEBenchのタスクの指示を取得する.

        Args:
            task_name (str): タスク名(swebench)

        Returns:
            str: タスクの指示
        """
        return "Please solve the following SWEBench task."

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
                "input": "Write a function to reverse a string.",
                "output": "def reverse_string(s):\n    return s[::-1]"
            },
            {
                "input": "Write a function to find the maximum number in a list.",
                "output": "def find_max(lst):\n    return max(lst)"
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
        return "Tool manual for SWEBench tasks."

"""MBPPタスク用のTaskProfileを定義するモジュール."""
from src.agent.prompt.task_profile.task_profile import TaskProfile
from src.models.sandbox_base import SandboxBase


class MBPPProfile(TaskProfile):
    """MBPP(単一の関数の実装課題)用のTaskProfileを定義するクラス."""
    name = "mbpp"
    _MBPP_FEW_SHOT_EXAMPLE = """Thought: I'll write the function, then quickly check it with print.
    ```python
    def add(a, b):
        return a + b

    print(add(2, 3))
    ```
    <end_code>
    Observation:
    [OK] Executed successfully.
    --- stdout ---
    5
    Thought: The output is correct, so I'll submit the function source.
    ```python
    final_answer("def add(a, b):\\n    return a + b")
    ```
    <end_code>
    """

    def task_instructions(self) -> str:
        """MBPPタスクの進め方を返す.

        Returns:
            str: タスクの指示
        """
        return (
            "This is an MBPP task: inplement a single Python function theat satisfies the "
            "behavior described in the next user message. Write the function, test it by "
            "calling it inside print(...), and iterate until it is correct."
            "Then submit the function's source code with final_answer."
        )

    def final_answer_specification(self) -> str:
        """final_answer()に何を渡すべきか、最終的な回答の仕方を返す.

        Returns:
            str: 最終的な回答の仕様
        """
        return (
            "Pass the full source code of your solution function to final_answer as a string, "
            'e.g. final_answer("def solve(n):\\n    return n * 2").'
        )

    def few_shot_example(self) -> str:
        """出力形式を教えるためのFew-shotの例を返す.

        Thought -> Code -> Observation -> final_answer
        実タスクとは無関係な例。形式を示すためだけの固定のテキスト。

        Returns:
            str: Few-shotの例
        """
        return self._MBPP_FEW_SHOT_EXAMPLE

    def manual(self, sandbox: SandboxBase) -> str:
        """接続中MCPサーバーのツールスキーマから動的生成した、LLM向けツールマニュアルを返す.

        このタスクで使えるツール / 環境の説明を返す。
        ツールはハードコードせずに、sandbox.manual()から動的に取得する。

        Args:
            sandbox (SandboxBase): サンドボックスのインスタンス

        Returns:
            str: LLM向けツールマニュアル
        """
        return sandbox.manual()

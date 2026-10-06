"""SWEBenchタスク用のTaskProfileを定義するモジュール."""
from src.agent.prompt.task_profile.task_profile import TaskProfile
from src.models.sandbox_base import SandboxBase


class SWEBenchProfile(TaskProfile):
    """SWEBench(gitリポジトリのバグ修正)用のTaskProfileを定義するクラス."""
    name = "swebench"
    _SWEBENCH_FEW_SHOT_EXAMPLE = '''Thought: First I'll inspect the failing file to understand the bug.
    ```python
    print(read_file("calc/ops.py"))
    ```
    <end_code>
    Observation:
    [OK] Executed successfully.
    --- stdout ---
    def divide(a, b):
        return a * b
    Thought: divide uses '*' instead of '/'. I'll submit a patch that fixes it.
    ```python
    final_answer("""--- a/calc/ops.py
    +++ b/calc/ops.py
    @@ -1,2 +1,2 @@
     def divide(a, b):
    -    return a * b
    +    return a / b
    """)
    ```
    <end_code>'''

    def task_instructions(self) -> str:
        """SWEタスクの進め方を返す.

        Returns:
            str: タスクの指示
        """
        return (
            "This is a SWE-bench task: you are inside a git repository with a failing issue "
            "described in the next user message. Use the available tools to explore the code, "
            "locate and fix the bug, and verify it. Then submit your fix as a unified diff "
            "patch with final_answer."
        )

    def final_answer_specification(self) -> str:
        """final_answer()に何を渡すべきか、最終的な回答の仕方を返す.

        Returns:
            str: 最終的な回答の仕様
        """
        return (
            "Pass a unified diff (git patch) to final_answer as a string, including the "
            "'--- a/<path>' and '+++ b/<path>' headers and the @@ hunks (as produced by git diff)."
        )

    def few_shot_example(self) -> str:
        """出力形式を教えるためのFew-shotの例を返す.

        Thought -> Code -> Observation -> final_answer
        実タスクとは無関係な例。形式を示すためだけの固定のテキスト。

        Returns:
            str: Few-shotの例
        """
        return self._SWEBENCH_FEW_SHOT_EXAMPLE

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

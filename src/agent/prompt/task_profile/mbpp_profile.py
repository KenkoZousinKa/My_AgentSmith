"""MBPPタスク用のTaskProfileを定義するモジュール.

MBPPの提出は関数のソースコード。
採点側は提出物に隠しテストを連結して実行するため、その形で例外を投げないコードだけ受理する。

下記を提供
- strip_code_fences()
    提出物の前後の空白とmarkdownのコードフェンスを取り除く。
- mbpp_rejection()
    提出物を受理できるか検査し、ダメなら理由を返す。
- MBPPProfile()
    MBPP用のTaskProfile
"""
import ast

from src.agent.prompt.task_profile.task_profile import TaskProfile
from src.models.sandbox_base import SandboxBase

# 環境に依存しないサンドボックス専用の関数名。参照するコードを提出するとNameErrorになる。
_SANDBOX_ONLY_NAMES = frozenset({"run_tests", "final_answer"})

# トップレベルに置いても採点で例外を投げない文。
# これ以外の文は、提出物に含まれると採点で例外を投げる可能性がある。
_ALLOWED_TOP_LEVEL = (
    ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign
)


def strip_code_fences(raw: str) -> str:
    """提出物の前後の空白とmarkdownのコードフェンスを取り除く.

    LLMが出力した```python ...```で囲んだコードを、連結して実行するために前後の空白とコードフェンスを取り除く。

    Args:
        raw (str): 提出物の文字列。

    Returns:
        str: 前後の空白とコードフェンスを取り除いた文字列。
    """
    # 前後の空白を取り除く
    text = raw.strip()
    # markdownのコードフェンスを取り除く
    if text.startswith("```"):
        # 先頭のコードフェンスを取り除く
        lines = text.splitlines()[1:]
        # 末尾のコードフェンスを取り除く
        while lines and lines[-1].strip().startswith("```"):
            lines.pop()

        # コードフェンスを取り除いた後の文字列を再構築する
        text = "\n".join(lines).strip()

    return text


def mbpp_rejection(solution: str) -> str | None:
    """MBPPの提出物を受理できるか検査し、ダメなら理由を返す.

    構文が通りかつ下記を満たす場合に受理する。
    - サンドボックス専用の関数名を参照していないこと。
    - トップレベルに関数定義があること。
    - トップレベルに例外を投げる文がないこと。

    Args:
        solution (str): 提出物の文字列。

    Returns:
        str | None: 受理できない場合は理由の文字列。受理できる場合はNone。
    """
    if not solution:
        return "final_answer() received an empty input."

    try:
        tree = ast.parse(solution)
    except SyntaxError as error:
        return f"The submission code is not valid Python ({error.msg} on line {error.lineno})."

    # サンドボックス専用の名前を先に調べる。
    # 検証用コードをそのまま提出すると関数定義が無いが先に検出されるので、先にチェックしLLMに伝えるため。
    referenced_names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    blocked_names = sorted(referenced_names & _SANDBOX_ONLY_NAMES)
    if blocked_names:
        return (
            f"The submitted code calls {', '.join(blocked_names)}, which exist only inside this sandbox. "
            "Submit just the function source, with no test harness around it."
        )

    if not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in tree.body):
        return "The submitted code contains no function definition."

    for node in tree.body:
        # トップレベルに例外を投げる文がないか検査する
        if isinstance(node, _ALLOWED_TOP_LEVEL):
            continue
        # トップレベルの文字列リテラルはdocstringなので許可する
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        return (
            f"The submitted code has a top-level {type(node).__name__} statement. Submit only "
            "imports and the function definition(s): the grader appends its own tests to your "
            "code and runs the whole file, so any extra statement that raises fails it."
        )

    return None


_MBPP_FEW_SHOT_EXAMPLE = '''
Thought: Implement the function, verify it with the given tests, submit if they pass.
```python
solution = """def add(a, b):
    return a + b
"""
import json
report = json.loads(run_tests(code=solution, test_list=['assert add(2, 3) == 5']))
print(report)
if report['success']:
    final_answer(solution)
```
<end_code>
Observation:
[OK] Executed successfully.
--- stdout ---
{'success': True, 'message': 'passed', 'output': ''}
'''


class MBPPProfile(TaskProfile):
    """MBPP(単一の関数の実装課題)用のTaskProfileを定義するクラス."""
    name = "mbpp"

    def sanitize_submission(self, raw: str) -> str:
        """提出物の前後の空白とmarkdownのコードフェンスを取り除く.

        Args:
            raw (str): LLMが出力した提出物。

        Returns:
            str: 前後の空白とコードフェンスを取り除いた提出物。
        """
        return strip_code_fences(raw)

    def submission_rejection(self, candidate: str) -> str | None:
        """採点側の実行方式で例外を投げない関数のソースか検査する。

        Args:
            candidate (str): 提出物の文字列。

        Returns:
            str | None: 受理できない場合は理由の文字列。受理できる場合はNone。
        """
        return mbpp_rejection(candidate)

    def is_fallback_candidate(self, code: str) -> bool:
        """そのまま提出できる形のコードかを返す。

        Args:
            code (str): 今の反復で実行したコード、または差し戻した提出物。

        Returns:
            bool: 打ち切り時に提出候補として残す場合はTrue。
        """
        return mbpp_rejection(code) is None

    def task_instructions(self) -> str:
        """MBPPタスクの進め方を返す.

        Returns:
            str: タスクの指示
        """
        return (
            "MBPP: implement ONE function with the exact name and signature given by the task.\n"
            "- Build its source as a triple-quoted string, verify it with "
            "run_tests(code=..., test_list=[...]) using the task's asserts, and when it passes call "
            "final_answer(<that string>) in the SAME block.\n"
            "- The submitted string must contain ONLY imports and the function(s). No prints, "
            "asserts or demo calls: the grader appends its own tests to your code and runs it, so "
            "any extra statement that raises fails the submission.\n"
            "- HIDDEN TESTS: you see only part of the suite. Write a general, correct "
            "implementation; never hardcode the shown values. Infer the intended rule from ALL the "
            "given examples (they often encode a convention the wording leaves out).\n"
            "- Gate final_answer on the task's own asserts only. Do not add asserts you invented: "
            "if they are wrong they block a correct submission. To explore edge cases, print values.\n"
            "- If run_tests fails, print what your function returns for the failing assert's input, "
            "compare it with the expected value, fix the rule, retry.\n"
            "- When the expected outputs follow a numeric or bit pattern you cannot see at once, "
            "compute it in code from the given examples (differences, ratios, binary forms) and "
            "print it, instead of guessing a formula."
        )

    def final_answer_specification(self) -> str:
        """final_answer()に何を渡すべきか、最終的な回答の仕方を返す.

        Returns:
            str: 最終的な回答の仕様
        """
        return (
            "Pass the function's full source code as a string, e.g. final_answer(solution) where "
            'solution = """def solve(n):\n    return n * 2\n""". '
            "Never pass a computed value, a function object, or markdown fences."
        )

    def few_shot_example(self) -> str:
        """出力形式を教えるためのFew-shotの例を返す.

        Thought -> Code -> Observation -> final_answer
        実タスクとは無関係な例。形式を示すためだけの固定のテキスト。

        Returns:
            str: Few-shotの例
        """
        return _MBPP_FEW_SHOT_EXAMPLE

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

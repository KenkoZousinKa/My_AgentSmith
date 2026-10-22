"""SWE-benchタスク用のTaskProfileを定義するモジュール.

SWE-benchの提出物はgitのパッチ(unified diff)形式。
リポジトリはDockerコンテナ内にあり、
AgentはMCPのツール(search_code / read_file / edit_file / run_tests / get_patch など)で外から操作する。
パッチは手書きさせずに、get_patch()の戻り値をそのまま提出させる。
-> final_answer(get_patch())

下記を提供
- SWEBenchProfile()
"""
from src.agent.prompt.task_profile.task_profile import TaskProfile
from src.models.sandbox_base import SandboxBase

# パッチらしさの判定に使う目印文字列。どれかが含まれていればパッチとみなす。
_PATCH_MARKERS = ("diff --git", "--- a/", "+++ b/", "@@")

# サンドボックスがツールの戻り値を切り詰めた時につける目印文字列(sandbox_helper.py _truncate)。
# 切り詰められたパッチは途中で切れている、かつ目印の文が混ざるためgit applyできない。
_TRUNCATED_MARKER = "[output truncated:"

# 打ち切り時に編集済みの変更をパッチとして回収し提出するためにサンドボックスで実行するコード。
# print()の出力はサイズ上限で切り詰められるのでfinal_answerで値ごと受け取る。
_COLLECT_PATCH_CODE = "final_answer(get_patch())"

_SWEBENCH_FORMAT_RULES = """- Start with a short Thought (at most 3 lines: what you learned, what you do next), then exactly
  ONE block fenced as ```python ... ```, then <end_code>.
- Tools are plain Python functions that RETURN strings: print() what you need to see, e.g.
  print(search_code(pattern="def foo", file_pattern="*.py")). Only printed output comes back.
- The tools and final_answer are already defined globals: call them directly, never import them.
- Print only the relevant part of large results (slice long strings, read files by line ranges).
- The namespace persists between turns: keep results in variables instead of re-running tools.
- Limits on iterations, tokens and time are strict: one focused step per turn."""

_SWEBENCH_FEW_SHOT_EXAMPLE = '''Thought: Find where the failing function is defined.
```python
print(search_function_or_class_definition_in_code(name="divide"))
```
<end_code>
Observation:
[OK] Executed successfully.
--- stdout ---
/testbed/calc/ops.py:10 def divide(a, b):
Thought: Read the function body.
```python
print(read_file(filepath="/testbed/calc/ops.py", start_line=8, end_line=14))
```
<end_code>
Observation:
[OK] Executed successfully.
--- stdout ---
10: def divide(a, b):
11:     return a * b
Thought: It multiplies instead of dividing. Fix it, run the evaluation tests, and look at the patch.
```python
print(edit_file(filepath="/testbed/calc/ops.py", old_str="    return a * b", new_str="    return a / b"))
print(run_tests()[-1500:])
patch = get_patch()
print(patch)
```
<end_code>
Observation:
[OK] Executed successfully.
--- stdout ---
Edited /testbed/calc/ops.py (replaced 1 occurrence starting at line 11).
calc/tests/test_ops.py::test_divide PASSED
diff --git a/calc/ops.py b/calc/ops.py
...
Thought: The tests pass and the patch is correct. Submit it.
```python
final_answer(patch)
```
<end_code>'''


class SWEBenchProfile(TaskProfile):
    """SWEBench(実在のgitリポジトリのバグ(issue)修正)用のTaskProfileを定義するクラス."""
    name = "swebench"
    history_window_size: int = 6
    observation_max_chars: int = 3000
    latest_observation_max_chars: int = 8000
    assistant_max_chars: int = 2000

    def sanitize_submission(self, raw: str) -> str:
        """提出物のパッチをgit applyできる形に整形する.

        前後の空行とコードフェンスを落とし、末尾の改行を保証する。
        末尾の改行がないパッチはgit applyでcorrupt patchエラーになる。
        行頭の空白(diffの文脈行の目印)を落とすと別のパッチになる。

        Args:
            raw (str): LLMがfinal_answerで出力した提出物。

        Returns:
            str: 整形済みのパッチ。中身がなければ空文字列。
        """
        # 前後の改行を落とす。
        text = raw.strip("\n")

        # markdownのコードフェンスを取り除く。
        # フェンスで囲まれている時だけフェンスの行ごと落とす。フェンスがない時はtextの行頭の空白は落とさない。
        if text.lstrip().startswith("```"):
            # ```diffなどの先頭の開きフェンスの行を取り除く。
            lines = text.splitlines()[1:]
            # ```などの閉じフェンスの行を取り除く。
            while lines and lines[-1].strip().startswith("```"):
                lines.pop()

            # コードフェンスを取り除いた後の文字列を再構築する。
            text = "\n".join(lines)

        # このあと末尾の改行を保証するため、空文字列の時はこの時点で返す。
        if not text.strip():
            return ""

        return text if text.endswith("\n") else text + "\n"

    def submission_rejection(self, candidate: str) -> str | None:
        """提出物がgit applyできるパッチか検査し、ダメならLLMへ返す理由を返す.

        Args:
            candidate (str): sanitize_submission()で整形済みの提出物。

        Returns:
            str | None: 受理できない場合は理由の文字列。受理できる場合はNone。
        """
        # 空の提出物はfinal_answer()の呼び出し忘れの可能性があるのでrejectする。
        if not candidate.strip():
            return (
                "final_answer() received an empty patch: get_patch() returns nothing until you "
                "edit a file with edit_file."
            )

        # パッチが途中で切れている場合はgit applyできないのでrejectする。
        if _TRUNCATED_MARKER in candidate:
            return (
                "The patch was cut off by the sandbox's output size limit, so it cannot be applied. "
                "Keep the change minimal: revert unrelated edits and touch only the lines needed for the fix."
            )

        # パッチらしさの目印文字列が含まれていない場合はrejectする。
        # どれか1つでも含まれていればgit applyできる可能性があるので受理する。
        if not any(marker in candidate for marker in _PATCH_MARKERS):
            return (
                "The submission is not a git diff: pass the value returned by get_patch()."
            )

        return None

    def fallback_solution(self, sandbox: SandboxBase) -> str:
        """提出がないまま打ち切り時にコンテナ内の編集済みの変更をパッチとして回収する.

        修正が途中でも空の提出物より採点で通る可能性があるため。
        print()経由だと切り詰めの可能性があるためget_patch()の値はfinal_answer()経由で受け取る。

        Args:
            sandbox (SandboxBase): サンドボックスのインスタンス

        Returns:
            str: 打ち切り時に提出するパッチ。中身がなければ空文字列。
        """
        result = sandbox.run(_COLLECT_PATCH_CODE)
        # final_answer()が呼ばれなかった場合は空文字列を返す。
        if not result.final_answer_bool or not result.final_answer:
            return ""

        # sanitize_submission()で整形して、submission_rejection()でrejectされる場合は空文字列を返す。
        patch = self.sanitize_submission(result.final_answer)
        return patch if self.submission_rejection(patch) is None else ""

    def task_instructions(self) -> str:
        """SWEタスクの進め方を返す.

        Returns:
            str: タスクの指示
        """
        return (
            "SWE-bench: fix the GitHub issue given in the next message in the repository checked out "
            "at /testbed (inside a container you reach ONLY through the tools above).\n"
            "1. Locate: search_function_or_class_definition_in_code / search_code / list_files.\n"
            "2. Understand: read_file with start_line/end_line around the relevant code. Optionally "
            "reproduce the bug. Put the script in a triple-quoted string and pass it to python through "
            "a quoted heredoc, so that no quote needs escaping (python -c \"...\" with nested quotes "
            "breaks easily):\n"
            "print(run_command(command=\"\"\"cd /testbed && python - <<'EOF'\n"
            "from pkg.module import func\n"
            "print(func(0))\n"
            "EOF\"\"\"))\n"
            "3. Fix: edit_file(filepath=..., old_str=..., new_str=...) with a MINIMAL change in the "
            "library source. old_str must match the file exactly (copy indentation from read_file "
            "output, without the 'N: ' prefixes). A reply starting with 'Error:' means nothing was changed.\n"
            "4. Verify: run_tests() runs the official evaluation script (it adds the hidden tests). "
            "Read the failing test names and fix until they pass.\n"
            "5. Submit: patch = get_patch(); if patch: final_answer(patch).\n"
            "Rules: never edit or add test files; do not try to fetch fixes from the internet, pull "
            "requests or issues; base every change on the code you read in this repository."
        )
        # 181行目、`cd /testbed && python - <<'EOF'` はbash -c ではなくbash -lcで実行する前提。

    def final_answer_specification(self) -> str:
        """final_answer()に何を渡すべきか、最終的な回答の仕方を返す.

        Returns:
            str: 最終的な回答の仕様
        """
        return (
            "Pass the git diff returned by get_patch(): final_answer(get_patch()). Never write a "
            "diff by hand, and do not submit before your edit is in place."
        )

    def few_shot_example(self) -> str:
        """出力形式を教えるためのFew-shotの例を返す.

        Thought -> Code -> Observation -> final_answer
        実タスクとは無関係な例。形式を示すためだけの固定のテキスト。

        Returns:
            str: Few-shotの例
        """
        return _SWEBENCH_FEW_SHOT_EXAMPLE

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

    def format_rules(self) -> str:
        """SWE-bench用の出力形式のルールを返す.

        - ツールが文字列を返すこと(print()で出力すること)。
        - ツールをimportしないこと
        - 名前空間が反復をまたいで残ることをMBPPの既定ルールに足して伝える。

        Returns:
            str: 出力形式のルール
        """
        return _SWEBENCH_FORMAT_RULES

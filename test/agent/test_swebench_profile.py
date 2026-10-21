"""SWEBenchProfile(swebench_profile.py)の提出物の整形・検査・回収とプロンプトのテスト(A-22)."""
import re

import pytest

from mcp_tools_swebench import server as swebench_server
from src.agent.extractor.python_extractor import PythonCodeExtractor
from src.agent.orchestrator import Orchestrator
from src.agent.prompt.task_profile.swebench_profile import SWEBenchProfile
from src.config.settings import Limits
from src.models.output import ExecuteResult
from src.sandbox.mock import MockSandbox
from test.agent.test_orchestrator import StubProvider

_PATCH = (
    "diff --git a/calc/ops.py b/calc/ops.py\n"
    "--- a/calc/ops.py\n"
    "+++ b/calc/ops.py\n"
    "@@ -10,2 +10,2 @@\n"
    " def divide(a, b):\n"
    "-    return a * b\n"
    "+    return a / b\n"
)


class _PatchSandbox:
    """sandbox.run()に渡されたコードを記録し、決まった結果を返すサンドボックス."""

    def __init__(self, result: ExecuteResult) -> None:
        self.result = result
        self.codes: list[str] = []

    def run(self, code: str) -> ExecuteResult:
        """渡されたコードを記録し、決まった結果を返す."""
        self.codes.append(code)
        return self.result

    def manual(self) -> str:
        """空のマニュアルを返す."""
        return ""


# ---- sanitize_submission ----

def test_sanitize_keeps_the_patch_and_adds_the_trailing_newline() -> None:
    """末尾の改行が無いパッチには改行を足す(無いと git apply が corrupt patch で失敗する)."""
    assert SWEBenchProfile().sanitize_submission(_PATCH.rstrip("\n")) == _PATCH


def test_sanitize_keeps_a_patch_that_is_already_well_formed() -> None:
    """整ったパッチは1文字も変えない."""
    assert SWEBenchProfile().sanitize_submission(_PATCH) == _PATCH


def test_sanitize_keeps_the_leading_space_of_context_lines() -> None:
    """文脈行の先頭の空白と、空行の文脈行(半角空白1つだけの行)を落とさない(既定の strip() との違い)."""
    patch_ending_with_blank_context = _PATCH + " \n"
    sanitized = SWEBenchProfile().sanitize_submission("\n\n" + patch_ending_with_blank_context + "\n\n")
    assert sanitized == patch_ending_with_blank_context
    assert "\n def divide(a, b):\n" in sanitized


@pytest.mark.parametrize("fence", ["```diff", "```", "```patch"])
def test_sanitize_removes_code_fences(fence: str) -> None:
    """コードフェンスで囲まれた提出からフェンスを落とす."""
    assert SWEBenchProfile().sanitize_submission(f"{fence}\n{_PATCH}```") == _PATCH


@pytest.mark.parametrize("raw", ["", "\n\n", "   ", "```diff\n```"])
def test_sanitize_returns_empty_for_blank_submissions(raw: str) -> None:
    """中身の無い提出は空文字にする(差し戻しの判定に回す)."""
    assert SWEBenchProfile().sanitize_submission(raw) == ""


# ---- submission_rejection ----

def test_accepts_a_git_diff() -> None:
    """git の diff は受理する."""
    assert SWEBenchProfile().submission_rejection(_PATCH) is None


@pytest.mark.parametrize(("candidate", "reason_part"), [
    ("", "empty patch"),
    ("I fixed the divide function.\n", "not a git diff"),
    ("def divide(a, b):\n    return a / b\n", "not a git diff"),
    (_PATCH + "[output truncated: 120 of 8120 characters omitted; narrow your request to see the rest]\n",
     "cut off"),
])
def test_rejects_what_git_apply_cannot_use(candidate: str, reason_part: str) -> None:
    """空・diff でない・サンドボックスに切り詰められた提出を、理由つきで差し戻す."""
    reason = SWEBenchProfile().submission_rejection(candidate)
    assert reason is not None
    assert reason_part in reason


# ---- fallback_solution ----

def test_fallback_collects_the_patch_through_final_answer() -> None:
    """打ち切り時は final_answer(get_patch()) を実行し、値ごと受け取ったパッチを整えて返す."""
    sandbox = _PatchSandbox(ExecuteResult(final_answer_bool=True, final_answer=_PATCH.rstrip("\n")))
    assert SWEBenchProfile().fallback_solution(sandbox) == _PATCH
    assert sandbox.codes == ["final_answer(get_patch())"]


@pytest.mark.parametrize("result", [
    ExecuteResult(final_answer_bool=True, final_answer=""),                     # 編集が無い
    ExecuteResult(error="NameError: name 'get_patch' is not defined"),         # ツールが無いサーバー
    ExecuteResult(final_answer_bool=True, final_answer="パッチの取得に失敗しました。 fatal: not a git repository"),
    ExecuteResult(final_answer_bool=True, final_answer=_PATCH + "[output truncated: 1 of 2 characters omitted]"),
])
def test_fallback_returns_empty_when_nothing_submittable_is_collected(result: ExecuteResult) -> None:
    """回収したものが提出できる形でなければ、空文字を返す(壊れたパッチは出さない)."""
    assert SWEBenchProfile().fallback_solution(_PatchSandbox(result)) == ""


def test_orchestrator_submits_the_collected_patch_when_iterations_run_out() -> None:
    """Orchestrator と組み合わせ: 提出しないまま反復が尽きたら、編集済みのパッチを回収して出す."""
    sandbox = MockSandbox()
    sandbox._namespace["get_patch"] = lambda: _PATCH.rstrip("\n")  # MCP の get_patch の代わり
    exploring = "Thought: look around.\n```python\nprint('exploring')\n```\n<end_code>"
    orchestrator = Orchestrator(
        provider=StubProvider([exploring]),
        extractor=PythonCodeExtractor(),
        sandbox=sandbox,
        profile=SWEBenchProfile(),
        limits=Limits(max_iterations=1, max_input_tokens=10**9, max_output_tokens=10**9,
                      total_time_sec=10**9, time_margin_sec=1.0),
    )
    solution = orchestrator.run("calc__calc-1", "swebench", "task")
    assert solution.success is False
    assert solution.error == "MAX_ITERATIONS"
    assert solution.solution == _PATCH


# ---- プロンプト ----

def _few_shot_code_blocks() -> list[str]:
    """few-shot の中の ```python ブロックの中身を、出てくる順に返す."""
    return re.findall(r"```python\n(.*?)\n```", SWEBenchProfile().few_shot_example(), flags=re.DOTALL)


def test_few_shot_blocks_compile_and_are_not_indented() -> None:
    """手本のコードブロックはどれも行頭が字下げされておらず、Python として compile できる."""
    blocks = _few_shot_code_blocks()
    assert len(blocks) == 4
    for block in blocks:
        assert block == block.lstrip()
        compile(block, "<swebench_few_shot>", "exec")


def test_few_shot_ends_by_submitting_the_value_of_get_patch() -> None:
    """手本の最後は get_patch() の値を提出する(diff を手書きしない)."""
    blocks = _few_shot_code_blocks()
    assert "patch = get_patch()" in blocks[-2]
    assert blocks[-1] == "final_answer(patch)"


def test_prompt_only_uses_tools_the_swebench_server_provides() -> None:
    """手本と手順に出てくるツール名は、どれも SWE-bench のサーバーが実際に提供している."""
    profile = SWEBenchProfile()
    text = profile.few_shot_example() + profile.task_instructions() + profile.format_rules()
    called_names = set(re.findall(r"\b([a-z_]+)\(", text))
    known_tool_names = set(swebench_server.tools)
    assert {"read_file", "edit_file", "run_tests", "get_patch", "run_command"} <= called_names
    python_builtins = {"print", "final_answer", "func", "foo", "divide"}
    assert called_names - python_builtins <= known_tool_names

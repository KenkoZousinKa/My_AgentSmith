"""MBPPProfile(mbpp_profile.py)の提出物の整形と検査のテスト(A-18の一部・A-12で使う)."""
import pytest

from src.agent.prompt.task_profile.mbpp_profile import MBPPProfile, mbpp_rejection, strip_code_fences

_FUNCTION = "def f(x):\n    return x + 1"


@pytest.mark.parametrize("raw", [
    _FUNCTION,
    f"\n  {_FUNCTION}\n\n",
    f"```python\n{_FUNCTION}\n```",
    f"```\n{_FUNCTION}\n```",
    f"  ```python\n{_FUNCTION}\n```\n```  ",
])
def test_strip_code_fences_returns_the_bare_source(raw: str) -> None:
    """前後の空白・開きフェンス(言語名の有無を問わない)・閉じフェンスを落とす."""
    assert strip_code_fences(raw) == _FUNCTION


def test_strip_code_fences_keeps_backticks_inside_the_code() -> None:
    """フェンスで始まらない提出は、中のバッククォートを含めて触らない."""
    source = 'def f():\n    return "```"'
    assert strip_code_fences(source) == source


@pytest.mark.parametrize("solution", [
    _FUNCTION,
    f"import math\nfrom typing import List\n\n{_FUNCTION}",
    f'"""module docstring"""\n{_FUNCTION}',
    f"LIMIT = 10\nscale: int = 2\n{_FUNCTION}",
    f"class Helper:\n    pass\n\n{_FUNCTION}",
    f"async def g():\n    return 1\n\n{_FUNCTION}",
])
def test_accepts_imports_and_definitions(solution: str) -> None:
    """import・関数/クラスの定義・代入・docstringだけなら受理する."""
    assert mbpp_rejection(solution) is None


@pytest.mark.parametrize(("solution", "reason_part"), [
    ("", "empty"),
    ("def f(:\n    return 1", "not valid Python"),
    ("x = 1", "no function definition"),
    (f"{_FUNCTION}\nprint(f(1))", "top-level Expr"),
    (f"{_FUNCTION}\nassert f(1) == 2", "top-level Assert"),
    (f"{_FUNCTION}\nif __name__ == '__main__':\n    f(1)", "top-level If"),
])
def test_rejects_what_breaks_the_graders_run(solution: str, reason_part: str) -> None:
    """採点側の連結実行で落ちる提出を、理由つきで拒否する."""
    reason = mbpp_rejection(solution)
    assert reason is not None
    assert reason_part in reason


def test_sandbox_only_names_are_reported_before_missing_definition() -> None:
    """検証用のコードごと提出したら、「関数定義が無い」ではなく本当の原因(run_tests)を伝える."""
    wrapper = 'import json\nreport = json.loads(run_tests(code="""def f(x):\n    return x"""))'
    reason = mbpp_rejection(wrapper)
    assert reason is not None
    assert "run_tests" in reason
    assert "no function definition" not in reason


def test_final_answer_inside_the_submission_is_rejected() -> None:
    """提出物の中で final_answer を呼んでいたら拒否する(採点環境には無い)."""
    reason = mbpp_rejection(f"{_FUNCTION}\nfinal_answer('x')")
    assert reason is not None
    assert "final_answer" in reason


def test_profile_hooks_use_the_mbpp_rules() -> None:
    """MBPPProfile のフックが上の関数につながっている."""
    profile = MBPPProfile()
    assert profile.sanitize_submission(f"```python\n{_FUNCTION}\n```") == _FUNCTION
    assert profile.submission_rejection(_FUNCTION) is None
    assert profile.submission_rejection("print(1)") is not None
    assert profile.is_fallback_candidate(_FUNCTION) is True
    assert profile.is_fallback_candidate(f"{_FUNCTION}\nprint(f(1))") is False
    assert profile.is_fallback_candidate("print('hello')") is False

"""Sandbox(sandbox_main.py)がツールの戻り値をそのまま渡すことのテスト(LLMに見える print の出力だけを切り詰める)."""
from src.models.sandbox_config import SandboxConfig
from src.sandbox.sandbox_main import Sandbox

_LONG_TEXT = "diff --git a/x.py b/x.py\n" + "+" + "x" * 20000 + "\n"


def _long_text() -> str:
    """出力の上限(既定 8,000字)より長い文字列を返すツール(SWE-bench の get_patch の代わり)."""
    return _LONG_TEXT


def test_tool_result_reaches_final_answer_without_truncation() -> None:
    """ツールの戻り値は切り詰めずにコードへ渡す。final_answer(get_patch()) で長いパッチが壊れない."""
    with Sandbox(config=SandboxConfig(), tools={"get_patch": _long_text}) as sandbox:
        result = sandbox.run("final_answer(get_patch())")
    assert result.final_answer == _LONG_TEXT
    assert result.truncated is False


def test_printed_tool_result_is_still_truncated_for_the_llm() -> None:
    """print した出力は今までどおり上限で切り詰め、切り詰めたことを示す(LLM の入力を守る)."""
    with Sandbox(config=SandboxConfig(), tools={"get_patch": _long_text}) as sandbox:
        result = sandbox.run("print(get_patch())")
    assert len(result.stdout) < len(_LONG_TEXT)
    assert "[output truncated:" in result.stdout
    assert result.truncated is True

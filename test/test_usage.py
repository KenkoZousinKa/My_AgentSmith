"""トークン使用量の抽出(usage.py)のテスト.

課題 VI.1 は思考トークンも出力トークンに数えるため、プロバイダの報告が実際より
小さいときは大きい側に倒すことを確かめる。
"""
from src.agent.llm.usage import estimate_tokens_from_text, extract_token_usage


def test_reported_usage_is_used_as_is() -> None:
    """prompt / completion が揃っていればそのまま使う(本文の長さは見ない)."""
    data = {"usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}
    assert extract_token_usage(data, "x" * 400) == (100, 20)


def test_hidden_reasoning_tokens_are_counted() -> None:
    """total - prompt が completion より大きい(思考を completion に含めない実装)なら大きい方."""
    data = {"usage": {"prompt_tokens": 43, "completion_tokens": 41, "total_tokens": 161}}
    assert extract_token_usage(data, "abc") == (43, 118)


def test_zero_completion_with_text_is_estimated() -> None:
    """本文があるのに completion_tokens=0 なら、本文の文字数から概算する(gemma実測)."""
    data = {"usage": {"prompt_tokens": 1238, "completion_tokens": 0, "total_tokens": 1238}}
    assert extract_token_usage(data, "y" * 1200) == (1238, 300)


def test_missing_usage_falls_back_to_estimate() -> None:
    """usageが無ければ入力0・出力は本文から概算."""
    assert extract_token_usage({}, "z" * 40) == (0, 10)


def test_empty_text_and_zero_usage() -> None:
    """本文が空でusageも0なら0(空応答の計上用)."""
    data = {"usage": {"prompt_tokens": 979, "completion_tokens": 0, "total_tokens": 979}}
    assert extract_token_usage(data, "") == (979, 0)


def test_prompt_is_kept_when_completion_is_missing() -> None:
    """completion_tokens だけ欠けていても、報告された入力は捨てない(今の Agent/main は 0 にしていた)."""
    data = {"usage": {"prompt_tokens": 500}}
    assert extract_token_usage(data, "w" * 80) == (500, 20)


def test_broken_usage_values_are_ignored() -> None:
    """usage が辞書でない・値が数値でない(null・文字列・bool)なら、無いものとして扱い落ちない."""
    assert extract_token_usage({"usage": None}, "a" * 8) == (0, 2)
    assert extract_token_usage({"usage": "n/a"}, "a" * 8) == (0, 2)
    data = {"usage": {"prompt_tokens": "10", "completion_tokens": None, "total_tokens": True}}
    assert extract_token_usage(data, "a" * 8) == (0, 2)


def test_estimate_tokens_from_text() -> None:
    """4文字で1トークン。1〜3文字でも1、空なら0."""
    assert estimate_tokens_from_text("") == 0
    assert estimate_tokens_from_text("abc") == 1
    assert estimate_tokens_from_text("a" * 41) == 10

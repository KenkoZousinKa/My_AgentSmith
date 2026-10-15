"""PythonCodeExtractor の単体テスト."""
import pytest

from src.agent.extractor.python_extractor import PythonCodeExtractor


@pytest.fixture
def extractor() -> PythonCodeExtractor:
    """テスト対象の抽出器を返す."""
    return PythonCodeExtractor()


def test_extracts_single_block(extractor: PythonCodeExtractor) -> None:
    """前後に地の文がある単一ブロックからコードだけ取れる."""
    text = "説明文\n```python\nprint('hi')\n```\n続き"
    assert extractor.extract(text) == "print('hi')"


def test_returns_last_block_when_multiple(extractor: PythonCodeExtractor) -> None:
    """複数ブロックがあるとき最後のブロックを返す(D-b)."""
    text = (
        "例:\n```python\nx = 1\n```\n"
        "本命:\n```python\nx = 2\nprint(x)\n```\n"
    )
    assert extractor.extract(text) == "x = 2\nprint(x)"


def test_returns_none_when_no_block(extractor: PythonCodeExtractor) -> None:
    """コードブロックが無ければ None(D-a)."""
    assert extractor.extract("コードはありません") is None


def test_ignores_non_python_fence(extractor: PythonCodeExtractor) -> None:
    """python/py 以外の言語ラベルは拾わない."""
    assert extractor.extract("```js\nconsole.log(1)\n```") is None


def test_accepts_py_and_uppercase_label(extractor: PythonCodeExtractor) -> None:
    """py / 大文字ラベルも受け付ける(点2)."""
    assert extractor.extract("```py\nprint(1)\n```") == "print(1)"
    assert extractor.extract("```Python\nprint(2)\n```") == "print(2)"


def test_rstrips_trailing_blank_lines(extractor: PythonCodeExtractor) -> None:
    """末尾の空行/空白は除去する(点3)."""
    assert extractor.extract("```python\nx = 1\n\n\n```") == "x = 1"


def test_multiline_code_preserved(extractor: PythonCodeExtractor) -> None:
    """複数行コードのインデント・改行(末尾以外)が保たれる."""
    text = "```python\ndef f():\n    return 1\n```"
    assert extractor.extract(text) == "def f():\n    return 1"


def test_closing_fence_without_trailing_newline(extractor: PythonCodeExtractor) -> None:
    """閉じフェンスが独立行なら、その後に改行が無くても取れる."""
    assert extractor.extract("```python\nprint('x')\n```") == "print('x')"


def test_inline_fence_is_ignored(extractor: PythonCodeExtractor) -> None:
    """行頭でないフェンス(地の文の途中)は拾わない(点4)."""
    assert extractor.extract("見て ```python x``` ね") is None


def test_nested_backticks_in_string(extractor: PythonCodeExtractor) -> None:
    """コード中の行頭でない ``` では閉じない(点1)."""
    text = "```python\ns = '```'\nprint(s)\n```"
    assert extractor.extract(text) == "s = '```'\nprint(s)"

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
    """python 以外の言語ラベルは拾わない(D-c 厳密)."""
    text = "```js\nconsole.log(1)\n```"
    assert extractor.extract(text) is None


def test_block_without_trailing_newline(extractor: PythonCodeExtractor) -> None:
    """閉じフェンス直前に改行が無くても取れる."""
    text = "```python\nprint('x')```"
    assert extractor.extract(text) == "print('x')"


def test_multiline_code_preserved(extractor: PythonCodeExtractor) -> None:
    """複数行コードのインデント・改行が保たれる."""
    text = "```python\ndef f():\n    return 1\n```"
    assert extractor.extract(text) == "def f():\n    return 1"
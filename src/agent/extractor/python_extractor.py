"""Pythonコード用コード抽出機能を提供するモジュール.

LLM出力中の```python```フェンスブロックを抽出する具象クラス。
"""
import re

from src.agent.extractor.code_extractor import CodeExtractor

# ```python``` Pythonコードブロック
# [ \t]* ラベルのあとの空白、タブを許可
# \r?\n コードブロックあとの改行を許可
# (.*?) コード本体。re.DOTALLで改行を含む任意の文字列を許可
# \r?\n? コードブロックの終わりの直前に改行を許可
_PYTHON_CODE_BLOCK_PATTERN = re.compile(r"```python[ \t]*\r?\n(.*?)\r?\n?", re.DOTALL)


class PythonCodeExtractor(CodeExtractor):
    """LLMの出力テキストからPythonブロックのコードを抽出する具象クラス."""

    def extract(self, llm_output: str) -> str | None:
        """LLMの出力テキストからPythonコードを抽出する.

        複数のPythonコードブロックが存在する場合は、最後のブロックを抽出する。

        Args:
            llm_output (str): LLMが生成した出力テキスト全体。

        Returns:
            str | None: 抽出されたコード
            または抽出できなかった場合(コードブロックが見つからない)はNone
        """
        # テキスト全体からPythonコードブロックを抽出
        code_blocks = _PYTHON_CODE_BLOCK_PATTERN.findall(llm_output)
        # なければNone
        if not code_blocks:
            return None

        # 最後のコードブロックを返す
        return str(code_blocks[-1])

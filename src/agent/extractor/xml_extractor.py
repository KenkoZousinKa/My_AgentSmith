"""xmlコード抽出機能を提供するモジュール."""
from src.agent.extractor.code_extractor import CodeExtractor


class XMLCodeExtractor(CodeExtractor):
    """XMLコードを抽出するクラス."""

    def extract(self, llm_output: str) -> str | None:
        """LLMの出力テキストからXMLコードを抽出する.

        Args:
            llm_output (str): LLMの出力テキスト

        Returns:
            str: 抽出されたXMLコード
        """
        # XMLコードの抽出ロジックを実装する
        return llm_output  # 実際には抽出したXMLコードを返す

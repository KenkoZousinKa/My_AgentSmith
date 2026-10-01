"""json / hermesコード抽出機能を提供するモジュール."""
from src.agent.extractor.code_extractor import CodeExtractor


class JSONHermesCodeExtractor(CodeExtractor):
    """JSON / Hermesコードを抽出するクラス."""

    def extract_code_from_text(self, llm_output: str) -> str:
        """LLMの出力テキストからJSON / Hermesコードを抽出する.

        Args:
            llm_output (str): LLMの出力テキスト
        Returns:
            str: 抽出されたJSON / Hermesコード
        """
        # JSON / Hermesコードの抽出ロジックを実装する
        return llm_output  # 実際には抽出したJSON / Hermesコードを返す
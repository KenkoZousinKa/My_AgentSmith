"""reactコード抽出機能を提供するモジュール.
"""
from src.agent.extractor.code_extractor import CodeExtractor


class ReactCodeExtractor(CodeExtractor):
    """Reactコードを抽出するクラス."""

    def extract_code_from_text(self, llm_output: str) -> str:
        """LLMの出力テキストからReactコードを抽出する.

        Args:
            llm_output (str): LLMの出力テキスト

        Returns:
            str: 抽出されたReactコード
        """
        # Reactコードの抽出ロジックを実装する
        return llm_output  # 実際には抽出したReactコードを返す
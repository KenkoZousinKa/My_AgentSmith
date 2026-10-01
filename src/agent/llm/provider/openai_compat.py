"""OpenAI互換のAPIを提供するプロバイダを統一的に扱うためのモジュール。

OpenRouter / Groq / Together / FireWorksなど。
リクエスト成形->送信->レスポンス成形
tokensはusage.pyで集計する、なければ概算。
-> LLMResponseを返す。リトライ、キー選択はkey_manager.pyに任せる。
"""
from src.agent.llm.provider.provider import LLMProvider, LLMResponse


class OpenAICompatProvider(LLMProvider):
    """OpenAI互換のAPIを提供するプロバイダを統一的に扱うためのクラス."""

    def generate(self, messages: str, model_name: str, stop_sequences: str, max_tokens: int) -> LLMResponse:
        """LLMにリクエストを送信し、レスポンスを返す.

        Args:
            messages (str): LLMに送信するメッセージ
            model_name (str): 使用するモデルの名前
            stop_sequences (str): 生成を停止するトークンのリスト
            max_tokens (int): 生成する最大トークン数

        Returns:
            LLMResponse: LLMのレスポンス情報
        """
        # OpenAI互換APIへのリクエスト処理を実装する
        return LLMResponse(
            text="",
            input_tokens=0,
            output_tokens=0,
            request_time_ms=0.0,
            api_url="",
            model_name=model_name,
            retries=0
        )

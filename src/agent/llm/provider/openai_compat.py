"""OpenAI互換のAPIを提供するプロバイダを統一的に扱うためのモジュール。

OpenRouter / Groq / Together / FireWorksなど。
chat / completions エンドポイントに投げ、choices[0].message.contentとusageを共通のLLMResponseに整形して返す。
リクエスト組み立て / レスポンス成形だけを実装し、送信や計測、エラー判定は LLMProvider.generate() に任せる。
tokensはusage.pyで集計する、なければ概算。
リトライ、キー選択はkey_manager.pyに任せる。
"""
import json
from typing import Any

from src.agent.llm.provider.provider import LLMProvider, LLMResponse, LLMError
from src.agent.llm.usage import extract_token_usage


class OpenAICompatProvider(LLMProvider):
    """OpenAI Chat Completions 互換のAPIを提供するプロバイダを統一的に扱うためのクラス."""

    def _build_request(
        self,
        messages: list[dict[str, str]],
        stop_sequences: list[str],
        max_tokens: int
    ) -> tuple[str, dict[str, str], str]:
        url = f"{self.config.provider_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload: dict[str, Any] = {
            "model": self.config.model_name,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if stop_sequences:
            payload["stop"] = stop_sequences

        payload.update(self.config.additional_params)

        return url, headers, json.dumps(payload)

    def _parse_response(self, body: str, request_time_ms: float) -> LLMResponse:
        """OpenAI互換のレスポンスをLLMResponseに変換する.

        Args:
            body (str): OpenAI互換のレスポンスボディ(JSON文字列)。
            request_time_ms (float): リクエストにかかった時間(ミリ秒)。

        Returns:
            LLMResponse: 正規化したLLMのレスポンス情報。

        Raises:
            LLMError: JSONや必須フィールドの解釈に失敗、または欠けている場合。
        """
        try:
            data: dict[str, Any] = json.loads(body)
            text: str = data["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
            raise LLMError(f"Failed to parse response: {e}: {body[:500]}") from e

        input_tokens, output_tokens = extract_token_usage(data, text)
        return LLMResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_time_ms=request_time_ms,
            api_url=self.config.provider_url,
            model_name=self.config.model_name,
            retries=0  # リトライ回数はgenerate()で計測するため
        )

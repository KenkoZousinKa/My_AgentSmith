"""OpenAI互換のAPIを提供するプロバイダを統一的に扱うためのモジュール。

OpenRouter / Groq / Google / NVIDIA / Mistral / cohere / ollama など。
chat / completions エンドポイントに投げ、choices[0].message.contentとusageを共通のLLMResponseに整形して返す。
リクエスト組み立て / レスポンス成形だけを実装し、送信や計測、エラー判定は LLMProvider.generate() に任せる。
tokensはusage.pyで集計する、なければ概算。
リトライ、キー選択はkey_manager.pyに任せる。

- 下記を提供
OpenAICompatProvider(LLMProvider) def _build_request() / _parse_response()
"""
import json
from typing import Any

from src.agent.llm.provider.provider import LLMProvider, LLMResponse, LLMError, EmptyResponseError
from src.agent.llm.usage import extract_token_usage


class OpenAICompatProvider(LLMProvider):
    """OpenAI Chat Completions 互換のAPIを提供するプロバイダを統一的に扱うためのクラス."""

    def _build_request(
        self,
        messages: list[dict[str, str]],
        stop_sequences: list[str],
        max_tokens: int
    ) -> tuple[str, dict[str, str], str]:
        """OpenAI互換のリクエストを組み立てる.

        url, headers, body文字列を返す。bodyはJSON文字列。
        urlには /chat/completions を付与したプロバイダURL。
        headersにはAuthorization(認証情報)とContent-Type。
        bodyにはmodel, messages, max_tokens, stop_sequencesを含むJSON文字列。

        Args:
            messages (list[dict[str, str]]): LLMに送信するメッセージ。OpenAI互換の形式で、roleとcontentを持つ辞書のリスト。
            stop_sequences (list[str]): 生成を停止する文字列郡(既定は ["<end_code>"])
            max_tokens (int): 生成する最大トークン数
        """

        url = f"{self.config.provider_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload: dict[str, Any] = {
            "model": self.model,
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
        # レスポンスをJSONとして解釈し、choices[0].message.contentを抽出する
        try:
            data: dict[str, Any] = json.loads(body)
            message: dict[str, Any] = data["choices"][0]["message"]
            text = message.get("content")
        # AttributeErrorは、choices[0]が存在しない(null)場合に発生する可能性がある
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError) as e:
            raise LLMError(f"Failed to parse response: {e}: {body[:500]}") from e

        # レスポンスにtextが空の場合、reasoningやreasoning_contentを代替として使用する
        if not (isinstance(text, str) and text.strip()):
            for field_name in ("reasoning", "reasoning_content"):
                reasoning = data.get(field_name)
                if isinstance(reasoning, str) and reasoning.strip():
                    text = reasoning
                    break

        # それでもtextが空の場合使えないので、消費したトークンを持たせたEmptyResponseErrorを発生させる
        # ResilientClientで捕まえて計上する。
        if not (isinstance(text, str) and text.strip()):
            wasted_input_tokens, wasted_output_tokens = extract_token_usage(data, "")
            raise EmptyResponseError(
                f"empty content from provider={self.config.name} model={self.model} {body[:300]}",
                input_tokens=wasted_input_tokens,
                output_tokens=wasted_output_tokens,
            )

        # レスポンスのusageを解釈して、input_tokens, output_tokensを取得する
        input_tokens, output_tokens = extract_token_usage(data, text)
        return LLMResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_time_ms=request_time_ms,
            api_url=self.config.provider_url,
            model_name=self.model,
            retries=0  # リトライ回数はgenerate()で計測するため
        )

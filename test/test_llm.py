"""LLMプロバイダ層のテスト(transportはモック。実HTTPは叩かない)."""
import json

import pytest

from src.agent.llm.provider.openai_compat import OpenAICompatProvider
from src.agent.llm.transport.transport import HttpResponse, HttpTransport
from src.agent.llm.provider.provider import (
    AuthenticationError,
    BadRequestError,
    LLMError,
    LLMResponse,
    ProviderConfig,
    RateLimitError,
    ServerError,
)

_CONFIG = ProviderConfig(
    name="fake",
    provider_url="https://example.test/api/v1",
    model="fake/model-1",
    keys_env="FAKE_API_KEY",
)

_OPENAI_JSON = json.dumps({
    "choices": [{"message": {"role": "assistant",
                             "content": "Thought: done\n```python\nfinal_answer(1)\n```"}}],
    "usage": {"prompt_tokens": 12, "completion_tokens": 7},
})


class _FakeTransport(HttpTransport):
    """送信内容を記録し固定応答を返すモックtransport."""

    def __init__(self, status: int = 200, body: str = _OPENAI_JSON,
                 headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.body = body
        self.headers = headers if headers is not None else {}
        self.calls: list[tuple[str, dict[str, str], str]] = []

    def post(self, url: str, headers: dict[str, str], data: str, timeout: float = 60.0) -> HttpResponse:
        self.calls.append((url, headers, data))
        return HttpResponse(status=self.status, body=self.body, headers=self.headers)


def _make_provider(transport: HttpTransport) -> OpenAICompatProvider:
    """テスト用に ProviderConfig/モックtransport/ダミーキーを注入した provider を作る."""
    return OpenAICompatProvider(config=_CONFIG, transport=transport, api_key="sk-test")


def test_generate_returns_normalized_response() -> None:
    """generate() が usage/本文/モデル/URL を共通 LLMResponse に正規化する."""
    transport = _FakeTransport()
    res = _make_provider(transport).generate(
        messages=[{"role": "user", "content": "add"}],
        stop_sequences=["<end_code>"],
        max_tokens=256,
    )
    assert isinstance(res, LLMResponse)
    assert "final_answer(1)" in res.text
    assert res.input_tokens == 12
    assert res.output_tokens == 7
    assert res.model_name == "fake/model-1"
    assert res.api_url == "https://example.test/api/v1"
    assert res.retries == 0


def test_build_request_includes_model_messages_stop() -> None:
    """送信bodyに model/messages/stop/max_tokens と Bearer ヘッダが入る."""
    transport = _FakeTransport()
    _make_provider(transport).generate(
        messages=[{"role": "user", "content": "add"}], stop_sequences=["<end_code>"], max_tokens=256
    )
    url, headers, data = transport.calls[0]
    assert url == "https://example.test/api/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-test"
    payload = json.loads(data)
    assert payload["model"] == "fake/model-1"
    assert payload["messages"] == [{"role": "user", "content": "add"}]
    assert payload["stop"] == ["<end_code>"]
    assert payload["max_tokens"] == 256


def test_429_raises_rate_limit_error_with_retry_after() -> None:
    """HTTP 429 は RateLimitError を送出し、retry-afterヘッダを秒数に解釈する."""
    transport = _FakeTransport(status=429, body="rate limited", headers={"retry-after": "3"})
    with pytest.raises(RateLimitError) as exc_info:
        _make_provider(transport).generate(
            messages=[{"role": "user", "content": "x"}], stop_sequences=[], max_tokens=16
        )
    assert exc_info.value.status == 429
    assert exc_info.value.retry_after == 3.0
    # 後方互換: RateLimitError は LLMError の子孫
    assert isinstance(exc_info.value, LLMError)


def test_429_without_retry_after_header_is_none() -> None:
    """retry-afterヘッダが無い429では retry_after は None(既定バックオフにフォールバック)."""
    transport = _FakeTransport(status=429, body="slow down")
    with pytest.raises(RateLimitError) as exc_info:
        _make_provider(transport).generate(
            messages=[{"role": "user", "content": "x"}], stop_sequences=[], max_tokens=16
        )
    assert exc_info.value.retry_after is None


def test_429_with_http_date_retry_after_is_none() -> None:
    """retry-afterがHTTP-date形式(非数値)なら解釈せず None を返す."""
    transport = _FakeTransport(status=429, headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})
    with pytest.raises(RateLimitError) as exc_info:
        _make_provider(transport).generate(
            messages=[{"role": "user", "content": "x"}], stop_sequences=[], max_tokens=16
        )
    assert exc_info.value.retry_after is None


def test_5xx_raises_server_error() -> None:
    """HTTP 5xx は ServerError を送出する."""
    transport = _FakeTransport(status=503, body="service unavailable")
    with pytest.raises(ServerError) as exc_info:
        _make_provider(transport).generate(
            messages=[{"role": "user", "content": "x"}], stop_sequences=[], max_tokens=16
        )
    assert exc_info.value.status == 503


def test_401_raises_auth_error() -> None:
    """HTTP 401 は AuthenticationError を送出する."""
    transport = _FakeTransport(status=401, body="invalid api key")
    with pytest.raises(AuthenticationError):
        _make_provider(transport).generate(
            messages=[{"role": "user", "content": "x"}], stop_sequences=[], max_tokens=16
        )


def test_400_raises_bad_request_error() -> None:
    """その他4xx(400) は BadRequestError を送出する."""
    transport = _FakeTransport(status=400, body="bad payload")
    with pytest.raises(BadRequestError):
        _make_provider(transport).generate(
            messages=[{"role": "user", "content": "x"}], stop_sequences=[], max_tokens=16
        )

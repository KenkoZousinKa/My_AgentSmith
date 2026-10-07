"""LLMプロバイダ層のテスト(transportはモック。実HTTPは叩かない)."""
import json

import pytest

from src.agent.llm.provider.openai_compat import OpenAICompatProvider
from src.agent.llm.provider.provider import LLMError, LLMResponse, ProviderConfig
from src.agent.llm.transport.transport import HttpTransport

_CONFIG = ProviderConfig(
    name="fake",
    provider_url="https://example.test/api/v1",
    model_name="fake/model-1",
    keys_env="FAKE_API_KEY",
)

_OPENAI_JSON = json.dumps({
    "choices": [{"message": {"role": "assistant",
                             "content": "Thought: done\n```python\nfinal_answer(1)\n```"}}],
    "usage": {"prompt_tokens": 12, "completion_tokens": 7},
})


class _FakeTransport(HttpTransport):
    """送信内容を記録し固定JSONを返すモックtransport."""

    def __init__(self, status: int = 200, body: str = _OPENAI_JSON) -> None:
        self.status = status
        self.body = body
        self.calls: list[tuple[str, dict[str, str], str]] = []

    def post(self, url: str, headers: dict[str, str], data: str, timeout: float = 60.0) -> tuple[int, str]:
        self.calls.append((url, headers, data))
        return self.status, self.body


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


def test_non_2xx_raises_llm_error() -> None:
    """HTTP非2xx は LLMError を送出する."""
    transport = _FakeTransport(status=429, body="rate limited")
    with pytest.raises(LLMError):
        _make_provider(transport).generate(
            messages=[{"role": "user", "content": "x"}], stop_sequences=[], max_tokens=16
        )

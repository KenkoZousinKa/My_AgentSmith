"""LLMプロバイダ層のテスト(transportはモック。実HTTPは叩かない)."""
import json

import pytest

from src.agent.llm.provider.openai_compat import OpenAICompatProvider
from src.agent.llm.transport.transport import HttpResponse, HttpTransport
from src.agent.llm.provider.provider import (
    AuthenticationError,
    BadRequestError,
    EmptyResponseError,
    LLMError,
    LLMResponse,
    ProviderConfig,
    RateLimitError,
    ServerError,
)

_CONFIG = ProviderConfig(
    name="fake",
    provider_url="https://example.test/api/v1",
    models=["fake/model-1"],
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
    return OpenAICompatProvider(config=_CONFIG, transport=transport, api_key="sk-test", model="fake/model-1")


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


_MODEL_PARAMS_CONFIG = ProviderConfig(
    name="fake",
    provider_url="https://example.test/api/v1",
    models=["fake/model-1", "fake/model-2"],
    keys_env="FAKE_API_KEY",
    additional_params={"temperature": 0.0},
    model_params={"fake/model-2": {"reasoning_effort": "low", "temperature": 0.7}},
)


def _send_with(model: str) -> dict[str, object]:
    """model_params付きconfigで1回送信し、送信bodyを辞書で返す."""
    transport = _FakeTransport()
    provider = OpenAICompatProvider(
        config=_MODEL_PARAMS_CONFIG, transport=transport, api_key="sk-test", model=model
    )
    provider.generate(messages=[{"role": "user", "content": "add"}], stop_sequences=[], max_tokens=64)
    payload: dict[str, object] = json.loads(transport.calls[0][2])
    return payload


def test_model_params_apply_only_to_the_named_model() -> None:
    """model_paramsは該当モデルのbodyにだけ入る.

    実測(groq)では gpt-oss系は reasoning_effort が無いと本文がreasoningへ流れてcontentが空になり、
    逆にqwenは指定するとcontentが空になる。同一プロバイダ内でモデル毎に分ける必要がある。
    """
    assert "reasoning_effort" not in _send_with("fake/model-1")
    assert _send_with("fake/model-2")["reasoning_effort"] == "low"


def test_model_params_override_provider_additional_params() -> None:
    """同じキーがあればmodel_params(モデル単位)がadditional_params(プロバイダ単位)に勝つ."""
    assert _send_with("fake/model-1")["temperature"] == 0.0
    assert _send_with("fake/model-2")["temperature"] == 0.7


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

def _body(message: dict[str, object], usage: dict[str, int] | None = None) -> str:
    """choices[0].message と usage を持つOpenAI互換のレスポンス本文を作る."""
    data: dict[str, object] = {"choices": [{"message": message}]}
    if usage is not None:
        data["usage"] = usage
    return json.dumps(data)


def _generate(transport: HttpTransport) -> LLMResponse:
    return _make_provider(transport).generate(
        messages=[{"role": "user", "content": "x"}], stop_sequences=["<end_code>"], max_tokens=16
    )


@pytest.mark.parametrize("field_name", ["reasoning", "reasoning_content"])
def test_null_content_falls_back_to_reasoning(field_name: str) -> None:
    """contentがnullで本文がreasoning系の欄にあるとき(gpt-oss / nemotron)、それを本文として返す."""
    body = _body(
        {"role": "assistant", "content": None, field_name: "Thought: x\n```python\nfinal_answer(1)\n```"},
        usage={"prompt_tokens": 30, "completion_tokens": 20},
    )
    res = _generate(_FakeTransport(body=body))
    assert "final_answer(1)" in res.text
    assert (res.input_tokens, res.output_tokens) == (30, 20)


def test_content_wins_over_reasoning() -> None:
    """contentに本文があれば、reasoningは使わない(思考の文章をコードとして扱わない)."""
    body = _body({"role": "assistant", "content": "the answer", "reasoning": "thinking..."})
    assert _generate(_FakeTransport(body=body)).text == "the answer"


@pytest.mark.parametrize("content", [None, "", "   \n"])
def test_empty_content_raises_empty_response_with_tokens(content: object) -> None:
    """本文がどこにも無ければEmptyResponseError。消費トークンを持ち、LLMErrorとして受けられる."""
    body = _body({"role": "assistant", "content": content}, usage={"prompt_tokens": 900, "completion_tokens": 600})
    with pytest.raises(EmptyResponseError) as info:
        _generate(_FakeTransport(body=body))
    assert (info.value.input_tokens, info.value.output_tokens) == (900, 600)
    assert isinstance(info.value, LLMError)
    assert "fake/model-1" in str(info.value)


def test_missing_choices_raises_llm_error() -> None:
    """choicesが無い・messageが辞書でないなど、形が壊れていればLLMError(クラッシュしない)."""
    for body in ['{"error": "x"}', '{"choices": []}', '{"choices": [{"message": null}]}', "not json"]:
        with pytest.raises(LLMError):
            _generate(_FakeTransport(body=body))

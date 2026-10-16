"""ResilientLLMClient のリトライ/ローテ/フォールバック/時間予算のテスト.

実HTTPは叩かず、generate が例外列を順に送出するフェイクProviderを注入する。
sleep は記録用フェイク、time_remaining も注入して決定的に検証する。
"""
import pytest

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
from src.agent.llm.resilient_client import AllProvidersExhausted, ResilientLLMClient
from src.agent.llm.transport.transport import HttpTransport, HttpResponse, TransportError
from src.config.settings import RetrySettings


class _NullTransport(HttpTransport):
    """呼ばれない前提のダミーtransport(ProviderはフェイクなのでHTTPは発生しない)."""

    def post(self, url: str, headers: dict[str, str], data: str, timeout: float = 60.0) -> HttpResponse:
        raise AssertionError("transport should not be called in these tests")


def _config(name: str, keys_env: str, priority: int) -> ProviderConfig:
    return ProviderConfig(
        name=name, provider_url=f"https://{name}.test/v1",
        models=[f"{name}/model"], keys_env=keys_env, priority=priority,
    )


def _ok_response(model: str = "x/model") -> LLMResponse:
    return LLMResponse(
        text="ok", input_tokens=1, output_tokens=1, request_time_ms=1.0,
        api_url="https://x.test/v1", model_name=model, retries=0,
    )


class _ScriptedProvider:
    """generate 呼び出しごとに、与えた「結果 or 例外」を順に返す/送出するフェイクProvider.

    ファクトリ経由で (config, transport, key) から生成されるが、挙動は key 列ごとに
    外側の辞書 scripts[key] のイテレータで決める。
    """

    def __init__(self, config: ProviderConfig, transport: HttpTransport, key: str,
                 scripts: dict[str, list[object]]) -> None:
        self._key = key
        self._script = scripts.get(key, [])
        self._index = 0

    def generate(self, messages: list[dict[str, str]], stop_sequences: list[str], max_tokens: int) -> LLMResponse:
        if self._index >= len(self._script):
            raise AssertionError(f"no scripted action left for key={self._key}")
        action = self._script[self._index]
        self._index += 1
        if isinstance(action, BaseException):
            raise action
        assert isinstance(action, LLMResponse)
        return action


def _client(providers: list[ProviderConfig], scripts: dict[str, list[object]],
            retry: RetrySettings | None = None,
            time_remaining: object = None) -> tuple[ResilientLLMClient, list[float]]:
    """scriptsに従うフェイクProviderを注入したクライアントと、sleep記録リストを返す."""
    slept: list[float] = []

    def factory(config: ProviderConfig, transport: HttpTransport, key: str, model: str) -> _ScriptedProvider:
        return _ScriptedProvider(config, transport, key, scripts)

    client = ResilientLLMClient(
        providers=providers,
        transport=_NullTransport(),
        retry=retry if retry is not None else RetrySettings(),
        provider_factory=factory,  # type: ignore[arg-type]
        sleep=slept.append,
        time_remaining=time_remaining,  # type: ignore[arg-type]
    )
    return client, slept


def _gen(client: ResilientLLMClient) -> LLMResponse:
    return client.generate(messages=[{"role": "user", "content": "x"}], stop_sequences=[], max_tokens=16)


def test_first_attempt_success_no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """初回で成功すれば待機せず retries=0."""
    monkeypatch.setenv("P1_KEY", "k1")
    providers = [_config("p1", "P1_KEY", 1)]
    client, slept = _client(providers, {"k1": [_ok_response()]})
    res = _gen(client)
    assert res.retries == 0
    assert slept == []


def test_retry_same_key_then_success_counts_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """ServerError(5xx)で1回バックオフ再送し2回目で成功。retries=1、sleepが1回。"""
    monkeypatch.setenv("P1_KEY", "k1")
    providers = [_config("p1", "P1_KEY", 1)]
    scripts = {"k1": [ServerError("500", status=500), _ok_response()]}
    client, slept = _client(providers, scripts)
    res = _gen(client)
    assert res.retries == 1
    assert len(slept) == 1


def test_rate_limit_advances_without_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """429は待たず次のキーへ(retry_afterがあっても待たない)。"""
    monkeypatch.setenv("P1_KEY", "k1"); monkeypatch.setenv("P1_KEY_2", "k2")
    providers = [_config("p1", "P1_KEY", 1)]
    scripts = {"k1": [RateLimitError("429", status=429, retry_after=3.0)], "k2": [_ok_response()]}
    client, slept = _client(providers, scripts)
    res = _gen(client)
    assert res.retries == 1
    assert slept == []


def test_rotate_to_next_key_on_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """401は同一キー再送せず(待機なし)次のキーへ。2本目で成功."""
    monkeypatch.setenv("P1_KEY", "k1")
    monkeypatch.setenv("P1_KEY_2", "k2")
    providers = [_config("p1", "P1_KEY", 1)]
    scripts: dict[str, list[object]] = {"k1": [AuthenticationError("401", status=401)], "k2": [_ok_response()]}
    client, slept = _client(providers, scripts)
    res = _gen(client)
    assert res.retries == 1   # k1の1回失敗を計上
    assert slept == []        # authは待たない


def test_fallback_to_next_provider_when_keys_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    """p1の全キーが枯れたらp2へフォールバックして成功."""
    monkeypatch.setenv("P1_KEY", "k1")
    monkeypatch.setenv("P2_KEY", "k2")
    providers = [_config("p1", "P1_KEY", 1), _config("p2", "P2_KEY", 2)]
    # k1: 初回+2リトライ すべて5xx(max_retries_per_key=2) -> キー枯れ -> p2へ
    retry = RetrySettings(max_retries_per_key=2, backoff_base_seconds=0.0, backoff_max_seconds=0.0)
    scripts: dict[str, list[object]] = {
        "k1": [ServerError("500", status=500), ServerError("500", status=500), ServerError("500", status=500)],
        "k2": [_ok_response("p2/model")],
    }
    client, slept = _client(providers, scripts, retry=retry)
    res = _gen(client)
    assert res.model_name == "p2/model"
    assert len(slept) == 2   # k1で2回だけ待機(3回目=最終試行は待たずに諦め)


def test_provider_without_keys_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """キーが1本も無いプロバイダは飛ばして次へ."""
    monkeypatch.delenv("P1_KEY", raising=False)
    monkeypatch.setenv("P2_KEY", "k2")
    providers = [_config("p1", "P1_KEY", 1), _config("p2", "P2_KEY", 2)]
    client, slept = _client(providers, {"k2": [_ok_response("p2/model")]})
    res = _gen(client)
    assert res.model_name == "p2/model"


def test_all_exhausted_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """全プロバイダ・全キーが失敗したら AllProvidersExhausted(原因を__cause__に保持)."""
    monkeypatch.setenv("P1_KEY", "k1")
    providers = [_config("p1", "P1_KEY", 1)]
    retry = RetrySettings(max_retries_per_key=0, backoff_base_seconds=0.0, backoff_max_seconds=0.0)
    scripts: dict[str, list[object]] = {"k1": [TransportError("conn reset")]}
    client, _ = _client(providers, scripts, retry=retry)
    with pytest.raises(AllProvidersExhausted) as exc_info:
        _gen(client)
    assert isinstance(exc_info.value.__cause__, TransportError)
    assert exc_info.value.attempts == 1  # key1つ×max_retries_per_key=0 => 1試行で全滅



def test_bad_request_skips_combo_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:  # 旧 test_bad_request_aborts_immediately を置換
    """BadRequest(不明モデルID等)はこの組合せを飛ばし、次キー/次モデルを試す。"""
    monkeypatch.setenv("P1_KEY", "k1"); monkeypatch.setenv("P1_KEY_2", "k2")
    providers = [_config("p1", "P1_KEY", 1)]
    scripts = {"k1": [BadRequestError("400", status=400)], "k2": [_ok_response()]}
    client, slept = _client(providers, scripts)
    res = _gen(client)
    assert res.retries == 1
    assert slept == []


def test_no_time_budget_gives_up_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """残予算が尽きていれば待たずにキーを諦める(p2へフォールバック)."""
    monkeypatch.setenv("P1_KEY", "k1")
    monkeypatch.setenv("P2_KEY", "k2")
    providers = [_config("p1", "P1_KEY", 1), _config("p2", "P2_KEY", 2)]
    retry = RetrySettings(max_retries_per_key=2, safety_margin_seconds=2.0)
    # time_remaining=1.0 < safety_margin=2.0 -> budget<=0 -> 待てない -> キー諦め -> p2へ
    scripts: dict[str, list[object]] = {
        "k1": [RateLimitError("429", status=429, retry_after=None)], "k2": [_ok_response("p2/model")]}
    client, slept = _client(providers, scripts, retry=retry, time_remaining=lambda: 1.0)
    res = _gen(client)
    assert res.model_name == "p2/model"
    assert slept == []   # 待機せずに諦めた


def test_resilient_sends_string_model_and_iterates_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """各リクエストの body.model が単一 str で、models を順に試す(実 OpenAICompatProvider)。"""
    import json
    from src.agent.llm.provider.openai_compat import OpenAICompatProvider
    ok_json = json.dumps({"choices":[{"message":{"role":"assistant","content":"ok"}}],
                          "usage":{"prompt_tokens":1,"completion_tokens":1}})
    sent_models: list[object] = []

    class RecordingTransport(HttpTransport):
        def __init__(self) -> None:
            self._n = 0

        def post(self, url: str, headers: dict[str, str], data: str, timeout: float = 60.0) -> HttpResponse:
            sent_models.append(json.loads(data)["model"]); self._n += 1
            return HttpResponse(status=(429 if self._n == 1 else 200),
                                body=("{}" if self._n == 1 else ok_json), headers={})

    monkeypatch.setenv("K_ENV", "sk-x")
    cfg = ProviderConfig(name="groq", provider_url="https://g.test/v1",
                         models=["m/one", "m/two"], keys_env="K_ENV")
    client = ResilientLLMClient(providers=[cfg], transport=RecordingTransport(),
                                retry=RetrySettings(), provider_factory=OpenAICompatProvider)
    res = client.generate([{"role":"user","content":"x"}], ["<end_code>"], 16)
    assert res.model_name == "m/two"
    assert sent_models == ["m/one", "m/two"]
    assert all(isinstance(m, str) for m in sent_models)

def test_empty_response_tokens_are_added_to_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """空応答で消費したトークンは、成功したレスポンスの使用量に足される(過少計上しない)."""
    monkeypatch.setenv("P1_KEY", "k1")
    monkeypatch.setenv("P2_KEY", "k2")
    providers = [_config("p1", "P1_KEY", 1), _config("p2", "P2_KEY", 2)]
    scripts: dict[str, list[object]] = {
        "k1": [EmptyResponseError("empty", input_tokens=900, output_tokens=600)],
        "k2": [_ok_response("p2/model")]}
    client, slept = _client(providers, scripts)
    res = _gen(client)
    assert res.model_name == "p2/model"
    assert (res.input_tokens, res.output_tokens) == (901, 601)
    assert res.retries == 1
    assert slept == []  # 空応答は待っても直らないので、待たずに次へ


def test_exhausted_carries_wasted_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """全滅した場合も、空応答で消費したトークンを例外に持たせて上位へ渡す."""
    monkeypatch.setenv("P1_KEY", "k1")
    providers = [_config("p1", "P1_KEY", 1)]
    scripts: dict[str, list[object]] = {"k1": [EmptyResponseError("empty", input_tokens=50, output_tokens=7)]}
    client, _ = _client(providers, scripts)
    with pytest.raises(AllProvidersExhausted) as info:
        _gen(client)
    assert (info.value.input_tokens, info.value.output_tokens) == (50, 7)
    assert isinstance(info.value.__cause__, EmptyResponseError)


def test_unparsable_response_advances_to_next_combo(monkeypatch: pytest.MonkeyPatch) -> None:
    """解釈できないレスポンス(素のLLMError)でも落ちず、次のプロバイダを試す."""
    monkeypatch.setenv("P1_KEY", "k1")
    monkeypatch.setenv("P2_KEY", "k2")
    providers = [_config("p1", "P1_KEY", 1), _config("p2", "P2_KEY", 2)]
    scripts: dict[str, list[object]] = {
        "k1": [LLMError("Failed to parse response")],
        "k2": [_ok_response("p2/model")]}
    client, _ = _client(providers, scripts)
    assert _gen(client).model_name == "p2/model"

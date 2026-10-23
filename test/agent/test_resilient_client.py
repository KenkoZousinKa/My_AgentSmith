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
    外側の辞書 scripts[key] の先頭から消費して決める。クライアントは試行ごとに
    (残り時間に合わせたタイムアウトで)Providerを作り直すため、進み具合は
    インスタンスではなく共有リストで持つ。
    """

    def __init__(self, config: ProviderConfig, transport: HttpTransport, key: str,
                 scripts: dict[str, list[object]]) -> None:
        self._key = key
        self._script = scripts.setdefault(key, [])
        self.config = config

    def generate(self, messages: list[dict[str, str]], stop_sequences: list[str], max_tokens: int) -> LLMResponse:
        if not self._script:
            raise AssertionError(f"no scripted action left for key={self._key}")
        action = self._script.pop(0)
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
    scripts: dict[str, list[object]] = {"k1": [ServerError("500", status=500), _ok_response()]}
    client, slept = _client(providers, scripts)
    res = _gen(client)
    assert res.retries == 1
    assert len(slept) == 1


def test_rate_limit_advances_without_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """429は待たず次のキーへ(retry_afterがあっても待たない)。"""
    monkeypatch.setenv("P1_KEY", "k1"); monkeypatch.setenv("P1_KEY_2", "k2")
    providers = [_config("p1", "P1_KEY", 1)]
    scripts: dict[str, list[object]] = {"k1": [RateLimitError("429", status=429, retry_after=3.0)], "k2": [_ok_response()]}
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
    scripts: dict[str, list[object]] = {"k1": [BadRequestError("400", status=400)], "k2": [_ok_response()]}
    client, slept = _client(providers, scripts)
    res = _gen(client)
    assert res.retries == 1
    assert slept == []


def test_no_time_budget_stops_without_sending(monkeypatch: pytest.MonkeyPatch) -> None:
    """残り時間が安全マージン以下なら、送信せずに打ち切る(送ると制限時間を越えて強制終了される)."""
    monkeypatch.setenv("P1_KEY", "k1")
    monkeypatch.setenv("P2_KEY", "k2")
    providers = [_config("p1", "P1_KEY", 1), _config("p2", "P2_KEY", 2)]
    retry = RetrySettings(max_retries_per_key=2, safety_margin_seconds=2.0)
    scripts: dict[str, list[object]] = {"k1": [_ok_response()], "k2": [_ok_response("p2/model")]}
    client, slept = _client(providers, scripts, retry=retry, time_remaining=lambda: 1.0)
    with pytest.raises(AllProvidersExhausted) as info:
        _gen(client)
    assert info.value.attempts == 0
    assert slept == []
    assert scripts["k1"] and scripts["k2"]   # どちらにも送っていない


def test_request_timeout_is_clamped_to_remaining_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """リクエストのタイムアウトは min(設定の60秒, 残り時間 - 安全マージン) に切り詰める."""
    monkeypatch.setenv("P1_KEY", "k1")
    providers = [_config("p1", "P1_KEY", 1)]
    retry = RetrySettings(safety_margin_seconds=2.0)
    timeouts: list[float] = []
    scripts: dict[str, list[object]] = {"k1": [_ok_response(), _ok_response()]}

    def factory(config: ProviderConfig, transport: HttpTransport, key: str, model: str) -> _ScriptedProvider:
        timeouts.append(config.request_timeout_sec)
        return _ScriptedProvider(config, transport, key, scripts)

    remaining = [30.0]
    client = ResilientLLMClient(
        providers=providers, transport=_NullTransport(), retry=retry,
        provider_factory=factory,  # type: ignore[arg-type]
        sleep=lambda seconds: None, time_remaining=lambda: remaining[0],
    )
    _gen(client)
    remaining[0] = 100.0
    _gen(client)
    assert timeouts == [28.0, 60.0]   # 30 - 2 / 設定値の60のまま
    assert providers[0].request_timeout_sec == 60.0   # 元の設定は書き換えない


def test_server_error_backoff_is_clamped_then_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """5xxのバックオフは残り時間-マージンにクランプされ、再送も失敗すれば次プロバイダへ."""
    monkeypatch.setenv("P1_KEY", "k1")
    monkeypatch.setenv("P2_KEY", "k2")
    providers = [_config("p1", "P1_KEY", 1), _config("p2", "P2_KEY", 2)]
    retry = RetrySettings(max_retries_per_key=1, backoff_base_seconds=4.0, safety_margin_seconds=2.0)
    scripts: dict[str, list[object]] = {
        "k1": [ServerError("503", status=503), ServerError("503", status=503)],
        "k2": [_ok_response("p2/model")]}
    client, slept = _client(providers, scripts, retry=retry, time_remaining=lambda: 5.0)
    res = _gen(client)
    assert res.model_name == "p2/model"
    assert slept == [3.0]   # min(4.0, 5.0 - 2.0)


def test_rate_limited_sweep_waits_once_then_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """全組合せが429で全滅し、retry_afterが残り時間に収まるなら、1回だけ待ってもう1周する."""
    monkeypatch.setenv("P1_KEY", "k1")
    monkeypatch.setenv("P2_KEY", "k2")
    providers = [_config("p1", "P1_KEY", 1), _config("p2", "P2_KEY", 2)]
    scripts: dict[str, list[object]] = {
        "k1": [RateLimitError("429", status=429, retry_after=5.0), _ok_response("p1/model")],
        "k2": [RateLimitError("429", status=429, retry_after=2.0)]}
    client, slept = _client(providers, scripts, time_remaining=lambda: 100.0)
    res = _gen(client)
    assert slept == [2.0]            # 観測した最短の retry_after だけ待つ
    assert res.model_name == "p1/model"
    assert res.retries == 2          # 1周目の2回を通算で計上


def test_rate_limit_longer_than_remaining_time_is_not_waited(monkeypatch: pytest.MonkeyPatch) -> None:
    """retry_afterが残り時間に収まらない(日次枠切れ等)なら、待たずに全滅を返す."""
    monkeypatch.setenv("P1_KEY", "k1")
    providers = [_config("p1", "P1_KEY", 1)]
    scripts: dict[str, list[object]] = {"k1": [RateLimitError("429", status=429, retry_after=500.0)]}
    client, slept = _client(providers, scripts, time_remaining=lambda: 30.0)
    with pytest.raises(AllProvidersExhausted) as info:
        _gen(client)
    assert slept == []
    assert info.value.attempts == 1
    assert isinstance(info.value.__cause__, RateLimitError)


def test_second_sweep_is_not_tried_without_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """429以外(認証エラー等)で全滅したら、待っても直らないので2周目はしない."""
    monkeypatch.setenv("P1_KEY", "k1")
    providers = [_config("p1", "P1_KEY", 1)]
    scripts: dict[str, list[object]] = {"k1": [AuthenticationError("401", status=401), _ok_response()]}
    client, slept = _client(providers, scripts, time_remaining=lambda: 100.0)
    with pytest.raises(AllProvidersExhausted) as info:
        _gen(client)
    assert slept == []
    assert info.value.attempts == 1
    assert scripts["k1"]   # 2回目は送っていない


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


def test_failed_combo_is_demoted_on_next_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """空応答を返したモデルは、同じタスクの次の呼び出しでは後回しにされる."""
    monkeypatch.setenv("P1_KEY", "k1")
    monkeypatch.setenv("P2_KEY", "k2")
    providers = [_config("p1", "P1_KEY", 1), _config("p2", "P2_KEY", 2)]
    scripts: dict[str, list[object]] = {
        "k1": [EmptyResponseError("empty")],
        "k2": [_ok_response("p2/model"), _ok_response("p2/model")]}
    client, _ = _client(providers, scripts)
    _gen(client)
    second = _gen(client)
    assert second.model_name == "p2/model"
    assert second.retries == 0   # p1を飛ばしてp2が1回目で成功


def test_demoted_combo_is_still_tried_last(monkeypatch: pytest.MonkeyPatch) -> None:
    """後回しにした組合せも捨てはしない。ほかが全部だめなら最後に試し、成功すれば後回しを解除する."""
    monkeypatch.setenv("P1_KEY", "k1")
    monkeypatch.setenv("P2_KEY", "k2")
    providers = [_config("p1", "P1_KEY", 1), _config("p2", "P2_KEY", 2)]
    scripts: dict[str, list[object]] = {
        "k1": [BadRequestError("400", status=400), _ok_response("p1/model"), _ok_response("p1/model")],
        "k2": [_ok_response("p2/model"), ServerError("503", status=503)]}
    retry = RetrySettings(max_retries_per_key=0)
    client, _ = _client(providers, scripts, retry=retry)
    assert _gen(client).model_name == "p2/model"   # p1は400で後回しに
    assert _gen(client).model_name == "p1/model"   # p2が503 -> 後回しのp1を最後に試して成功
    third = _gen(client)
    assert third.model_name == "p1/model"          # 成功したので後回しが解除され、先頭に戻った
    assert third.retries == 0


def test_rotate_prefers_another_provider_next_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """rotate() は直前に成功したプロバイダを後回しにする。全部後回しにしたら古い順に戻る(A-15)."""
    monkeypatch.setenv("P1_KEY", "k1")
    monkeypatch.setenv("P2_KEY", "k2")
    providers = [_config("p1", "P1_KEY", 1), _config("p2", "P2_KEY", 2)]
    scripts: dict[str, list[object]] = {
        "k1": [_ok_response("p1/model"), _ok_response("p1/model")],
        "k2": [_ok_response("p2/model")]}
    client, _ = _client(providers, scripts)
    assert _gen(client).model_name == "p1/model"
    client.rotate()
    assert _gen(client).model_name == "p2/model"   # p1を後回しにしたのでp2が先
    client.rotate()
    assert _gen(client).model_name == "p1/model"   # p2も後回しにしたので、先に後回しにしたp1から戻る


def test_rotate_before_any_success_does_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("P1_KEY", "k1")
    client, _ = _client([_config("p1", "P1_KEY", 1)], {"k1": [_ok_response("p1/model")]})
    client.rotate()
    assert _gen(client).model_name == "p1/model"

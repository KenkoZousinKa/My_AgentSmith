"""複数プロバイダ、複数キーを束ね、冗長性と耐障害性を提供するLLMクライアント

provider(1キーで1リクエスト)の上位レイヤ。
priorityに応じてprovider内で複数のキーを回し、型付きエラーに応じて
1. バックオフ(同一キー)再送 -> 2. 次のモデル -> 3. 次のキー -> 4. 次のプロバイダ
の順にフォールバックする。
すべて尽きたらAllProvidersExhausted返す。
上位Orchestratorはクラッシュさせず、success=Falseで返す。
(バックオフ: 通信やAPIの呼び出しが失敗した際に少し待機してから再試行する仕組み。リトライの時間調整。)
(フォールバック: 処理や通信に失敗した際に別の手段や代替案に切り替えること。リトライでだめな時の代替処理。)

- RateLimitError
    レートリミットに達したことを示す。バックオフせずに即次のキーへ。
- ServerError / TransportError
    一過性。バックオフして同一キーで再送。
- AuthenticationError
    認証に失敗したことを示す。バックオフせずに即次のキーへ。
- BadRequestError
    リクエスト不正。こちらの責任。バックオフせずに即次のキーへ。
- EmptyResponseError
    レスポンスが空だった場合。消費したトークンを記録してバックオフせずに即次のキーへ。
- AllProvidersExhausted
    すべてのプロバイダ / すべてのキーを試しても成功しなかった場合に発生する例外。
    上位のOrchestratorはこの例外を捕まえて、success=Falseで返す。

- time_remainingを渡すと、待機がMBPPのハード制限を食いつぶさないように残予算にクランプする。
残予算がなければそのキーを諦めて次のキーへ。
backoff / retry の設定はRetrySettings(config.json)。

- 下記を提供
AllProvidersExhausted
ResilientLLMClient def _wait_seconds def generate()
"""
import time
import logging
from collections.abc import Callable

from src.agent.llm.key_manager import resolve_api_keys
from src.agent.llm.provider.openai_compat import OpenAICompatProvider
from src.agent.llm.provider.provider import (
    AuthenticationError,
    BadRequestError,
    EmptyResponseError,
    LLMError,
    LLMProvider,
    LLMResponse,
    ProviderConfig,
    RateLimitError,
    ServerError
)
from src.agent.llm.transport.transport import HttpTransport, TransportError
from src.config.settings import RetrySettings

_LOGGER = logging.getLogger("agent.llm")

# (config, transport, api_key, model) -> LLMProvider を生成するファクトリ型。
# 既定はOpenAICompatProvider
ProviderFactory = Callable[[ProviderConfig, HttpTransport, str, str], LLMProvider]
# 全ローテーションの最大回数。
_MAX_SWEEPS = 2
# 同じタスク内でリトライしても無駄な組み合せ。
# (provider_name, api_key, model_name)
_Combo = tuple[str, int, str]
# この周回で試す組み合せ。
# (provider_config, api_key_index, model_name, attempt_on_key)
_Candidate = tuple[ProviderConfig, int, str, str]


class AllProvidersExhausted(LLMError):
    """全プロバイダ・全キーを試しても成功しなかったことを表す例外クラス.

    上位のOrchestratorはこの例外を捕まえて、total_input/output_tokensに加算する。
    Attributes:
        attempts (int): 試行回数。成功までのリトライを含む。
            上位のOrchestratorはこの例外を捕まえて、total_requestsに加算する。
        retry_after (float | None): 周回中に観測した最短の待機秒数。Noneなら429なし。
        input_tokens (int): 失敗した試行中(空応答)にプロバイダ側で消費した入力トークン数。
        output_tokens (int): 失敗した試行中(空応答)にプロバイダ側で消費した出力トークン数。
    """
    def __init__(
        self,
        message: str,
        attempts: int = 0,
        retry_after: float | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0
    ) -> None:
        super().__init__(message, attempts, retry_after, input_tokens, output_tokens)
        self.attempts = attempts
        self.retry_after = retry_after
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens

    def __str__(self) -> str:
        """ログを見やすくするためにメッセージのみを返す。"""
        return str(self.args[0])


class ResilientLLMClient:
    """複数プロバイダ / 複数キーで冗長性と耐障害性を提供するProviderの上位クライアント.

    OrchestratorはProviderと同じgenerate(messages, stop_sequences, max_tokens)を呼び出すだけでよい。
    """

    def __init__(
        self,
        providers: list[ProviderConfig],
        transport: HttpTransport,
        retry: RetrySettings,
        provider_factory: ProviderFactory = OpenAICompatProvider,
        sleep: Callable[[float], None] = time.sleep,
        time_remaining: Callable[[], float] | None = None,
        logger: logging.Logger | None = None
    ) -> None:
        """依存を注入して初期化。

        Args:
            providers (list[ProviderConfig]): プロバイダ設定のリスト。優先度順に並べる。
            transport (HttpTransport): HTTP POST で送信を担当するTransportクラス
            retry (RetrySettings): バックオフ / リトライの設定
            provider_factory (ProviderFactory): ProviderConfigからLLMProviderを生成するファクトリ関数
            sleep (Callable[[float], None]): 待機関数。time.sleepの代替を注入可能。
            time_remaining (Callable[[], float] | None): 残り時間を返す関数。Noneなら無制限。
            logger (logging.Logger | None): ロガー。Noneならデフォルトロガーを使用。
        """
        self._providers = providers
        self._transport = transport
        self._retry = retry
        self._provider_factory = provider_factory
        self._sleep = sleep
        self._time_remaining = time_remaining
        self._log = logger if logger is not None else _LOGGER
        # 1周目で一過性でない失敗をした組み合わせ(認証 / 空応答 / 解釈できない応答)を記録し、1タスクの間は後回し
        self._demoted: set[_Combo] = set()

    def _budget(self) -> float | None:
        """残り時間から安全マージンを引いた秒数を返す.

        generate()内の _sweep_wait() / _request_timeout() / _wait_seconds()で使う。
        """
        if self._time_remaining is None:
            return None
        return self._time_remaining() - self._retry.safety_margin_seconds

    def _wait_seconds(self, attempt_on_key: int) -> float | None:
        """一過性のエラー(500系 / ネットワークエラー)でバックオフする秒数を返す。残予算がなければNone.

        指数バックオフ(base * 2^n)をmaxまでクランプする。
        generate() -> _sweep() -> _wait_seconds() の順に呼ばれる。

        Args:
            attempt_on_key (int): 同一キーでのリトライ回数。0から始まる。

        Returns:
            float | None: バックオフする秒数。残予算がなければNone。
        """
        wait: float = min(self._retry.backoff_base_seconds * (2 ** attempt_on_key), self._retry.backoff_max_seconds)

        # 残り時間から安全マージンを引いた秒数を取得
        budget = self._budget()
        if budget is None:
            return wait

        # 予算が0以下なら、残予算がないのでNoneを返す。
        if budget <= 0:
            return None

        return wait

    def _request_timeout(self, config: ProviderConfig) -> float | None:
        """このリクエストに使えるHTTPタイムアウト秒数を返す。残予算がなければNone.

        プロバイダ設定のタイムアウトをそのまま使うと残り時間が少ない時に1リクエストの待ち時間で
        タスクの制限時間を超え強制終了されるので、残り時間、安全マージンにクランプする。
        generate() -> _sweep() -> _request_timeout() の順に呼ばれる。

        Args:
            config (ProviderConfig): 送信先のプロバイダ設定。request_timeoutを参照する

        Returns:
            float | None: このリクエストに使えるHTTPタイムアウト秒数。残り時間がない場合はNone。
        """
        # 残り時間から安全マージンを引いた秒数を取得
        budget = self._budget()
        if budget is None:
            return config.request_timeout_sec

        # 1秒未満の残り時間はリクエストを無駄にするので送らせない。
        if budget <= 1.0:
            return None

        return config.request_timeout_sec

    def _sweep_wait(self, retry_after: float | None) -> float | None:
        """全組み合わせ全滅のあと、もう一周するために待つ秒数を返す。残予算がなければNone.

        待って解決するのはレート制限(429)だけなので、周回中に429が出なければ(retry-afterがNone)Noneを返す。
        観測していれば、その最短待機秒数が残り時間に収まる時に限り待つ。
        収まらなければ終了。
        generate() -> _sweep_wait() の順に呼ばれる。

        Args:
            retry_after (float | None): 周回中に観測した最短の待機秒数。Noneなら429なし。

        Returns:
            float | None: 待つべき秒数。残予算がなければNone。
        """
        # 429が観測されていなければ、もう一周しても無駄なのでNoneを返す。
        if retry_after is None:
            return None

        # 429が観測されていて、残予算があれば待つ。
        budget = self._budget()
        if budget is None:
            return retry_after

        # 予算が0以下、または待機秒数が予算を超える場合はNoneを返す。
        if budget <= 0 or retry_after > budget:
            return None

        return retry_after

    def generate(
        self,
        messages: list[dict[str, str]],
        stop_sequences: list[str],
        max_tokens: int
    ) -> LLMResponse:
        """粘り付きで1回の生成を行い、成功したLLMResponseを返す.

        1周目は全プロバイダ / 全キー / 全モデルを優先度順に試す。
        全滅かつ原因が一過性(残り時間で解除されるレート制限)なら2周目を試す。
        成功までに空応答などで消費したトークンは、成功したレスポンスの使用量に足して返す。

        Args:
            messages (list[dict[str, str]]): LLMに送信するメッセージ。OpenAI互換の形式で、roleとcontentを持つ辞書のリスト。
            stop_sequences (list[str]): 生成を停止する文字列郡(既定は ["<end_code>"])
            max_tokens (int): 生成する最大トークン数

        Returns:
            LLMResponse: 生成テキストと使用量、計測値をまとめた結果。

        Raises:
            AllProvidersExhausted: すべてのプロバイダ / すべてのキーを試しても成功しなかった場合に発生する例外。
        """
        attempts = 0
        # 失敗した試行中(空応答)にプロバイダ側で消費したトークン数を集計する。
        # 成功したら成功レスポンスに、全滅したら例外に足して上位へ戻して過小計上を避ける。
        wasted = [0, 0]
        # wasted_input_tokens = 0
        # wasted_output_tokens = 0
        last_error: BaseException | None = None

        for sweep in range(_MAX_SWEEPS):
            try:
                response = self._sweep(messages, stop_sequences, max_tokens, attempts, wasted)

            except AllProvidersExhausted as exhausted:
                # 通算の試行回数を引き継いで、次の周回で再開する。
                attempts = exhausted.attempts
                # AllProvidersExhaustedの原因となった最後の例外を取得。
                last_error = exhausted.__cause__ or exhausted
                # リトライの前に残予算の計算
                wait = self._sweep_wait(exhausted.retry_after)
                # 一周目での失敗が一過性(残り時間で解除されるレート制限)で、残予算があればもう一周する。
                if sweep + 1 >= _MAX_SWEEPS or wait is None:
                    break
                self._log.warning(
                    "all providers / keys / models exhausted after %d attempt(s); "
                    "waiting %.1fs for the rate limit to clear, then retrying once.",
                    attempts,
                    wait
                )
                self._sleep(wait)
            else:
                if wasted[0] or wasted[1]:
                    response = response.model_copy(
                        update={
                            "input_tokens": response.input_tokens + wasted[0],
                            "output_tokens": response.output_tokens + wasted[1]
                        }
                    )
                return response

        # すべての周回で成功しなかった場合は、AllProvidersExhaustedを送出
        raise AllProvidersExhausted(
            f"All providers / keys / models exhausted after {attempts} attempt(s).",
            attempts=attempts,
            input_tokens=wasted[0],
            output_tokens=wasted[1]
        ) from last_error

    def _candidates(self) -> list[_Candidate]:
        """この周回で試す組み合わせのリストを優先度順に返す。

        一過性でない失敗を起こした時は、捨てずに最後に回す。
        Returns:
            list[_Candidate]: (provider_config, api_key_index, model_name, attempt_on_key) のリスト。
        """
        preferred: list[_Candidate] = []
        demoted: list[_Candidate] = []

        # 優先度順に並べたすべてのプロバイダを試す
        for config in self._providers:
            # config.keys_envからAPIキーを取得する。もしkeysが空なら次のプロバイダへ。
            keys = resolve_api_keys(config.keys_env)
            # もしkeysが空なら、次のプロバイダへ。
            if not keys:
                self._log.warning(
                    "provider=%s skipped: no API keys in %s",
                    config.name,
                    config.keys_env
                )
                continue

            # すべてのキーとモデルを順番に並べる。1組み合わせ1リクエスト。
            for key_number, key in enumerate(keys, start=1):
                for model in config.models:
                    candidate = (config, key_number, key, model)
                    # 一過性でない失敗を起こした組み合わせは後回しにする。
                    if (config.name, key_number, model) in self._demoted:
                        demoted.append(candidate)
                    else:
                        preferred.append(candidate)

        return preferred + demoted

    def _sweep(
        self,
        messages: list[dict[str, str]],
        stop_sequences: list[str],
        max_tokens: int,
        attempts_so_far: int,
        wasted: list[int]
    ) -> LLMResponse:
        """全プロバイダ / 全キー / 全モデルを優先度順に1回試す.

        Args:
            messages (list[dict[str, str]]): LLMに送信するメッセージ。OpenAI互換の形式で、roleとcontentを持つ辞書のリスト。
            stop_sequences (list[str]): 生成を停止する文字列郡(既定は ["<end_code>"])
            max_tokens (int): 生成する最大トークン数
            attempts_so_far (int): これまでの試行回数
            wasted (list[int]): 失敗した試行中(空応答)にプロバイダ側で消費したトークン数を集計するリスト。wasted[0]は入力、wasted[1]は出力。

        Returns:
            LLMResponse: 生成テキストと使用量、計測値をまとめた結果。

        Raises:
            AllProvidersExhausted: すべてのプロバイダ / すべてのキーを試しても成功しなかった場合に発生する例外。
        """
        attempts = attempts_so_far
        last_error: BaseException | None = None
        # 周回中に観測した429の待機秒数。retry_afterがない429はバックオフ上限秒で代用し
        # 最短のものを待てば解けるかもしれない秒数として上位のgenerate()に返す。
        rate_limit_waits: list[float] = []

        for config, key_number, key, model in self._candidates():
            combo = (config.name, key_number, model)

            # 1キーでのリトライループ。バックオフ再送 -> 次の組み合せの順にフォールバック
            for attempt_on_key in range(self._retry.max_retries_per_key + 1):
                # 残り時間に収まるタイムアウトを計算。時間がなければ周回自体打ち切る。
                timeout = self._request_timeout(config)
                if timeout is None:
                    raise AllProvidersExhausted(
                        f"No time budget left after {attempts} attempt(s).",
                        attempts=attempts
                    ) from last_error

                # timeoutを差し替えてProviderを生成して、generate()を呼ぶ。
                # _provider_factoryは、ProviderConfigからLLMProviderを生成する
                provider = self._provider_factory(
                    config.model_copy(update={"request_timeout_sec": timeout}),
                    self._transport,
                    key,
                    model
                )
                attempts += 1
                try:
                    response = provider.generate(messages, stop_sequences, max_tokens)

                # 1. RateLimitError(429)はバックオフせずに次のモデルへ。
                except RateLimitError as error:
                    last_error = error
                    rate_limit_waits.append(
                        error.retry_after if error.retry_after is not None else self._retry.backoff_max_seconds
                    )
                    self._log.warning(
                        "provider=%s key#%d model=%s attempts=%d rate limited (retry_after=%s); advance, no backoff.",
                        config.name,
                        key_number,
                        model,
                        attempts,
                        error.retry_after
                    )
                    break

                # 2. ServerError / 3. TransportError は一過性(500系 / ネットワークエラー)。バックオフして同一キーで再送。
                except (ServerError, TransportError) as error:
                    last_error = error
                    # 1つのキーでのリトライ回数が上限に達したら、次のキーへ。
                    if attempt_on_key >= self._retry.max_retries_per_key:
                        self._log.warning(
                            "provider=%s key#%d model=%s attempts=%d %s; give up key",
                            config.name,
                            key_number,
                            model,
                            attempts,
                            type(error).__name__
                        )
                        break

                    # バックオフ秒数を計算し、残予算がなければバックオフせずに次のモデルへ。
                    wait = self._wait_seconds(error, attempt_on_key)
                    if wait is None:
                        self._log.warning(
                            "provider=%s key#%d model=%s attempts=%d %s; no time budget, give up key.",
                            config.name,
                            key_number,
                            model,
                            attempts,
                            type(error).__name__
                        )
                        break

                    # バックオフ秒数待機し、バックオフ、同一キーで再送する。
                    self._log.warning(
                        "provider=%s key#%d model=%s attempts=%d %s; backoff %.1fs.",
                        config.name,
                        key_number,
                        model,
                        attempts,
                        type(error).__name__,
                        wait
                    )
                    self._sleep(wait)

                # 4. 認証エラー(401 / 403)は次のキーへ。バックオフせずに次のモデルへ。
                except AuthenticationError as error:
                    last_error = error
                    self._demoted.add(combo)
                    self._log.warning(
                        "provider=%s key#%d model=%s attempts=%d auth/quota; next combo.",
                        config.name,
                        key_number,
                        model,
                        attempts
                    )
                    break

                # 5. BadRequestErrorはリクエスト不正。バックオフせずに次のモデルへ。
                except BadRequestError as error:
                    last_error = error
                    self._demoted.add(combo)
                    self._log.error(
                        "provider=%s key#%d model=%s bad request; skip combo: %s.",
                        config.name,
                        key_number,
                        model,
                        error
                    )
                    break

                # 6. EmptyResponseErrorは、レスポンスが空だった場合。消費したトークンを記録してバックオフせずに次のモデルへ。
                except EmptyResponseError as error:
                    last_error = error
                    self._demoted.add(combo)
                    wasted[0] += error.input_tokens
                    wasted[1] += error.output_tokens
                    self._log.warning(
                        "provider=%s key#%d model=%s attempts=%d empty response(wasted in=%d, out=%d); next combo.",
                        config.name,
                        key_number,
                        model,
                        attempts,
                        error.input_tokens,
                        error.output_tokens
                    )
                    break

                # 7. その他のLLMError(レスポンスの解釈失敗など)はバックオフせずに次のモデルへ。
                # privider._parse_response()でLLMからのレスポンスが取得できない時、LLMErrorが発生する
                # OpenAI互換のレスポンスがJSONでない、choices[0]が存在しない、contentが空など。
                # 今後の拡張でLLMErrorの子孫クラスを追加する場合もここで捕らえる。
                except LLMError as error:
                    last_error = error
                    self._demoted.add(combo)
                    self._log.error(
                        "provider=%s key#%d model=%s attempts=%d LLMError; next combo: %s.",
                        config.name,
                        key_number,
                        model,
                        attempts,
                        error
                    )
                    break

                # エラーが発生しなければ成功。LLMResponseを返す。
                else:
                    if attempts > 1:
                        response = response.model_copy(update={"retries": attempts - 1})

                    # 成功した組み合わせは、次のタスクで後回しにしないようにする。
                    self._demoted.discard(combo)
                    self._log.info(
                        "provider=%s key#%d model=%s success after %d attempt(s)",
                        config.name,
                        key_number,
                        model,
                        attempts
                    )
                    return response

        # すべてのプロバイダ / すべてのキーを試しても成功しなかった場合は、AllProvidersExhaustedを送出
        # 上位のOrchestratorはこの例外を捕まえて、success=Falseで返す。
        # attemptsはリトライを含む総試行回数
        raise AllProvidersExhausted(
            f"All providers/keys exhausted after {attempts} attempt(s).",
            attempts=attempts,
            retry_after=min(rate_limit_waits) if rate_limit_waits else None
        ) from last_error

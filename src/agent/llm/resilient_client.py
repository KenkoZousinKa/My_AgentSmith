"""複数プロバイダ、複数キーを束ね、冗長性と耐障害性を提供するLLMクライアント

provider(1キーで1リクエスト)の上位レイヤ。
priorityに応じてprovider内で複数のキーを回し、型付きエラーに応じて
1. バックオフ(同一キー)再送 -> 2. 次のキー -> 3. 次のプロバイダ
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
ResilientLLMClient def _wait_second def generate()

Todo:
    - [ ] A-04で待ち時間、タイムアウト、後回しで_sweep / _candidatesに分割、watedは[入力、出力]のリストで受け渡す。
    - [ ]上記変更でwasted_input/output_tokensを変更する。
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


class AllProvidersExhausted(LLMError):
    """全プロバイダ・全キーを試しても成功しなかったことを表す例外クラス.

    上位のOrchestratorはこの例外を捕まえて、total_input/output_tokensに加算する。
    Attributes:
        attempts (int): 試行回数。成功までのリトライを含む。
            上位のOrchestratorはこの例外を捕まえて、total_requestsに加算する。
        input_tokens (int): 失敗した試行中(空応答)にプロバイダ側で消費した入力トークン数。
        output_tokens (int): 失敗した試行中(空応答)にプロバイダ側で消費した出力トークン数。
    """
    def __init__(self, message: str, attempts: int = 0, input_tokens: int = 0, output_tokens: int = 0) -> None:
        super().__init__(message, attempts, input_tokens, output_tokens)
        self.attempts = attempts
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens

    def __str__(self) -> str:
        """ログを見やすくするためにメッセージのみを返す。"""
        return str(self.args[0])


class ResilientLLMClient:
    """複数プロバイダ / 複数キーで冗長性と耐障害性を提供するProviderの上位クライアント.

    OrchestratorはProviderと同じgengerate(messages, stop_sequences, max_tokens)を呼び出すだけでよい。
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

    def _wait_seconds(self, error: BaseException, attempt_on_key: int) -> float | None:
        """次の再送までの待機秒数を返す。残予算がなければNone.

        429でretry_afterがあればそれを優先する。
        無ければ指数バックオフ(base * 2^n をmaxまでクランプ)。
        time_remainingがあれば残予算 - safety_margin_secondsにクランプする。
        0以下ならNoneを返す。
        """
        if isinstance(error, RateLimitError) and error.retry_after is not None:
            wait = error.retry_after
        else:
            wait = min(self._retry.backoff_base_seconds * (2 ** attempt_on_key), self._retry.backoff_max_seconds)

        if self._time_remaining is not None:
            budget = self._time_remaining() - self._retry.safety_margin_seconds
            if budget <= 0:
                return None
            wait = min(wait, budget)

        return wait

    def generate(
        self,
        messages: list[dict[str, str]],
        stop_sequences: list[str],
        max_tokens: int
    ) -> LLMResponse:
        """粘り付きで1回の生成を行い、成功したLLMResponseを返す.

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
        last_error: BaseException | None = None

        # 失敗した試行中(空応答)にプロバイダ側で消費したトークン数を集計する。
        # 成功したら成功レスポンスに、全滅したら例外に足して上位へ戻して過小計上を避ける。
        wasted_input_tokens = 0
        wasted_output_tokens = 0

        # 優先度順に並べたすべてのプロバイダを試す
        for config in self._providers:
            # config.keys_envからAPIキーを取得する。もしkeysが空なら、次のプロバイダへ。
            keys = resolve_api_keys(config.keys_env)
            # もしkeysが空なら、次のプロバイダへ。
            if not keys:
                self._log.warning(
                    "provider=%s skipped: no API keys in %s",
                    config.name,
                    config.keys_env
                )
                continue

            # すべてのキーを順番に試す。1キーで1リクエスト。
            for key_number, key in enumerate(keys, start=1):

                # すべてのモデルを順番に試す。1モデルで1リクエスト。
                for model in config.models:
                    # Providerを生成して、generate()を呼ぶ。
                    # _provider_factoryは、ProviderConfigからLLMProviderを生成する
                    provider = self._provider_factory(config, self._transport, key, model)

                    # 1キーでのリトライループ。バックオフ再送 -> 次キー -> 次モデル -> 次プロバイダ の順にフォールバックする。
                    for attempt_on_key in range(self._retry.max_retries_per_key + 1):
                        # リトライを含む総試行回数。上位のOrchestratorがtotal_requestsに加算する。
                        attempts += 1

                        try:
                            response = provider.generate(messages, stop_sequences, max_tokens)

                        # 1. RateLimitError(429)は次のキーへ。バックオフはしない。
                        except RateLimitError as error:
                            last_error = error
                            self._log.warning(
                                "provider=%s key#%d attempts=%d rate limited (retry_after=%s); advance, no backoff.",
                                config.name,
                                key_number,
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
                                    "provider=%s key#%d attempts=%d %s; give up key",
                                    config.name,
                                    key_number,
                                    attempts,
                                    type(error).__name__
                                )
                                break

                            # バックオフ秒数を計算し、残予算がなければバックオフせずに次のキーへ。
                            wait = self._wait_seconds(error, attempt_on_key)
                            if wait is None:
                                self._log.warning(
                                    "provider=%s key#%d attempts=%d %s; no time budget, give up key.",
                                    config.name,
                                    key_number,
                                    attempts,
                                    type(error).__name__
                                )
                                break

                            # バックオフ秒数待機し、バックオフ、同一キーで再送する。
                            self._log.warning(
                                "provider=%s key#%d attempts=%d %s; backoff %.1fs.",
                                config.name,
                                key_number,
                                attempts,
                                type(error).__name__,
                                wait
                            )
                            self._sleep(wait)

                        # 4. 認証エラー(401 / 403)は次のキーへ。バックオフせずに次のキーへ。
                        except AuthenticationError as error:
                            last_error = error
                            self._log.warning(
                                "provider=%s key#%d attempts=%d auth/quota; next key.",
                                config.name,
                                key_number,
                                attempts
                            )
                            break

                        # 5. BadRequestErrorはリクエスト不正。バックオフせずに次のキーへ。
                        except BadRequestError as error:
                            last_error = error
                            self._log.error(
                                "provider=%s key#%d bad request; skip key: %s.",
                                config.name,
                                key_number,
                                error
                            )
                            break

                        # 6. EmptyResponseErrorは、レスポンスが空だった場合。消費したトークンを記録してバックオフせずに次のキーへ。
                        except EmptyResponseError as error:
                            last_error = error
                            wasted_input_tokens += error.input_tokens
                            wasted_output_tokens += error.output_tokens
                            self._log.warning(
                                "provider=%s key#%d attempts=%d empty response; next key.",
                                config.name,
                                key_number,
                                attempts
                            )
                            break

                        # 7. その他のLLMError(レスポンスの解釈失敗など)はバックオフせずに次のキーへ。
                        # 現状LLMHTTPError系のみ?LLMHTTPErrorは送出されないのでここには来ない？
                        except LLMError as error:
                            last_error = error
                            self._log.error(
                                "provider=%s key#%d attempts=%d LLMError; next key: %s.",
                                config.name,
                                key_number,
                                attempts,
                                error
                            )
                            break

                        # エラーが発生しなければ成功。LLMResponseを返す。
                        else:
                            if attempts > 1:
                                response = response.model_copy(update={"retries": attempts - 1})

                            # 失敗した試行中(空応答)にプロバイダ側で消費したトークン数を成功レスポンスに加算する。
                            if wasted_input_tokens or wasted_output_tokens:
                                response = response.model_copy(
                                    update={
                                        "input_tokens": response.input_tokens + wasted_input_tokens,
                                        "output_tokens": response.output_tokens + wasted_output_tokens
                                    }
                                )

                            self._log.info(
                                "provider=%s key#%d success after %d attempt(s)",
                                config.name,
                                key_number,
                                attempts
                            )
                            return response

        # すべてのプロバイダ / すべてのキーを試しても成功しなかった場合は、AllProvidersExhaustedを送出
        # 上位のOrchestratorはこの例外を捕まえて、success=Falseで返す。
        # attemptsはリトライを含む総試行回数
        raise AllProvidersExhausted(
            f"All providers/keys exhausted after {attempts} attempt(s).",
            attempts=attempts,
            input_tokens=wasted_input_tokens,
            output_tokens=wasted_output_tokens
        ) from last_error

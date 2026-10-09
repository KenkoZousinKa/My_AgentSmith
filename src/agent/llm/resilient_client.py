"""複数プロバイダ、複数キーを束ね、冗長性と耐障害性を提供するLLMクライアント

provider(1キーで1リクエスト)の上位レイヤ。
priorityに応じてprovider内で複数のキーを回し、
型付きエラーに応じて
バックオフ再送 -> 次キー -> 次プロバイダ
の順にフォールバックする。
すべて尽きたらAllProvidersExhausted返す。
上位Orchestratorはクラッシュさせず、success=Falseで返す。

- RateLimitError / ServerError / TransportError
    一過性。バックオフして同一キーで再送。
- AuthenticationError
    同一キー再送は無意味。即次のキーへ。
- BadRequestError
    リクエスト不正。他キー / 他プロバイダでも直らないので即送出。

time_remainingを渡すと、待機がMBPPのハード制限を食いつぶさないように
残予算にクランプする。
残予算がなければそのキーを諦めて次のキーへ。
backoff / retry の設定はRetrySettings(config.json)。
"""
import time
import logging
from collections.abc import Callable

from src.agent.llm.key_manager import resolve_api_keys
from src.agent.llm.provider.openai_compat import OpenAICompatProvider
from src.agent.llm.provider.provider import (
    AuthenticationError,
    BadRequestError,
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

# (config, transport, api_key) -> LLMProvider を生成するファクトリ型。
# 既定はOpenAICompatProvider
ProviderFactory = Callable[[ProviderConfig, HttpTransport, str], LLMProvider]


class AllProvidersExhausted(LLMError):
    """全プロバイダ・全キーを試しても成功しなかったことを表す例外クラス."""


class ResilientLLMClient:
    """複数プロバイダ / 複数キーで冗長性と耐障害性を提供するProviderの上位クライアント.

    OrchestratorはProviderと同じ
    gengerate(messages, stop_sequences, max_tokens)を呼び出すだけでよい。
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
            BadRequestError: リクエスト不正。プロバイダ / キーを変えても直らないので即送出。
        """
        attempts = 0
        last_error: BaseException | None = None

        for config in self._providers:
            keys = resolve_api_keys(config.keys_env)
            if not keys:
                self._log.warning(
                    "provider=%s skipped: no API keys in %s",
                    config.name,
                    config.keys_env
                )
                continue

            for key_number, key in enumerate(keys, start=1):
                provider = self._provider_factory(config, self._transport, key)

                for attempt_on_key in range(self._retry.max_retries_per_key + 1):
                    attempts += 1

                    try:
                        response = provider.generate(messages, stop_sequences, max_tokens)

                    except (RateLimitError, ServerError, TransportError) as error:
                        last_error = error
                        if attempt_on_key >= self._retry.max_retries_per_key:
                            self._log.warning(
                                "provider=%s key#%d attempts=%d %s; give up key",
                                config.name,
                                key_number,
                                attempts,
                                type(error).__name__
                            )
                            break

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

                        self._log.warning(
                            "provider=%s key#%d attempts=%d %s; backoff %.1fs.",
                            config.name,
                            key_number,
                            attempts,
                            type(error).__name__,
                            wait
                        )
                        self._sleep(wait)

                    except AuthenticationError as error:
                        last_error = error
                        self._log.warning(
                            "provider=%s key#%d attempts=%d auth/quota; next key.",
                            config.name,
                            key_number,
                            attempts
                        )
                        break

                    except BadRequestError:
                        self._log.error(
                            "provider=%s key#%d bad request; aborting.",
                            config.name,
                            key_number
                        )
                        raise

                    else:
                        if attempts > 1:
                            response = response.model_copy(update={"retries": attempts - 1})

                        self._log.info(
                            "provider=%s key#%d success after %d attempt(s)",
                            config.name,
                            key_number,
                            attempts
                        )
                        return response

        raise AllProvidersExhausted(
            f"All providers/keys exhausted after {attempts} attempt(s).") from last_error

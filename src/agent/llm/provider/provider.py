"""LLMプロバイダの抽象クラスと設定情報を定義するモジュール。

1リクエストを送って結果 / 例外を返すだけ。
generate()にリクエスト組み立て -> 送信 -> 計測 -> レスポンス整形の共通フローを実装し、
プロバイダの固有差分を _build_request() / _parse_response()のフックに実装する。
認証、リトライ、キーローテーション、フォールバックなどの機能はProvider / KeyManagerが担当。
実際のHTTP送信は HTTPTransportが担当する。

OpenRouterProvider / GroqProvider / TogetherProvider / FireWorksProvider / GeminiProvider 等
具体的なプロバイダは、この抽象クラスを継承して実装する。
プロバイダURL / モデル名 / キー郡などはJSONか.envで設定し、コードの変更なしでモデルを差し替えて
ベンチマークを実行できるようにする。
"""
import time
from typing import Any
from abc import ABC, abstractmethod
from pydantic import BaseModel, ConfigDict

from src.agent.llm.transport.transport import HttpTransport, HttpResponse


class ProviderConfig(BaseModel):
    """LLMプロバイダ一件分の設定情報.(provider.jsonの1要素に相当)

    Attributes:
        name (str): プロバイダ名。openrouter / groq / together / fireworks / gemini など。
        provider_url (str): プロバイダのAPIエンドポイントURL。
        model (str): 使用するモデルの名前。識別子。"qwen/qwen-7b-chat"など。
        keys_env (str): APIキーを格納した環境変数名。
        priority (int): プロバイダのフォールバック優先度。小さいほど優先度が高い。
        request_timeout_sec (float): HTTPリクエストのタイムアウト秒数。デフォルト60秒。MBPPの120秒にあわせる。
        additional_params (dict[str, Any]): プロバイダ固有のbodyに足す追加パラメータ。必要に応じて使用する。
    """
    model_config = ConfigDict(extra="forbid")

    name: str
    provider_url: str
    model: str  # API body / provider.jsonのキーと同名
    keys_env: str
    priority: int = 1
    request_timeout_sec: float = 60.0
    additional_params: dict[str, Any] = {}


class LLMResponse(BaseModel):
    """1回のLLM生成の結果。StepMetricsへ直結.

    Attributes:
        text (str): コード抽出前の生のレスポンス文字列。LLMの出力をそのまま保持する。
        input_tokens (int): 入力、プロンプトのトークン数。usage.pyで集計する。
        output_tokens (int): 生成に使用されたトークン数。usage.pyで集計する。
        request_time_ms (float): APIリクエストの応答時間(秒)をミリ秒単位で保持する。LLMの応答時間を計測する。
        api_url (str): "https://openrouter.ai/api/v1"
        model_name (str): 使用したモデル名
        retries (int): 成功までのリトライ回数(0なら初回で成功)
    """
    text: str
    input_tokens: int
    output_tokens: int
    request_time_ms: float
    api_url: str
    model_name: str
    retries: int


class LLMError(RuntimeError):
    """LLM呼び出し時の失敗を表す基底例外クラス.

    HTTPステータス由来の失敗(LLMHTTPErrorとその子孫)と、
    解釈できないレスポンス由来の失敗(LLMError)をまとめる。
    上位はこのLLMErrorを捕まえて、全失敗を一括で扱える。
    """


class LLMHTTPError(LLMError):
    """LLM呼び出し時のHTTPステータス由来の失敗を表す例外クラス.

    HTTPステータスコードが200系以外の場合に発生する。

    Attributes:
        status_code (int): Providerが返したHTTPステータスコード
    """
    def __init__(self, message: str, status: int) -> None:
        """メッセージとHTTPステータスコードを保持する.

        Args:
            message (str): エラーメッセージ
            status (int): Providerが返したHTTPステータスコード
        """
        super().__init__(message)
        self.status = status


class RateLimitError(LLMHTTPError):
    """LLM呼び出し時のレートリミット超過を表す例外クラス.

    HTTPステータスコードが429の場合に発生する。

    Attributes:
        retry_after (float | None): リトライするまでの秒数。Noneの場合はリトライ不可。
    """
    def __init__(self, message: str, status_code: int, retry_after: float | None = None) -> None:
        super().__init__(message, status_code)
        """メッセージとHTTPステータスコード、リトライまでの秒数を保持する.

        Args:
            message (str): エラーメッセージ
            status_code (int): Providerが返したHTTPステータスコード
            retry_after (float | None): リトライするまでの秒数。なければNone。
        """
        self.retry_after = retry_after


class ServerError(LLMHTTPError):
    """サーバーエラー(HTTP 500系)の場合に発生、再送で成功する可能性がある例外クラス."""


class AuthenticationError(LLMHTTPError):
    """認証 / 権限 / クォータ枯れ(HTTP 401 / 403)エラーを表す例外クラス.

    同じキーの再送は無意味なので、プロバイダを切り替えるか、キーを差し替える必要がある。
    """


class BadRequestError(LLMHTTPError):
    """リクエストが不正(HTTP 400系)の場合に発生する例外クラス.

    リクエストの組み立てに問題がある場合に発生する。
    設定 / コードのバグで、再送しても成功しない。
    """


def _parse_retry_after(header: dict[str, str]) -> float | None:
    """retry-afterヘッダを待機秒数に解釈する.

    数値のみ対応。HTTP-date形式 / 欠落時はNoneを返す。
    呼び出し側が既定の指数バックオフにフォールバックする。

    Args:
        header (dict[str, str]): 小文字正規化済みHTTPレスポンスヘッダ

    Returns:
        float | None: 待機秒数。欠落時はNone。
    """
    raw = header.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _error_from_response(response: HttpResponse) -> LLMHTTPError:
    """非200系のHTTPレスポンスから、ステータスに応じて型付き例外に変換して返す.

    """
    status = response.status
    snippet = response.body[:500]

    # 429はレートリミット超過なので、retry-afterヘッダを解釈して返す
    if status == 429:
        retry_after = _parse_retry_after(response.headers)
        return RateLimitError(f"LLM HTTP {status}: {snippet}", status, retry_after)

    # 401 / 403は認証 / 権限 / クォータ枯れなので、AuthenticationErrorを返す
    if status in (401, 403):
        return AuthenticationError(f"LLM HTTP {status} (auth / quota): {snippet}", status=status)

    # 500系はサーバーエラーなので、ServerErrorを返す
    if 500 <= status < 600:
        return ServerError(f"LLM HTTP {status} (server): {snippet}", status=status)

    # 400系はリクエスト不正なので、BadRequestErrorを返す
    return BadRequestError(f"LLM HTTP {status} (bad request): {snippet}", status=status)


class LLMProvider(ABC):
    """LLMプロバイダの抽象クラス。

    generate()にリクエスト組み立て -> 送信 -> 計測 -> レスポンス整形の共通フローを実装し、
    プロバイダの固有差分を _build_request() / _parse_response()のフックに実装する。
    """

    def __init__(self, config: ProviderConfig, transport: HttpTransport, api_key: str) -> None:
        """LLMProviderの初期化.

        Args:
            config (ProviderConfig): プロバイダの設定情報。
            transport (HTTPTransport): HTTP POST で送信を担当するTransportクラス
            api_key (str): APIキー。key_managerがkeys_envから取得して渡す。
        """
        self.config = config
        self.transport = transport
        self.api_key = api_key

    def generate(self, messages: list[dict[str, str]], stop_sequences: list[str], max_tokens: int) -> LLMResponse:
        """LLMに会話履歴を一回送って生成、リクエストを送信し、レスポンスを返す.

        Args:
            messages (list[dict[str, str]]): LLMに送信するメッセージ。OpenAI互換の形式で、roleとcontentを持つ辞書のリスト。
            stop_sequences (list[str]): 生成を停止する文字列郡(既定は ["<end_code>"])
            max_tokens (int): 生成する最大トークン数

        Returns:
            LLMResponse: 生成テキストと使用量、計測値をまとめた結果。

        Raises:
            LLMError: HTTPが非200系のステータスコードを返した場合、または解釈できない場合に発生する例外。
        """
        url, headers, body = self._build_request(messages, stop_sequences, max_tokens)
        start_time = time.perf_counter()
        response = self.transport.post(url, headers, body, timeout=self.config.request_timeout_sec)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        if not 200 <= response.status < 300:
            raise _error_from_response(response)

        return self._parse_response(response.body, elapsed_ms)

    @abstractmethod
    def _build_request(
        self,
        messages: list[dict[str, str]],
        stop_sequences: list[str],
        max_tokens: int
    ) -> tuple[str, dict[str, str], str]:
        """(url, headers, body文字列)を組み立てて返す.

        Args:
            messages (list[dict[str, str]]): LLMに送信するメッセージ。
            stop_sequences (list[str]): stop_sequences。
            max_tokens (int): 生成する最大トークン数

        Returns:
            tuple[str, dict[str, str], str]: POST先URL、ヘッダ、JSON文字列ボディ。
        """

    @abstractmethod
    def _parse_response(self, body: str, request_time_ms: float) -> LLMResponse:
        """生のレスポンス本文(JSON文字列)を解釈し、LLMResponseに変換して返す.

        Args:
            body (str): 生のHTTPレスポンス本文(JSON文字列)。
            request_time_ms (float): generate()が計測したリクエストの応答時間(ミリ秒)。

        Returns:
            LLMResponse: 共通形式に正規化した結果。
        """

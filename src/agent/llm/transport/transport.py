"""HttpTransportの抽象クラスと共通の戻り値型、例外を定義するモジュール.

Requests / Httpx / Urllib / などのHttpClientがHTTPTransportを継承。
送信して応答(HttpResponse)を返す。
応答がなければTransportErrorを返す。
リトライ / キーローテ / フォールバックはここで行わない。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class HttpResponse:
    """1回のHTTPリクエストの応答を表すデータクラス.

    Attributes:
        status (int): HTTPステータスコード(200 / 429 / 500など)
        body (str): HTTPレスポンスボディ(文字列)
        headers (dict[str, str]): HTTPレスポンスヘッダ。キーは小文字に正規化して保持。
    """
    status: int
    body: str
    headers: dict[str, str] = field(default_factory=dict)


class TransportError(RuntimeError):
    """HTTP通信に失敗 / 応答がない時に送出される例外クラス.

    timeout / 接続断 / DNS解決失敗 / SSLエラーなど
    ステータスコードが存在しない通信系の例外をラップして送出する。
    200系以外のHTTPステータスコードがある場合はTransportErrorではなくHttpResponseを返す。
    """


class HttpTransport(ABC):
    """HTTP通信を行う抽象クラス."""

    @abstractmethod
    def post(self, url: str, headers: dict[str, str], data: str, timeout: float = 60.0) -> HttpResponse:
        """HTTP POSTリクエストを送信する.

        Args:
            url (str): リクエスト先URL
            headers (dict[str, str]): リクエストヘッダ
            data (str): リクエストボディ
            timeout (float): タイムアウト秒数

        Returns:
            HttpResponse: timeout / 接続断など、応答そのものがない場合。
        """

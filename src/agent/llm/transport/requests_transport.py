"""Requestsライブラリを使用したHTTP通信を抽象化するモジュール."""
from src.agent.llm.transport.transport import HttpTransport, HttpResponse, TransportError


class RequestsTransport(HttpTransport):
    """Requestsライブラリを使用したHTTP通信クラス."""

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
        import requests

        try:
            response = requests.post(url, headers=headers, data=data, timeout=timeout)
        except requests.RequestException as e:
            raise TransportError(f"HTTP request failed: {e}") from e

        return HttpResponse(
            status=response.status_code,
            body=response.text,
            headers={key.lower(): value for key, value in response.headers.items()}
        )

"""urllibを使用したHTTP通信クラス.

requests / httpx と違い、非200系をHTTPError例外で返す。
HTTPErrorは例外かつ応答でもあるので、呼び出し側で例外をキャッチして
HTTPErrorのstatus / body / headersを参照することで、非200系の応答を取得できる。
HTTPErrorはURLErrorのサブクラスなので、先にHTTPErrorをexceptする必要がある。
"""
from src.agent.llm.transport.transport import HttpTransport, HttpResponse, TransportError


class UrllibTransport(HttpTransport):
    """Urllibライブラリを使用したHTTP通信クラス."""

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
        from urllib import request, error

        req = request.Request(url, data=data.encode(), headers=headers, method='POST')

        try:
            with request.urlopen(req, timeout=timeout) as response:
                return HttpResponse(
                    status=response.getcode(),
                    body=response.read().decode(),
                    headers={key.lower(): value for key, value in response.headers.items()}
                )
        except error.HTTPError as http_error:
            body = http_error.read().decode(errors='replace')
            raw_headers = http_error.headers.items() if http_error.headers else []

            return HttpResponse(
                status=http_error.code,
                body=body,
                headers={key.lower(): value for key, value in raw_headers}
            )

        except (error.URLError, TimeoutError) as url_error:
            raise TransportError(f"HTTP request failed: {url_error}") from url_error

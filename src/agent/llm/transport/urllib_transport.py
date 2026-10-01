"""urllibを使用したHTTP通信クラス."""
from src.agent.llm.transport.transport import HttpTransport


class UrllibTransport(HttpTransport):
    """Urllibライブラリを使用したHTTP通信クラス."""

    def post(self, url: str, headers: dict[str, str], data: str) -> tuple[int, str]:
        from urllib import request

        req = request.Request(url, data=data.encode(), headers=headers, method='POST')
        with request.urlopen(req) as response:
            return response.getcode(), response.read().decode()

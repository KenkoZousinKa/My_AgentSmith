"""HTTP通信を抽象化するモジュール."""
from src.agent.llm.transport.transport import HttpTransport


class RequestsTransport(HttpTransport):
    """Requestsライブラリを使用したHTTP通信クラス."""

    def post(self, url: str, headers: dict[str, str], data: str) -> tuple[int, str]:
        import requests

        response = requests.post(url, headers=headers, data=data)
        return response.status_code, response.text

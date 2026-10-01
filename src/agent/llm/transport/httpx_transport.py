"""HTTP通信を抽象化するモジュール."""
from src.agent.llm.transport.transport import HttpTransport


class HttpxTransport(HttpTransport):
    """Httpxライブラリを使用したHTTP通信クラス.モダン."""

    def post(self, url: str, headers: dict[str, str], data: str) -> tuple[int, str]:
        import httpx

        response = httpx.post(url, headers=headers, data=data)
        return response.status_code, response.text

"""httpxを使用したHTTP通信を抽象化するモジュール."""
from src.agent.llm.transport.transport import HttpTransport


class HttpxTransport(HttpTransport):
    """Httpxライブラリを使用したHTTP通信クラス."""

    def post(self, url: str, headers: dict[str, str], data: str, timeout: float = 60.0) -> tuple[int, str]:
        import httpx

        response = httpx.post(url, headers=headers, data=data, timeout=timeout)
        return response.status_code, response.text

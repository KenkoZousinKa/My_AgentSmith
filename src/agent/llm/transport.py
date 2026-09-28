"""HttpTransportの抽象クラスを定義するモジュール.

Requests / Httpx / Urllib / などのHttpClientが継承予定。
"""
from abc import ABC, abstractmethod


class HttpTransport(ABC):
    """HTTP通信を行う抽象クラス."""

    @abstractmethod
    def post(self, url: str, headers: dict[str, str], data: str) -> tuple[int, str]:
        """HTTP POSTリクエストを送信する.

        Args:
            url (str): リクエスト先URL
            headers (dict[str, str]): リクエストヘッダ
            data (str): リクエストボディ

        Returns:
            tuple[int, str]: レスポンスのステータスコードとボディ
        """
        pass


class RequestsTransport(HttpTransport):
    """Requestsライブラリを使用したHTTP通信クラス."""

    def post(self, url: str, headers: dict[str, str], data: str) -> tuple[int, str]:
        import requests

        response = requests.post(url, headers=headers, data=data)
        return response.status_code, response.text


class HttpxTransport(HttpTransport):
    """Httpxライブラリを使用したHTTP通信クラス.モダン."""

    def post(self, url: str, headers: dict[str, str], data: str) -> tuple[int, str]:
        import httpx

        response = httpx.post(url, headers=headers, data=data)
        return response.status_code, response.text


class UrllibTransport(HttpTransport):
    """Urllibライブラリを使用したHTTP通信クラス."""

    def post(self, url: str, headers: dict[str, str], data: str) -> tuple[int, str]:
        from urllib import request

        req = request.Request(url, data=data.encode(), headers=headers, method='POST')
        with request.urlopen(req) as response:
            return response.getcode(), response.read().decode()

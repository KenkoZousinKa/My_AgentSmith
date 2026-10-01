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

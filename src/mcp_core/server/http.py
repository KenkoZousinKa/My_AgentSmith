import socket
from typing import Callable
from dataclasses import dataclass, field

from src.mcp_core.models import jsonrpc as rpc
from src.mcp_core.models import mcpmodel as mcp

MAX_HEADER_BYTES = 8000
MAX_BODY_BYTES = 1000000
RECIEVE_BUFFER = 4096
HTTP_VERSION = "HTTP/1.1"


@dataclass
class HttpRequest:
    method: str
    path: str
    headers: dict[str, str]     # 名前は小文字
    body: bytes


@dataclass
class HttpResponse:
    code: int
    text: str
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def to_bytes(self) -> bytes:
        """クラスの全属性（__dict__）をバイト列(http書式)に変換"""
        # 1. リクエストラインの作成 (例: "POST /index.html HTTP/1.1")
        lines = [f"HTTP/1.1 {self.code} {self.text}"]

        # 2. ヘッダー情報の追加 (例: "Host: localhost")
        for key, value in self.headers.items():
            lines.append(f"{key}: {value}")

        # ヘッダーとボディの間には空行（改行のみ）が必要なので、末尾に空文字を入れる
        lines.append("")

        # 3. 各行をHTTPの標準改行コード「\r\n（CRLF）」で結合
        header_part = "\r\n".join(lines) + "\r\n"

        # 4. ヘッダー文字列をバイト列に変換し、ボディ（文字列と仮定）を結合する
        # ※ボディがすでにバイト列の場合は、そのまま結合してください
        return header_part.encode("utf-8") + self.body


class HttpError(Exception):
    def __init__(self, code: int, text: str = "") -> None:
        super().__init__(text)
        self.code = code


class HttpServerTransport:
    """サーバーの受付(http)を担当する."""
    def __init__(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        self.host = host
        self.port = port

    def serve(self, handle: Callable[[str], rpc.JSONRPCResponse | rpc.JSONRPCError | None]) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:  # ipv4 and tcp. socket opne
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # setting port reuserble
            s.bind((self.host, self.port))  # setting ip port
            s.listen()  # waiting
            while True:
                conn, addr = s.accept()
                with conn:
                    try:
                        request = self._read_request(conn)
                        response = self._route(request, handle)
                    except HttpError as e:
                        response = HttpResponse(e.code, str(e))
                    conn.sendall(response.to_bytes())

    def _read_request(self, conn: socket.socket) -> HttpRequest:
        """Httpリクエストを読んで、リクエストを返す."""
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            buffer += self._recv(conn)
            if 8000 <= len(buffer):
                raise HttpError(431, "Request Header Fields Too Large")

        b_head, _, b_body = buffer.partition(b"\r\n\r\n")

        method, path, headers = self._parse_head(b_head)

        while len(b_body) < int(headers['content-length']):
            b_body += self._recv(conn)

        return HttpRequest(method=method, path=path, headers=headers, body=b_body)


    # def _write_response(self, conn: socket.socket, response: HttpResponse) -> None:
        """
        Content-Length を len(response.body) から作る（本文は bytes なので、これがバイト数になる）。
        Connection: close を付ける。
        1行目の理由の文字列は、HTTPStatus(response.status).phrase から作る。
        ヘッダーを \r\n でつなぎ、空行を足し、本文をつなげて、sendall する。
        """

    def _route(self, request: HttpRequest, handle: Callable[[str], rpc.JSONRPCResponse | rpc.JSONRPCError | None]) -> HttpResponse:
        body = handle(request.body.decode("utf-8"))

        if body is None:
            http = HttpResponse(code=200, text="OK",
                                headers={"Content-Type": "application/json",
                                         "Content-Length": "0",
                                         "Connection": "close"})
        else:
            http = HttpResponse(code=200, text="OK",
                                body=body.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8"),
                                headers={"Content-Type": "application/json",
                                         "Content-Length": str(len(body.model_dump_json(by_alias=True, ))),
                                         "Connection": "close"})
        return http

    def _recv(self, conn: socket.socket) -> bytes:
        data = conn.recv(RECIEVE_BUFFER)
        if data == b"":  # closed client
            raise HttpError(400, "Not Data")
        return data

    def _parse_head(self, head: bytes) -> tuple[str, str, dict[str, str]]:
        """head部の解析とオブジェクト化."""
        # decodeしたあと、行ごとにリスト化
        try:
            l_header = head.decode("ascii").split("\r\n")

            method, path, version = l_header[0].split(' ', 2)
            if version != HTTP_VERSION:
                raise HttpError(505, "HTTP Version Not Supported")

            headers: dict[str, str] = {}
            for line in l_header[1:]:
                key, value = line.split(":", 1)

                headers[key.strip().lower()] = value.strip().lower()

            content_length = int(headers["content-length"])
            if content_length < 0 or MAX_BODY_BYTES < content_length:
                raise HttpError(400, "Bad Request")

        except ValueError as e:
            print("ValueError", e)
            raise HttpError(400, "Bad Request")
        except KeyError as e:
            print("keyError", e)
            raise HttpError(411, "Length Required")
        return (method, path, headers)



# HttpServerTransport().serve(None)

import socket
import http
import uuid
import json
from urllib.parse import urlsplit
from email.utils import formatdate
from typing import Callable
from dataclasses import dataclass, field

from src.mcp_core.models import jsonrpc as rpc
from src.mcp_core.models import mcpmodel as mcp

MAX_HEADER_BYTES = 8000
MAX_BODY_BYTES = 1000000
RECEIVE_BUFFER = 4096
HTTP_VERSION = "HTTP/1.1"
RECV_TIMEOUT_SECONDS = 5


@dataclass
class HttpRequest:
    method: str
    path: str
    headers: dict[str, str]     # 名前は小文字
    body: bytes


@dataclass
class HttpResponse:
    code: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def to_bytes(self) -> bytes:
        """クラスの全属性（__dict__）をバイト列(http書式)に変換"""
        reason = http.HTTPStatus(self.code).phrase
        headers = {
            **self.headers,
            "Content-Length": str(len(self.body)),
            "Connection": "close",
            "Date":  formatdate(usegmt=True)
        }
        # 1. リクエストラインの作成
        lines = [f"HTTP/1.1 {self.code} {reason}"]

        # 2. ヘッダー情報の追加
        lines += [f"{key}: {value}" for key, value in headers.items()]

        # 3. 各行をHTTPの標準改行コード「\r\n（CRLF）」で結合
        head = "\r\n".join(lines) + "\r\n\r\n"

        # 4. ヘッダーをバイト列に変換し、ボディを結合
        return head.encode("ascii") + self.body


class HttpError(Exception):
    """HTTPとして返すErrorオブジェクト"""
    def __init__(self, code: int, message: str = "",
                 headers: dict[str, str] | None = None) -> None:
        super().__init__(code, message, headers)
        self.code = code
        self.message = message or http.HTTPStatus(code).phrase
        self.headers = headers or {}

    def __str__(self) -> str:
        return self.message


class HttpServerTransport:
    """サーバーの受付(http)を担当する."""
    def __init__(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        self.host = host
        self.port = port
        self.sessions: set[str] = set()

    def serve(self, handle: Callable[[str], rpc.JSONRPCResponse | rpc.JSONRPCError | None]) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:  # ipv4 and tcp. socket opne
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # setting port reuserble
            s.bind((self.host, self.port))  # setting ip port
            s.listen()  # waiting
            while True:
                conn, addr = s.accept()
                conn.settimeout(RECV_TIMEOUT_SECONDS)
                with conn:
                    try:
                        request = self._read_request(conn)
                        response = self._route(request, handle)
                        conn.sendall(response.to_bytes())
                    except HttpError as e:
                        conn.sendall(HttpResponse(e.code, e.headers).to_bytes())
                    except OSError:
                        pass

    def _read_request(self, conn: socket.socket) -> HttpRequest:
        """Httpリクエストを読んで、リクエストオブジェクトを返す."""
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            if MAX_HEADER_BYTES <= len(buffer):
                raise HttpError(431, "Request Header Fields Too Large")
            buffer += self._recv(conn)

        b_head, _, b_body = buffer.partition(b"\r\n\r\n")

        method, path, headers = self._parse_head(b_head)

        content_length = int(headers.get('content-length', 0))
        while len(b_body) < content_length:
            b_body += self._recv(conn)
        b_body = b_body[:content_length]

        return HttpRequest(method=method, path=path, headers=headers, body=b_body)

    def _route(self, request: HttpRequest,
               handle: Callable[[str], rpc.JSONRPCResponse | rpc.JSONRPCError | None]) -> HttpResponse:
        """リクエストオブジェクトの解析後、レスポンスオブジェクトを作成して返す
       順	確かめること	当てはまったら
        1	パスが /mcp 以外	404
        2	Origin が localhost 以外	403
        3	POST 以外	405（Allow: POST）
        4	Content-Length が無い（transfer-encoding がある場合も）	411
        5	本文が initialize	handle に渡し、成功ならセッション ID を付けて 200
        6	Mcp-Session-Id が無い	400
        7	知らないセッション ID	404
        8	MCP-Protocol-Version が未対応	400
        9	handle の結果	返事があれば 200、None なら 202
        """
        # ====== HTTP ======
        # Pathが/mcp以外を弾く
        if request.path != "/mcp":
            raise HttpError(404)

        # origin（ホストPCからのアクセス）かどうか
        origin = request.headers.get("origin")
        if origin is not None and urlsplit(origin).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise HttpError(403)

        # POST以外を弾く
        if request.method != "POST":
            raise HttpError(405, headers={"Allow": "POST"})

        # Content_Lengthがない
        if request.headers.get("content-length") is None:
            raise HttpError(411)

        # Transfer-Encodingがある
        if request.headers.get("transfer-encoding"):
            raise HttpError(411)

        # ====== MCP ======
        # clientからinitializeがきた
        try:
            is_initialize = json.loads(request.body).get("method") == "initialize"
        except (ValueError, AttributeError):
            is_initialize = False

        if not is_initialize:
            # Session Idがない
            if request.headers.get("mcp-session-id") is None:
                raise HttpError(400)

            # 知らないSession Id
            if request.headers.get("mcp-session-id") not in self.sessions:
                raise HttpError(404)

            # mcp-protocolが同じか
            version = request.headers.get("mcp-protocol-version")
            if version is not None and version != mcp.MCP_VERSION:
                raise HttpError(400)

        data = handle(request.body.decode("utf-8"))

        # notifycationと判断する
        if data is None:
            return HttpResponse(202)

        # JSONRPCErrorが返ってきたらcodeを400に
        json_error = (rpc.ErrorCode.PARSE_ERROR, rpc.ErrorCode.INVALID_REQUEST)
        code = 400 if isinstance(data, rpc.JSONRPCError) and data.error.code in json_error else 200

        headers = {"Content-Type": "application/json"}
        if is_initialize and isinstance(data, rpc.JSONRPCResponse):
            session_id = uuid.uuid4().hex
            self.sessions.add(session_id)
            headers["Mcp-Session-Id"] = session_id

        body = data.model_dump_json(by_alias=True, exclude_unset=True).encode("utf-8")
        return HttpResponse(code=code, headers=headers, body=body)

    def _recv(self, conn: socket.socket) -> bytes:
        data = conn.recv(RECEIVE_BUFFER)
        if not data:  # closed client
            raise ConnectionError("client closed the connection")
        return data

    # def _write_response(self, conn: socket.socket, response: HttpResponse) -> None:
        """
        Content-Length を len(response.body) から作る（本文は bytes なので、これがバイト数になる）。
        Connection: close を付ける。
        1行目の理由の文字列は、HTTPStatus(response.status).phrase から作る。
        ヘッダーを \r\n でつなぎ、空行を足し、本文をつなげて、sendall する。
        """

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

                headers[key.strip().lower()] = value.strip()

            content_length = int(headers.get("content-length", 0))
            if content_length < 0:
                raise HttpError(400, "Bad Request")
            elif MAX_BODY_BYTES < content_length:
                raise HttpError(413, "Bad Request")

        except ValueError:
            raise HttpError(400, "Bad Request")
        return (method, path, headers)


# HttpServerTransport().serve(None)

"""Server側のhttp接続クラス."""

import socket
import http  # HTTPステータスコード取得のみ
import uuid
import json
from urllib.parse import urlsplit
from email.utils import formatdate
from typing import Callable
from dataclasses import dataclass, field

from src.mcp.models import jsonrpc as rpc
from src.mcp.models import mcpmodel as mcp

MAX_HEADER_BYTES = 8000  # HTTPヘッダーの最大バイト数
MAX_BODY_BYTES = 1000000  # HTTPボディの最大バイト数
RECEIVE_BUFFER = 4096  # ソケット受信バッファサイズ
HTTP_VERSION = "HTTP/1.1"  # 使用するHTTPバージョン
RECV_TIMEOUT_SECONDS = 5  # ソケット受信タイムアウト(秒)


@dataclass
class HttpRequest:
    """HTTPリクエストを表すデータクラス.

    Attributes:
        method (str): HTTPメソッド
        path (str): リクエストパス
        headers (dict[str, str]): HTTPヘッダー（名前は小文字）
        body (bytes): HTTPボディ
    """
    method: str
    path: str
    headers: dict[str, str]
    body: bytes


@dataclass
class HttpResponse:
    """HTTPレスポンスを表すデータクラス.

    HTTP送信時は属性情報ははbyte変換される。

    Attributes:
        code (int): HTTPステータスコード
        headers (dict[str, str]): HTTPヘッダー
        body (bytes): HTTPボディ
    """
    code: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def to_bytes(self) -> bytes:
        """クラスの全属性（__dict__）をbyte列(http書式)に変換.

        HTTPフォーマットに整えて送れる形にする。

        Returns:
            bytes: HTTPレスポンスを表すバイト列
        """
        reason = http.HTTPStatus(self.code).phrase  # HTTPステータスコードに合わせたメッセージを取得
        headers = {
            **self.headers,
            "Content-Length": str(len(self.body)),
            "Connection": "close",  # 接続を閉じることを伝える
            "Date":  formatdate(usegmt=True)  # 現在時刻をHTTP形式で取得
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
    """HTTPが返すエラーを表す例外クラス.

    Attributes:
        code (int): HTTPステータスコード
        message (str): エラーメッセージ
        headers (dict[str, str]): HTTPヘッダー
    """
    def __init__(self, code: int, message: str = "", headers: dict[str, str] | None = None) -> None:
        """HttpErrorの初期化.

        Args:
            code (int): HTTPステータスコード
            message (str): エラーメッセージ
            headers (dict[str, str] | None): HTTPヘッダー
        """
        super().__init__(code, message, headers)
        self.code = code
        self.message = message or http.HTTPStatus(code).phrase
        self.headers = headers or {}

    def __str__(self) -> str:
        """HttpErrorの文字列表現を返す."""
        return self.message


class HttpServerTransport:
    """Clientとの接続をHTTPで行うTransportクラス.

    Attributes:
        host (str): サーバーのホスト
        port (int): サーバーのポート
        sessions (set[str]): 接続中のセッションIDをsetで保持
    """
    def __init__(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        """HttpServerTransportの初期化.

        Args:
            host (str): サーバーのホスト
            port (int): サーバーのポート
        """
        self.host = host
        self.port = port
        self.sessions: set[str] = set()

    def serve(self, handle: Callable[[str], rpc.JSONRPCResponse | rpc.JSONRPCError | None]) -> None:
        """ソケットを作成し、クライアントからの接続を受け付けるHTTPサーバーのループを回す.

        Args:
            handle (Callable[[str], rpc.JSONRPCResponse | rpc.JSONRPCError | None]): クライアントからのリクエストを受け取り、レスポンスを返す関数
        """
        # AF_INET: IPv4, SOCK_STREAM: TCP
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:  # Socketオブジェクトはs
            # SOL_SOCKET: ソケットレベルのオプションを設定, SO_REUSEADDR: ポートのロックを解除して再利用可能にする
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # hostとportをバインド
            s.bind((self.host, self.port))
            s.listen()  # 接続待ち状態にする
            while True:
                # TCP 3-way handshakeで接続を受け付けるまでブロック
                # conn: クライアント専用のソケット, addr: (IP, Port)
                conn, addr = s.accept()
                conn.settimeout(RECV_TIMEOUT_SECONDS)  # 受信タイムアウトを設定
                with conn:
                    try:
                        request = self._read_request(conn)
                        response = self._route(request, handle)
                        # レスポンスをクライアントに送信
                        conn.sendall(response.to_bytes())
                    except HttpError as e:
                        # HttpErrorが発生した場合はエラーレスポンスを送信
                        conn.sendall(HttpResponse(e.code, e.headers).to_bytes())
                    except OSError:
                        pass

    def _read_request(self, conn: socket.socket) -> HttpRequest:
        """ソケットからHTTPリクエストを読んで、リクエストオブジェクトにして返す.

        Args:
            conn (socket.socket): クライアントとの接続ソケット
        Returns:
            HttpRequest: 解析されたHTTPリクエストオブジェクト
        """
        buffer = b""
        while b"\r\n\r\n" not in buffer:  # ヘッダの終端は空行のため\r\n\r\nで示される
            # ヘッダが大きすぎる場合はエラー
            if MAX_HEADER_BYTES <= len(buffer):
                raise HttpError(431, "Request Header Fields Too Large")
            buffer += self._recv(conn)

        # ヘッダーとボディのかけらに分割
        b_head, _, b_body = buffer.partition(b"\r\n\r\n")

        # ヘッダ部分を解析
        method, path, headers = self._parse_head(b_head)

        # Bodyの長さを取得
        content_length = int(headers.get('content-length', 0))
        # content-lengthまでボディを読み足す
        while len(b_body) < content_length:
            b_body += self._recv(conn)
        b_body = b_body[:content_length]

        return HttpRequest(method=method, path=path, headers=headers, body=b_body)

    def _recv(self, conn: socket.socket) -> bytes:
        """ソケットからデータを受信して返す.

        Args:
            conn (socket.socket): クライアントとの接続ソケット
        Returns:
            bytes: 受信したデータ
        """
        data = conn.recv(RECEIVE_BUFFER)
        # clientが接続を閉じた場合はエラー
        if not data:
            raise ConnectionError("client closed the connection")
        return data

    def _parse_head(self, head: bytes) -> tuple[str, str, dict[str, str]]:
        """HTTPリクエスト行とヘッダーを解析して返す.

        Args:
            head (bytes): HTTPリクエストのヘッダ部分
        Returns:
            tuple[str, str, dict[str, str]]: (method, path, headers)
        """
        try:
            # decodeして行ごとに分割
            l_header = head.decode("ascii").split("\r\n")

            # 1行目はリクエスト行 (method, path, version)
            method, path, version = l_header[0].split(' ', 2)
            if version != HTTP_VERSION:
                raise HttpError(505, "HTTP Version Not Supported")

            # 2行目以降はヘッダー
            headers: dict[str, str] = {}
            for line in l_header[1:]:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()

            # Content-Lengthのチェック
            content_length = int(headers.get("content-length", 0))
            # Content-Lengthが負の値や最大値を超えていないか確認
            if content_length < 0:
                raise HttpError(400, "Bad Request")
            elif MAX_BODY_BYTES < content_length:
                raise HttpError(413, "Content Too Large")

        except ValueError:
            raise HttpError(400, "Bad Request")
        return (method, path, headers)

    def _route(self, request: HttpRequest,
               handle: Callable[[str], rpc.JSONRPCResponse | rpc.JSONRPCError | None]) -> HttpResponse:
        """リクエストオブジェクトの解析後、レスポンスオブジェクトを作成して返す.

        Args:
            request (HttpRequest): HTTPリクエストオブジェクト
            handle (Callable[[str], rpc.JSONRPCResponse | rpc.JSONRPCError | None]): JSON-RPCリクエストを処理するコールバック
        Returns:
            HttpResponse: HTTPレスポンスオブジェクト
        """
        # ====== HTTP ======
        # Pathがエンドポイント /mcp であるかどうか
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

        # Transfer-Encodingがある(Bodyの長さを判定できないため)
        if request.headers.get("transfer-encoding"):
            raise HttpError(411)

        # ====== MCP ======
        # clientからinitializeが来たかどうかを判定
        try:
            is_initialize = json.loads(request.body).get("method") == "initialize"
        except (ValueError, AttributeError):
            is_initialize = False

        if not is_initialize:
            # Session Idがない(初期化以外のリクエストでは必須)
            if request.headers.get("mcp-session-id") is None:
                raise HttpError(400)

            # 知らないSession Id
            if request.headers.get("mcp-session-id") not in self.sessions:
                raise HttpError(404)

            # mcp-protocolが同じか
            version = request.headers.get("mcp-protocol-version")
            if version is not None and version != mcp.MCP_VERSION:
                raise HttpError(400)

        # サーバー機能にリクエストを渡す
        data = handle(request.body.decode("utf-8"))

        # dataがなければnotifycationと判断する
        if data is None:
            return HttpResponse(202)

        # JSON-RPCエラーかどうかを判定し、HTTPステータスコードを設定
        json_error = (rpc.ErrorCode.PARSE_ERROR, rpc.ErrorCode.INVALID_REQUEST)
        code = 400 if isinstance(data, rpc.JSONRPCError) and data.error.code in json_error else 200

        headers = {"Content-Type": "application/json"}
        # InitializeかつerrorじゃなければセッションIDを設定
        if is_initialize and isinstance(data, rpc.JSONRPCResponse):
            session_id = uuid.uuid4().hex
            self.sessions.add(session_id)
            headers["Mcp-Session-Id"] = session_id

        body = data.model_dump_json(by_alias=True, exclude_unset=True).encode("utf-8")
        return HttpResponse(code=code, headers=headers, body=body)

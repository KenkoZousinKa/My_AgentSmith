import http.client
import subprocess
import shlex
import time
import sys
from collections import deque
from urllib.parse import urlsplit, SplitResult
from pydantic import ValidationError

from src.mcp_core.models import jsonrpc as rpc
from src.mcp_core.models import mcpmodel as mcp

DEFAULT_URL = "http://127.0.0.1:8000/mcp"
SERVER_COMMAND = "python mcp_tools_mbpp.py --transport http"


class HttpClientTransport:
    def __init__(self, url: str, timeout: int = 60) -> None:
        self.process: subprocess.Popen[bytes] | None = None  # 規定serverを立ち上げた際のプロセスオブジェクト
        self.url: str = url
        parts: SplitResult = urlsplit(url)
        if parts.scheme != "http" or parts.hostname is None:
            raise ValueError(f"http://ホスト:ポート/パス の形で指定してください: {url!r}")

        self.hostname: str = parts.hostname
        self.path: str = parts.path or "/"
        self.port: int | None = parts.port
        self.session_id: str | None = None
        self.protocol_version: str | None = None

        self.timeout: int = timeout
        self.stream: http.client.HTTPResponse | None = None  # SSEでサーバーと接続されているconnオブジェクト
        self.inbox: deque[rpc.JSONRPCMessage] = deque()  # Clientが処理すべきメッセージ

    def open(self) -> None:
        """サーバーが起動しているか確かめて、接続が確立されなければ規定サーバーを起動する."""
        if self._is_connect():
            return

        if self.url != DEFAULT_URL:
            raise mcp.MCPConnectionError(f"サーバーに繋がりません  URL: {self.url}")

        print("サーバーが見つからないため提供サーバーを立ち上げます", file=sys.stderr)
        self.process = subprocess.Popen(shlex.split(SERVER_COMMAND))
        deadline = time.monotonic() + 10
        while not self._is_connect():
            if self.process.poll() is not None:
                raise mcp.MCPConnectionError(f"提供サーバーが起動直後に終了しました: {SERVER_COMMAND}")
            if time.monotonic() > deadline:
                raise mcp.MCPConnectionError(f"提供サーバーが 10 秒以内に待ち受けを始めませんでした: {SERVER_COMMAND}")
            time.sleep(0.1)

    def _is_connect(self) -> bool:
        """短い待ち時間でつないでみて、待ち受けているか確かめる."""
        conn = http.client.HTTPConnection(self.hostname, self.port, timeout=1)
        try:
            conn.connect()
            return True
        except OSError:
            return False
        finally:
            conn.close()

    def _new_connection(self) -> http.client.HTTPConnection:
        return http.client.HTTPConnection(self.hostname, self.port, timeout=self.timeout)

    def send(self, message: rpc.JSONRPCMessage) -> None:
        """メッセージを POST し、返事を待ち行列か self.stream に入れる."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            }
        if self.session_id is not None:
            headers["Mcp-Session-Id"] = self.session_id
        if self.protocol_version is not None:
            headers["MCP-Protocol-Version"] = self.protocol_version
        body = message.model_dump_json(by_alias=True, exclude_unset=True).encode("utf-8")

        conn = self._new_connection()
        try:
            conn.request("POST", self.path, body=body, headers=headers)
            resp = conn.getresponse()
            self._handle_response(resp)
        except (OSError, http.client.HTTPException) as e:
            conn.close()
            raise mcp.MCPConnectionError(f"{self.url} と通信できません: {e}") from e

    def _handle_response(self, resp: http.client.HTTPResponse) -> None:
        """ステータスと Content-Type を見て、メッセージを待ち行列か self.stream に入れる."""
        session_id = resp.getheader("Mcp-Session-Id")
        if session_id is not None:
            self.session_id = session_id

        # 202
        if resp.status == http.HTTPStatus.ACCEPTED:
            resp.read()  # 読み残しを防ぐ
            resp.close()  # socketを閉じる
            return

        # not 200
        if resp.status != http.HTTPStatus.OK:
            body = resp.read().decode("utf-8", errors="replace")  # replace文字化けを防ぐ
            resp.close()
            if resp.status == http.HTTPStatus.NOT_FOUND and self.session_id is not None:  # SessionIDが違っていた
                self.session_id = None
                raise mcp.MCPConnectionError("サーバーがセッションを知りません（404）。サーバーが再起動した可能性があります")
            raise mcp.MCPConnectionError(f"予期しない返事です。Code: {resp.status} Body: {body[:200]!r}")  # bodyが長すぎでもカットする

        # 200
        content_type = (resp.getheader("Content-Type") or "").split(";")[0].strip().lower()  # 追加のパラメータ(;)を外す
        if content_type == "application/json":
            body = resp.read().decode("utf-8")
            resp.close()
            self.inbox.append(self._parse(body))
        elif content_type == "text/event-stream":
            if self.stream is not None:  # 読みかけのstreamを消す
                self.stream.close()
            self.stream = resp  # SSEなので後で_respが読む
        else:
            resp.close()
            raise mcp.MCPProtocolError(f"想定外の Content-Type です: {content_type!r}")

    def _parse(self, text: str) -> rpc.JSONRPCMessage:
        """JSON の文字列を JSON-RPC のメッセージに変換する."""
        try:
            return rpc.jsonrpc_message_adapter.validate_json(text)
        except ValidationError as e:
            raise mcp.MCPProtocolError(f"サーバから不正なメッセージを受信しました。{text!r}") from e

    def receive(self) -> rpc.JSONRPCMessage:
        """次のメッセージを1件返す。待ち行列が空なら、読みかけの SSE から1件読む."""
        if self.inbox:
            return self.inbox.popleft()
        if self.stream is not None:
            try:
                data = self._read_event(self.stream)
            except (OSError, http.client.HTTPException) as e:
                self._close_stream()
                raise mcp.MCPConnectionError(f"SSE の受信中に接続が切れました: {e}") from e
            if data is not None:
                return self._parse(data)
            self._close_stream()                           # SSE が終わった
        raise mcp.MCPConnectionError("サーバーから、待っているメッセージが届いていません")

    def _read_event(self, stream: http.client.HTTPResponse) -> str | None:
        """SSE から次のイベントの data を1件分読む。本文が終わったら None."""
        data_lines: list[str] = []
        while True:
            raw = stream.readline()  # OSから1行だけ受け取る
            if not raw:                                   # 本文の終わり
                return "\n".join(data_lines) if data_lines else None
            line = raw.decode("utf-8").rstrip("\r\n")
            if line == "":                                # 空行 = イベントの終わり
                if data_lines:
                    return "\n".join(data_lines)
                continue                                  # data の無いイベント（コメントだけなど）は飛ばす
            if line.startswith("data:"):
                value = line[len("data:"):]
                data_lines.append(value[1:] if value.startswith(" ") else value)
            # event:、id:、retry:、":" で始まるコメントは読み飛ばす

    def _close_stream(self) -> None:
        """streamレスポンスオブジェクトを安全に終了する."""
        if self.stream is not None:
            self.stream.close()
            self.stream = None

    def close(self) -> None:
        """読みかけの SSE を閉じ、自分で起動したサーバーがあれば止める."""
        self._close_stream()
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None

    def set_protocol_version(self, version: str) -> None:
        """MCPプロトコルのバージョンを設定する."""
        self.protocol_version = version

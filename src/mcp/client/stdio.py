"""MCPClientの標準入出力を使ったTransportクラス."""
import time
import shlex
import subprocess
from pydantic import ValidationError

from src.mcp.models import jsonrpc as rpc
from src.mcp.models import mcpmodel as mcp


class StdioClientTransport:
    """MCPサーバーとの接続を標準入出力で行うTransportクラス.

    MCPサーバーを起動し、標準入出力を使ってJSON-RPCメッセージを送受信する.

    Attributes:
        command (str): MCPサーバーを起動するコマンド. 例 :["python", "mcp_tools_mbpp.py"]
        process (subprocess.Popen): MCPサーバーのプロセスオブジェクト
        mcp_version (str): MCPサーバーのバージョン
    """
    def __init__(self, command: str) -> None:
        """StdioClientTransportを初期化する.

        Args:
            command (str): MCPサーバーを起動するコマンド
        """
        self.command: str = command
        self.process: subprocess.Popen[str]
        self.mcp_version: str

    def open(self) -> None:
        """MCPサーバーとの接続をStdioで確立する.

        サーバープロセスを起動し、入出力をパイプで繋ぐ.

        Raises:
            mcp.MCPConnectionError: サーバーの起動に失敗した場合
        """
        # サーバープロセスを起動し、入出力をパイプで繋ぐ
        # text=True により、バイト列ではなく文字列として扱える
        self.process = subprocess.Popen(
            args=shlex.split(self.command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,       # 送信時に文字列が壊れないように
        )

        # 起動直後の即死チェック
        time.sleep(0.1)
        if self.process.poll() is not None:
            raise mcp.MCPConnectionError(f"サーバーの起動に失敗しました。コマンド: {self.command}")

    def send(self, message: rpc.JSONRPCMessage) -> None:
        """stdio接続されているサーバーに1行送信する.

        引数のmessageはサーバーと送受信する型をまとめたJSONRPCMessage型で、
        jsonrpc_message_adapterを使ってjson文字列に変換して送信する.

        Args:
            message (rpc.JSONRPCMessage): 送信するJSON-RPCメッセージ
        """
        assert self.process.stdin is not None
        self.process.stdin.write(message.model_dump_json(by_alias=True, exclude_unset=True) + "\n")
        self.process.stdin.flush()

    def receive(self) -> rpc.JSONRPCMessage:
        """stdio接続されているサーバーから1行受信し、JSON-RPCの型に変換して返す.

        受信したメッセージが不正な場合は例外を投げる.
        例外は呼び出し元で処理する

        Returns:
            rpc.JSONRPCMessage: サーバーから受信したJSON-RPCメッセージ

        Raises:
            mcp.MCPConnectionError: サーバーとの接続が切れた場合
            mcp.MCPProtocolError: サーバーから不正なメッセージを受信した場合
        """
        assert self.process.stdout is not None

        # MCPサーバーからの標準出力を待つ
        line = self.process.stdout.readline()

        # MCPサーバーが終了している場合、readline()は空文字列を返す
        if not line:
            raise mcp.MCPConnectionError("サーバーとの接続が切れました。")

        try:
            # JSON-RPCの型に変換する
            return rpc.jsonrpc_message_adapter.validate_json(line)
        except ValidationError as e:
            raise mcp.MCPProtocolError(f"サーバから不正なメッセージを受信しました。{line!r}") from e

    def set_protocol_version(self, version: str) -> None:
        """通知を受け取るがstdioでは何もしない.

        httpではヘッダーに設定するため保存する.

        Args:
            version (str): MCPプロトコルのバージョン
        """
        pass

    def close(self) -> None:
        """stdio接続されているサーバーとの接続を閉じる."""
        # クラス内に　process属性が存在しているか and sub_processが終了していないか
        if not hasattr(self, 'process') or self.process.poll() is not None:
            return
        assert self.process.stdin is not None

        # 1. EOFを送る EOF=0
        self.process.stdin.close()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:

            # 2. 正常終了信号を送る SIGTERM=-15
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:

                # 3. 強制終了信号を送る terminater「Hasta la vista, baby.」 SIGKILL=-9
                self.process.kill()
                self.process.wait()

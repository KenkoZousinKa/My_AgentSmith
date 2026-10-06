import time
import shlex
import subprocess
from pydantic import ValidationError

from src.mcp_core.models import jsonrpc as rpc
from src.mcp_core.models import mcpmodel as mcp


class StdioClientTransport:
    def __init__(self, command: str) -> None:
        self.command: str = command
        self.process: subprocess.Popen[str]
        self.mcp_version: str

    def open(self) -> None:
        """MCPサーバーとの接続をStdioで確立する."""
        # サーバープロセスを起動し、入出力をパイプで繋ぐ
        # text=True により、バイト列ではなく文字列として扱える
        # 例: command = ["python", "mcp_tools_mbpp.py"]
        self.process = subprocess.Popen(
            args=shlex.split(self.command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True       # 送信時に文字列が壊れないように
        )
        # 起動直後の即死チェック
        time.sleep(0.1)
        if self.process.poll() is not None:
            raise mcp.MCPConnectionError(f"サーバーの起動に失敗しました。コマンド: {self.command}")

    def send(self, message: rpc.JSONRPCMessage) -> None:
        """封筒を1行の JSON にしてサーバーの stdin に書き込む."""
        assert self.process.stdin is not None
        self.process.stdin.write(message.model_dump_json(by_alias=True, exclude_unset=True) + "\n")
        self.process.stdin.flush()

    def receive(self) -> rpc.JSONRPCMessage:
        """サーバーの stdout から1通読み、JSON-RPCの型に変換して返す."""
        assert self.process.stdout is not None
        # MCPサーバーからの標準出力を待つ
        line = self.process.stdout.readline()
        if not line:
            raise mcp.MCPConnectionError("サーバーとの接続が切れました。")

        # JSON-RPCの型に変換する
        try:
            return rpc.jsonrpc_message_adapter.validate_json(line)
        except ValidationError as e:
            raise mcp.MCPProtocolError(f"サーバから不正なメッセージを受信しました。{line!r}") from e

    def set_protocol_version(self, version: str) -> None:
        """MCPサーバーのバージョンを保存する."""
        pass

    def close(self) -> None:
        """プロセスを安全に終了させる"""
        # process属性が存在しているか　and sub_processが終了していないか
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

import time
import shlex
import subprocess

from src.mcp_core.models import jsonrpc as rpc
from src.mcp_core.models import mcpmodel as mcp


class StdioClientTransport:
    def __init__(self, command: str) -> None:
        self.command: str = command
        self.process: subprocess.Popen[str]

    def open(self) -> None:
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
    def send(self, message: rpc.JSONRPCMessage) -> None: ...
    def receive(self) -> rpc.JSONRPCMessage: ...
    def set_protocol_version(self, version: str) -> None: ...
    def close(self) -> None: ...

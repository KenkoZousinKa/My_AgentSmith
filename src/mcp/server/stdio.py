"""Server側のstdio接続クラス."""

import sys
from typing import Callable

from src.mcp.models import jsonrpc as rpc


class StdioServerTransport:
    """Clientとの接続を標準入出力で行うTransportクラス."""
    def serve(self, handle: Callable[[str], rpc.JSONRPCResponse | rpc.JSONRPCError | None]) -> None:
        """標準入力からリクエストを受け取り、標準出力へレスポンスを返すループを開始する.

        Args:
            handle (Callable[[str], rpc.JSONRPCResponse | rpc.JSONRPCError | None]): クライアントからのリクエストを受け取り、レスポンスを返す関数
        """
        # 1.stdinを受け取る
        for line in sys.stdin:  # EOFでループが終わる clientが異常終了した場合は子プロセスにEOFが届く
            # 空行は無視
            if not line.strip():
                continue
            # 2. handle関数がサーバー処理を行った後返答を返す
            response = handle(line)
            if response is not None:
                self._write(response)

    def _write(self, msg: rpc.JSONRPCResponse | rpc.JSONRPCError) -> None:
        """渡されたレスポンスオブジェクトをstrにして標準出力へ書き込む.

        Args:
            msg (rpc.JSONRPCResponse | rpc.JSONRPCError): 標準出力に書き込むレスポンスオブジェクト
        """
        # exclude_unset: オブジェクト内で入力しなかった要素をJSONに含めない
        sys.stdout.write(msg.model_dump_json(by_alias=True, exclude_unset=True) + "\n")
        sys.stdout.flush()

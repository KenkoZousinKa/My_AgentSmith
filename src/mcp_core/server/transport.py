import sys
from typing import Callable

from src.mcp_core.models import jsonrpc as rpc


class StdioServerTransport:
    def serve(self, handle: Callable[[str], rpc.JSONRPCResponse | rpc.JSONRPCError | None]) -> None:
        """サーバーの受付(Stdio)を担当する."""
        # 1.stdinを受け取る
        for line in sys.stdin:  # EOFでループが終わる clientが異常終了した場合は子プロセスにEOFが届く
            if not line.strip():  # '\n'などのから文字を読み飛ばす
                continue
            # 2. クライアントへの返答を生成
            response = handle(line)
            if response is not None:
                self._write(response)

    def _write(self, msg: rpc.JSONRPCResponse | rpc.JSONRPCError) -> None:
        """渡されたレスポンスオブジェクトをstrにして標準出力へ書き込む."""
        # exclude_unsetはコードで指定しなかった値、exclude_noneは値がNoneのものを消してjson文字列にする。
        sys.stdout.write(msg.model_dump_json(by_alias=True, exclude_unset=True) + "\n")
        sys.stdout.flush()

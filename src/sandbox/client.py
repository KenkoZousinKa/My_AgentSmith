import subprocess
import json
import uuid
import time
from typing import Any


class StdioMCPClient:
    def __init__(self, command: str):
        # サーバープロセスを起動し、入出力をパイプで繋ぐ
        # text=True により、バイト列ではなく文字列として扱える
        # 例: command = ["python", "mcp_tools_mbpp.py"]
        self.process = subprocess.Popen(
            args=command.split(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True       # 文字列として送信する
        )
        # 起動直後の即死チェック
        time.sleep(0.1)
        if self.process.poll() is not None:
            raise RuntimeError(f"サーバーの起動に失敗しました。コマンド: {command}")

    def __del__(self) -> None:
        """ガベージコレクション時のフェイルセーフ"""
        self.close()

    def close(self) -> None:
        """プロセスを安全に終了させる"""
        if hasattr(self, 'process') and self.process.poll() is None:
            self.process.terminate()
            self.process.wait()

    def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """MCPサーバーにツールのリストを要求する"""

        requesut_data = {
            'jsonrpc': '2.0',
            'id': uuid.uuid4().hex,
            'method': "tools/list"
        }
        if params:
            requesut_data['params'] = params
        assert self.process.stdin is not None
        assert self.process.stdout is not None

        # 1.ツール要求のリクエストをMCPサーバーの標準入力に送る flushで即送信
        self.process.stdin.write(json.dumps(requesut_data) + '\n')
        self.process.stdin.flush()

        # 2.MCPサーバーからの標準出力を待つ
        responce_line = self.process.stdout.readline()
        if not responce_line:
            raise RuntimeError("サーバーから応答がありません。")

        data: dict[str, Any] = json.loads(responce_line)
        return data


if __name__ == "__main__":
    print("[Client] MCPクライアントを起動します...")
    client = StdioMCPClient("python mcp_tools_mbpp.py")

    try:
        print("[Client] ツールリストをリクエスト中...")
        response = client.get_tools_list()

        print("\n[Client] サーバーからの回答を受信しました:")
        print(json.dumps(response, indent=2, ensure_ascii=False))

    finally:
        # プログラムが正常終了しようと、エラーでクラッシュしようと
        # 必ず最後にここを通って、子プロセスにトドメを刺す
        client.process.terminate()
        client.process.wait()   # 完全に死ぬまで待つ
        print("[Client] サーバープロセスを終了しました。")

    # def call_tool(self, tool_name: str, args: dict[str, str]) -> dict[str, str]:
    #     """サーバーにツール実行を依頼し、結果を受け取る"""
    #     # 1. リクエストJSONを作成
    #     request_data = {
    #         "method": "call_tool",
    #         "tool": tool_name,
    #         "args": args
    #     }

    #     # 2. サーバーの標準入力に書き込み、改行で区切る
    #     self.process.stdin.write(json.dumps(request_data) + "\n")

    #     # 【超重要】バッファに溜めず、即座に送信を確定させる
    #     self.process.stdin.flush()

    #     # 3. サーバーからの標準出力を1行読み取る（結果が来るまで待機）
    #     response_line = self.process.stdout.readline()

    #     if not response_line:
    #         raise RuntimeError("MCPサーバーとの通信が切断されました")

    #     # 4. 受け取ったJSONを辞書に戻して返す
    #     return json.loads(response_line)

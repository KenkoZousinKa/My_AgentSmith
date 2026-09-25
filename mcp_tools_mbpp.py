import sys
import json


def run_tests(code: str, test_list: list[str]) -> dict[str, bool | str]:
    """実際のツール処理（ここではダミー）"""
    return {"success": True, "output": "テスト成功しました"}


def main() -> None:
    while True:
        line = sys.stdin.readline()
        if not line:
            break  # 親が死んだら終了

        try:
            request = json.loads(line)

            # tools/list リクエストが来た場合
            if request.get("method") == "tools/list":
                response = {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "result": {
                        "tools": [
                            {
                                "name": "run_tests",
                                "description": "コードとテストのリストを実行し、成功か失敗かを返します。",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "code": {"type": "string"},
                                        "test_list": {"type": "array", "items": {"type": "string"}}
                                    },
                                    "required": ["code", "test_list"]
                                }
                            }
                        ]
                    }
                }

            # # tool呼び出し
            # if request.get("method") == "call_tool":
            #     tool_name = request.get("tool")
            #     args = request.get("args", {})

            #     if tool_name == "run_tests":
            #         # ツールの実行
            #         result = run_tests(args.get("code"), args.get("test_list"))

            #         # 2. 結果をJSONにして標準出力へ返す
            #         response = {"result": result}
            #         sys.stdout.write(json.dumps(response) + "\n")

            #         # 【超重要】バッファをフラッシュして確実に届ける
            #         sys.stdout.flush()

                # クライアントへ返信
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

        except Exception as e:
            error_res = {"jsonrpc": "2.0", "error": {"message": str(e)}}
            sys.stdout.write(json.dumps(error_res) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()


# def main() -> None:
#     # 無限ループでリクエストを待ち受ける
#     while True:
#         # 1. クライアントからの入力を1行読み取る
#         line = sys.stdin.readline()

#         if not line:
#             # EOF（クライアント側でプロセスが終了した）ならループを抜ける
#             break

#         try:
#             request = json.loads(line)

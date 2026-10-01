"""
引数は code と test_list の2つだけにします。 引数を増やすと、LLM が使い方に迷う原因になります。
返り値は、辞書ではなく JSON 文字列です。 json.dumps({"success": ..., "output": ...}) で作ります。
実行時間の上限は、引数にせず、関数の中の定数として持ちます。 Moulinette の採点も、30秒の上限で実行していました。
LLM に渡す必要のない設定なので、関数の中に閉じ込めておけば十分です。
"""

import json
from src.mcp_server.server import MCPServer

server = MCPServer(name="agent-smith-mbpp", version="0.1.0")


@server.tool()
def run_tests(code: str, test_list: list[str]) -> str:
    """候補の解答コードを、与えられた assert 文のテストで実行する.

    すべてのテストが通ったかを表す success と、実行時の出力 output を含む JSON 文字列を返す.
    """
    return json.dumps({"success": True, "output": "dummy"})


# @server.tool()
# def divide(a: int, b: int) -> str:
#     """a を b で割る(debug)."""
#     return str(a / b)


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()

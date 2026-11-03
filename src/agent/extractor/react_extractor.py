"""ReAct形式のツール呼び出しをPythonコードに変換して抽出するモジュール.

ReActで学習したモデルが出力する
    Action: read_file
    Action Input: {"filepath": "/testbed/x.py"}
形式をサンドボックスがそのまま実行できる
    print(read_file(filepath='/testbed/x.py'))
に変換する。
Action Input はJSON / Pythonの辞書 / 'key=value'の並び、素の値のどれでも対応する。
"""
import re
import ast
import json
from typing import Any

from src.agent.extractor.code_extractor import CodeExtractor
from src.agent.extractor.tools import is_tool_name, render_tool_call, python_literals, literal_for

_ACTION_PATTERN = re.compile(
    r"Action\s*:\s*([A-Za-z_][A-Za-z0-9_]*)[ \t]*\r?\n\s*Action\s*Input\s*:\s*(.*?)"
    r"(?=\n\s*(?:Action|Thought|Observation)\s*:|\Z)",
    re.DOTALL | re.IGNORECASE
)


def _parse_mapping(text: str) -> dict[Any, Any] | None:
    try:
        value: Any = json.loads(text)
    except json.JSONDecodeError:
        # {'code': 'x'}のようなシングルクォートで各モデルもあり。literal_eval()は式自体を実行しないので安全に使える。
        try:
            value = ast.literal_eval(text)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            return None

    return value if isinstance(value, dict) else None


def _arguments(raw: str) -> dict[str, str]:
    """Action Input を引数: Pythonリテラルの辞書に変換する.

    1. 辞書(辞書 / Pythonリテラル)ならキーごとに展開する。
    2. 'key=value'のカンマ区切りの並びならそれぞれを引数にする。
    3. どちらでもなければ全体を1つの値として"input"という名前で渡す。
        (final_answerなら位置引数になる。render_tool_call()で1つの引数なら位置引数にする。)

    Args:
        raw (str): Action Input の文字列。

    Returns:
        dict[str, str]: 引数名: Pythonリテラルの文字列の辞書。
    """
    text = raw.strip()
    if not text:
        return {}

    mapping = _parse_mapping(text) if text.startswith("{") else None
    if mapping is not None:
        return python_literals(mapping)

    if "=" in text and not text.startswith("{"):
        pairs: dict[str, str] = {}

        for chunk in text.split(","):
            name, _, value = chunk.partition("=")
            if name.strip().isidentifier():
                pairs[name.strip()] = literal_for(value)

        if pairs:
            return pairs

    return {"input": literal_for(text)}


class ReactCodeExtractor(CodeExtractor):
    """ReAct形式のツール呼び出しをPythonコードに変換して抽出する具象クラス."""

    def extract(self, llm_output: str) -> str | None:
        """LLMの出力テキストからReactコードを抽出する.

        Args:
            llm_output (str): LLMの出力テキスト

        Returns:
            str | None: 変換されたPythonコード(1アクション1行)。ReAct呼び出しがなければNone。
        """
        lines = [
            render_tool_call(tool_name, _arguments(action_input))
            for tool_name, action_input in _ACTION_PATTERN.findall(llm_output)
            if is_tool_name(tool_name)
        ]

        return "\n".join(lines) if lines else None

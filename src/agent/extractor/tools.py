"""ツール呼び出しをPythonの呼び出し文に変換する共通部品を提供するモジュール.

XML / JSON-Hermes / ReAct の各抽出器はツール名と引数を取り出す部分が形式ごとの責務で、
Pythonの呼び出し文を組み立てる部分は共通の責務であるため、ここにまとめる。
非Python形式は等価なPython関数呼び出しに変換してからサンドボックスに渡す。

下記を提供
"""
import json
import keyword
from typing import Any

_FINAL_ANSWER = "final_answer"


def literal_for(raw: str) -> str:
    """XML / ReAct 由来の素の値をPythonリテラルの文字列に変換する.

    数値、真偽値、None、JSONの配列 / 辞書は型を持ち、それ以外は文字列に変換する。
    - MBPPのrun_testsはtest_list: list[str]を受け取るので"[...]"を文字列のまま渡せない。

    Args:
        raw (str): タグに囲まれた素の値。

    Returns:
        str: Pythonソースに埋め込めるリテラルの文字列。
    """
    value = raw.strip()
    if value.startswith(("[", "{")):
        # JSONの配列 / 辞書は型を持つので、文字列にせずそのまま返す。
        try:
            return repr(json.loads(value))
        except json.JSONDecodeError:
            pass

    lowered = value.lower()
    if lowered in ("true", "false"):
        return "True" if lowered == "true" else "False"

    if lowered in ("none", "null"):
        return "None"

    try:
        return repr(int(value))
    except ValueError:
        pass

    try:
        return repr(float(value))
    except ValueError:
        pass

    return repr(value)  # 文字列として返す。reprでエスケープされる。


def is_tool_name(name: object) -> bool:
    """Pythonの関数名として呼び出せる名前かを返す.

    Args:
        name (object): ツール名の候補。

    Returns:
        bool: 識別子でかつ予約語(classなど)でなければTrue。
    """
    return isinstance(name, str) and name.isidentifier() and not keyword.iskeyword(name)


def render_tool_call(tool_name: str, arguments: dict[str, str]) -> str:
    """ツール名と引数(値はリテラル表現済み)からPythonの呼び出し文を1行組み立てる.

    Args:
        tool_name (str): ツール名。is_tool_name()でTrueを返す文字列であること。
        arguments (dict[str, str]): 引数の辞書。引数名: Pythonリテラルの文字列。

    Returns:
        str: Pythonの呼び出し文。引数がなければ()だけの呼び出しになる。
            str: "print(read_file(filepath='/testbed/x.py'))"
    """
    # 引数が1つでツール名がfinal_answerなら、print(final_answer(value))の形にする。
    if tool_name == _FINAL_ANSWER and len(arguments) == 1:
        (only_value, ) = arguments.values()
        return f"print({tool_name}({only_value}))"

    # 引数が1つでツール名がfinal_answer以外なら、print(tool_name(value))の形にする。
    rendered = [
        f"{name}={value}" for name, value in arguments.items() if is_tool_name(name)
    ]
    return f"print({tool_name}({', '.join(rendered)}))"


def python_literals(values: dict[Any, Any]) -> dict[str, str]:
    """JSONなどで型付の値になっている引数を、Pythonリテラルの表現の辞書にする.

    Args:
        values (dict[Any, Any]): 引数名: 値(文字列、数値、リスト、辞書など)。

    Returns:
        dict[str, str]: Pythonリテラルの文字列に変換された引数の辞書。
            引数名(文字列化): repr()したリテラル表現。
    """
    return {str(name): repr(value) for name, value in values.items()}

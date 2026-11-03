"""複数フォーマットのコード抽出(課題 V.1)のテスト.

非Python形式は「等価なPython関数呼び出しに変換されてからサンドボックスへ渡る」ことが要件。
文字列の部分一致ではなく、変換後のコードを偽のツールを置いた名前空間で実際にexec()し、
ツールに届いた引数(名前・値・型)を確かめる。
"""
import json
from typing import Any

import pytest

from src.agent.extractor.composite_extractor import CompositeCodeExtractor
from src.agent.extractor.json_hermes_extractor import JSONHermesCodeExtractor
from src.agent.extractor.python_extractor import PythonCodeExtractor
from src.agent.extractor.react_extractor import ReactCodeExtractor
from src.agent.extractor.xml_extractor import XMLCodeExtractor


class _FinalAnswer(BaseException):
    """サンドボックスのfinal_answerと同じく、呼ばれたら実行を止める."""


def _run(code: str) -> list[tuple[str, tuple[Any, ...], dict[str, Any]]]:
    """変換後のコードを偽のツールで実行し、呼ばれた順に(ツール名, 位置引数, キーワード引数)を返す.

    Args:
        code (str): 抽出器が返したPythonコード。

    Returns:
        list[tuple[str, tuple[Any, ...], dict[str, Any]]]: ツールの呼び出し記録。
    """
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def make_tool(name: str) -> Any:
        def tool(*positional: Any, **keywords: Any) -> str:
            calls.append((name, positional, keywords))
            return f"<{name} result>"
        return tool

    def final_answer(value: Any = None) -> None:
        calls.append(("final_answer", (value,), {}))
        raise _FinalAnswer

    namespace: dict[str, Any] = {
        "final_answer": final_answer,
        **{name: make_tool(name) for name in ("read_file", "search_code", "list_files", "run_tests")},
    }
    try:
        exec(compile(code, "<extracted>", "exec"), namespace)
    except _FinalAnswer:
        pass
    return calls


def test_python_block_is_primary() -> None:
    """```python ブロックはそのまま取り出される(主系)."""
    output = "Thought: go\n```python\nprint(1 + 1)\n```\n<end_code>"
    assert PythonCodeExtractor().extract(output) == "print(1 + 1)"


def test_xml_tool_call_keeps_names_and_types() -> None:
    """XMLツール呼び出しが、引数名と型(数値は数値)を保ったPython呼び出しになる."""
    output = (
        'I will read it.\n<invoke name="read_file">'
        '<parameter name="filepath">/testbed/x.py</parameter>'
        '<parameter name="start_line">1</parameter></invoke>'
    )
    code = XMLCodeExtractor().extract(output)
    assert code is not None
    assert _run(code) == [("read_file", (), {"filepath": "/testbed/x.py", "start_line": 1})]


def test_xml_multiline_code_parameter_is_passed_verbatim() -> None:
    """複数行のコード(インデント・比較演算子・クォート入り)がそのまま文字列で届く."""
    source = "def f(x):\n    return x < 3 and 'a' != \"b\""
    output = (
        '<invoke name="run_tests">\n<parameter name="code">' + source + "</parameter>\n"
        '<parameter name="test_list">["assert f(1)"]</parameter>\n</invoke>'
    )
    code = XMLCodeExtractor().extract(output)
    assert code is not None
    assert _run(code) == [("run_tests", (), {"code": source, "test_list": ["assert f(1)"]})]


def test_xml_multiple_invocations_run_in_order() -> None:
    """1つの応答に複数の呼び出しがあれば、書かれた順に1行ずつ実行される."""
    output = (
        '<invoke name="list_files"><parameter name="directory">/testbed</parameter></invoke>'
        '<invoke name="read_file"><parameter name="filepath">/testbed/a.py</parameter></invoke>'
    )
    code = XMLCodeExtractor().extract(output)
    assert code is not None
    assert [name for name, _, _ in _run(code)] == ["list_files", "read_file"]


def test_json_hermes_tagged_call_with_nested_braces() -> None:
    """<tool_call>の引数のコードに { } があっても、JSON全体が読める."""
    source = "def f(items):\n    return {key: 1 for key in items}"
    output = (
        '<tool_call>{"name": "run_tests", "arguments": {"code": '
        + _json_string(source) + ', "test_list": ["assert f([1]) == {1: 1}"]}}</tool_call>'
    )
    code = JSONHermesCodeExtractor().extract(output)
    assert code is not None
    assert _run(code) == [("run_tests", (), {"code": source, "test_list": ["assert f([1]) == {1: 1}"]})]


def test_json_bare_object_with_nested_braces() -> None:
    """タグ無しの素のJSONでも、引数の { } で途中切れせずに読める."""
    output = (
        "I'll test it.\n"
        '{"name": "run_tests", "arguments": {"code": "x = {1: 2}", "test_list": []}}\n'
        "Then submit."
    )
    code = JSONHermesCodeExtractor().extract(output)
    assert code is not None
    assert _run(code) == [("run_tests", (), {"code": "x = {1: 2}", "test_list": []})]


def test_json_arguments_given_as_a_json_string() -> None:
    """OpenAI形式のように arguments が「JSONの文字列」でも展開できる."""
    output = '<tool_call>{"name": "search_code", "arguments": "{\\"pattern\\": \\"validate_email\\"}"}</tool_call>'
    code = JSONHermesCodeExtractor().extract(output)
    assert code is not None
    assert _run(code) == [("search_code", (), {"pattern": "validate_email"})]


def test_json_object_without_tool_shape_is_ignored() -> None:
    """name / arguments の形でないJSONはツール呼び出しとみなさない."""
    assert JSONHermesCodeExtractor().extract('The result is {"a": 1, "b": 2}.') is None


@pytest.mark.parametrize(
    "llm_output",
    [
        '<tool_call>{"name": "final_answer"}</tool_call>',
        'I will call {"name": "read_file", "arguments": ["/a"]} next.',
        '<tool_call>{"name": "read_file", "arguments": "[\\"/a\\"]"}</tool_call>',
    ],
)
def test_json_tool_call_without_argument_mapping_is_ignored(llm_output: str) -> None:
    """argumentsが無い / 辞書でないJSONは、例外にせずツール呼び出しとみなさない."""
    assert JSONHermesCodeExtractor().extract(llm_output) is None
    assert CompositeCodeExtractor().extract(llm_output) is None


def test_react_json_input() -> None:
    """ReActのAction / Action Input(JSON)がPython呼び出しになる."""
    output = 'Thought: inspect\nAction: list_files\nAction Input: {"directory": "/testbed", "pattern": "*.py"}'
    code = ReactCodeExtractor().extract(output)
    assert code is not None
    assert _run(code) == [("list_files", (), {"directory": "/testbed", "pattern": "*.py"})]


def test_react_python_dict_input_with_single_quotes() -> None:
    """シングルクォートの辞書(JSONとしては不正)も読める."""
    output = "Action: read_file\nAction Input: {'filepath': '/testbed/x.py', 'start_line': 3}"
    code = ReactCodeExtractor().extract(output)
    assert code is not None
    assert _run(code) == [("read_file", (), {"filepath": "/testbed/x.py", "start_line": 3})]


def test_react_key_value_input() -> None:
    """`key=value` の並びも引数になる."""
    output = "Action: read_file\nAction Input: filepath=/testbed/x.py, start_line=10"
    code = ReactCodeExtractor().extract(output)
    assert code is not None
    assert _run(code) == [("read_file", (), {"filepath": "/testbed/x.py", "start_line": 10})]


def test_react_stops_before_a_hallucinated_observation() -> None:
    """モデルが自分で書いたObservation以降は、Action Inputに含めない."""
    output = 'Action: list_files\nAction Input: {"directory": "/testbed"}\nObservation: a.py b.py'
    code = ReactCodeExtractor().extract(output)
    assert code is not None
    assert _run(code) == [("list_files", (), {"directory": "/testbed"})]


@pytest.mark.parametrize("arguments", ['{"answer": "def f():\\n    return 1"}', '{"code": "def f():\\n    return 1"}'])
def test_react_final_answer_with_any_argument_name(arguments: str) -> None:
    """final_answer は引数名が違っても(answer / code)、値が1つなら位置引数で届く."""
    output = f"Thought: done\nAction: final_answer\nAction Input: {arguments}"
    code = ReactCodeExtractor().extract(output)
    assert code is not None
    assert _run(code) == [("final_answer", ("def f():\n    return 1",), {})]


def test_reserved_word_tool_name_is_not_converted() -> None:
    """予約語(class など)はツール名として変換しない(実行するとSyntaxErrorになるため)."""
    assert XMLCodeExtractor().extract('<invoke name="class"><parameter name="x">1</parameter></invoke>') is None
    assert JSONHermesCodeExtractor().extract('<tool_call>{"name": "class", "arguments": {}}</tool_call>') is None


def test_no_recognisable_format_returns_none() -> None:
    """どの形式でもない素の文章はNone(再促し対象)になる."""
    assert CompositeCodeExtractor().extract("I think the answer is 42, but I will not run code.") is None


def test_composite_prefers_python_block() -> None:
    """Pythonブロックと他形式が混在する場合はPythonブロックを優先する."""
    output = (
        '<tool_call>{"name": "read_file", "arguments": {"filepath": "/a"}}</tool_call>\n'
        "```python\nprint('real code')\n```"
    )
    assert CompositeCodeExtractor().extract(output) == "print('real code')"


def test_composite_falls_back_to_tool_call_format() -> None:
    """Pythonブロックが無ければ他形式にフォールバックして変換する."""
    output = 'Action: run_tests\nAction Input: {"code": "def f(): pass", "test_list": ["assert True"]}'
    code = CompositeCodeExtractor().extract(output)
    assert code is not None
    assert _run(code) == [("run_tests", (), {"code": "def f(): pass", "test_list": ["assert True"]})]


def test_composite_xml_with_code_is_not_taken_by_bare_python_salvage() -> None:
    """XMLの引数にPythonの代入文があっても、Python抽出器の「フェンス無し救済」に横取りされない."""
    output = (
        '<invoke name="run_tests">\n<parameter name="code">result = 1\nprint(result)</parameter>\n'
        '<parameter name="test_list">[]</parameter>\n</invoke>'
    )
    code = CompositeCodeExtractor().extract(output)
    assert code is not None
    assert _run(code) == [("run_tests", (), {"code": "result = 1\nprint(result)", "test_list": []})]


def _json_string(text: str) -> str:
    """文字列をJSONの文字列リテラルにする(テストの入力を組み立てる補助)."""
    return json.dumps(text)

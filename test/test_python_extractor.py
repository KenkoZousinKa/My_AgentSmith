"""PythonCodeExtractor の単体テスト."""
import pytest

from src.agent.extractor.python_extractor import (
    SALVAGE_ESCAPED_QUOTES,
    SALVAGE_UNCLOSED_FENCE,
    SALVAGE_UNFENCED,
    SALVAGE_UNMATCHED_CLOSERS,
    PythonCodeExtractor,
    salvage_kind,
)


@pytest.fixture
def extractor() -> PythonCodeExtractor:
    """テスト対象の抽出器を返す."""
    return PythonCodeExtractor()


def test_extracts_single_block(extractor: PythonCodeExtractor) -> None:
    """前後に地の文がある単一ブロックからコードだけ取れる."""
    text = "説明文\n```python\nprint('hi')\n```\n続き"
    assert extractor.extract(text) == "print('hi')"


def test_joins_multiple_blocks_when_valid(extractor: PythonCodeExtractor) -> None:
    """複数ブロックは、連結して構文が通るなら順に全部実行する(定義と検証を分けて書くモデル対策)."""
    text = (
        "定義:\n```python\ndef f():\n    return 1\n```\n"
        "検証:\n```python\nprint(f())\n```\n"
    )
    assert extractor.extract(text) == "def f():\n    return 1\n\nprint(f())"


def test_returns_last_block_when_join_is_invalid(extractor: PythonCodeExtractor) -> None:
    """連結すると構文エラーになる場合は、従来どおり最後のブロックを返す."""
    text = (
        "例:\n```python\nif x:\n```\n"
        "本命:\n```python\nx = 2\nprint(x)\n```\n"
    )
    assert extractor.extract(text) == "x = 2\nprint(x)"


def test_does_not_join_when_an_earlier_block_submits(extractor: PythonCodeExtractor) -> None:
    """最後以外のブロックが final_answer() を呼ぶなら連結せず、最後のブロックだけを返す.

    final_answer() は呼ばれた時点で実行を止めるので、連結すると前のブロックの下書きが提出される。
    """
    text = (
        "下書き:\n```python\nfinal_answer('def f():\\n    return 0')\n```\n"
        "直した版:\n```python\nfinal_answer('def f():\\n    return 1')\n```\n"
    )
    assert extractor.extract(text) == "final_answer('def f():\\n    return 1')"
    assert salvage_kind(text) is None


def test_final_answer_inside_a_string_does_not_block_joining(extractor: PythonCodeExtractor) -> None:
    """文字列の中の final_answer という文字は呼び出しではないので、連結を止めない."""
    text = (
        "```python\nhint = 'call final_answer(x) at the end'\n```\n"
        "```python\nprint(hint)\n```\n"
    )
    assert extractor.extract(text) == "hint = 'call final_answer(x) at the end'\n\nprint(hint)"


def test_returns_none_when_no_block(extractor: PythonCodeExtractor) -> None:
    """コードブロックが無ければ None(D-a)."""
    assert extractor.extract("コードはありません") is None


def test_ignores_non_python_fence(extractor: PythonCodeExtractor) -> None:
    """python/py 以外の言語ラベルは拾わない."""
    assert extractor.extract("```js\nconsole.log(1)\n```") is None


def test_accepts_py_and_uppercase_label(extractor: PythonCodeExtractor) -> None:
    """py / 大文字ラベルも受け付ける(点2)."""
    assert extractor.extract("```py\nprint(1)\n```") == "print(1)"
    assert extractor.extract("```Python\nprint(2)\n```") == "print(2)"


def test_rstrips_trailing_blank_lines(extractor: PythonCodeExtractor) -> None:
    """末尾の空行/空白は除去する(点3)."""
    assert extractor.extract("```python\nx = 1\n\n\n```") == "x = 1"


def test_multiline_code_preserved(extractor: PythonCodeExtractor) -> None:
    """複数行コードのインデント・改行(末尾以外)が保たれる."""
    text = "```python\ndef f():\n    return 1\n```"
    assert extractor.extract(text) == "def f():\n    return 1"


def test_closing_fence_without_trailing_newline(extractor: PythonCodeExtractor) -> None:
    """閉じフェンスが独立行なら、その後に改行が無くても取れる."""
    assert extractor.extract("```python\nprint('x')\n```") == "print('x')"


def test_inline_fence_is_ignored(extractor: PythonCodeExtractor) -> None:
    """行頭でないフェンス(地の文の途中)は拾わない(点4)."""
    assert extractor.extract("見て ```python x``` ね") is None


def test_nested_backticks_in_string(extractor: PythonCodeExtractor) -> None:
    """コード中の行頭でない ``` では閉じない(点1)."""
    text = "```python\ns = '```'\nprint(s)\n```"
    assert extractor.extract(text) == "s = '```'\nprint(s)"


def test_unfenced_final_answer_is_salvaged(extractor: PythonCodeExtractor) -> None:
    """フェンス無しで素のPythonを返した応答も救済して実行する.

    実測(MBPPタスク235 step1)でgpt-ossが final_answer(三連引用符の関数ソース) をフェンス無しで
    出力し、抽出できず1反復(600トークン)を丸損した。A13(崩れた形式の解釈)が要求する救済。
    """
    text = 'final_answer("""def f(n):\n    return n * 2\n""")'
    assert extractor.extract(text) == text
    assert salvage_kind(text) == SALVAGE_UNFENCED


def test_unfenced_code_after_prose_is_salvaged(extractor: PythonCodeExtractor) -> None:
    """地の文のあとにフェンス無しのコードが続く場合、コード部分から拾う."""
    text = "Thought: just define it.\ndef f(n):\n    return n + 1\nprint(f(1))"
    assert extractor.extract(text) == "def f(n):\n    return n + 1\nprint(f(1))"
    assert salvage_kind(text) == SALVAGE_UNFENCED


def test_prose_only_is_not_mistaken_for_code(extractor: PythonCodeExtractor) -> None:
    """純粋な散文をコードと誤認しない(構文が通らないものは採用しない)."""
    text = "I think the answer is 42 but I will not write any code block."
    assert extractor.extract(text) is None
    assert salvage_kind(text) is None


def test_salvage_kind_distinguishes_unclosed_fence(extractor: PythonCodeExtractor) -> None:
    """閉じフェンス欠落とフェンス無しを区別する(LLMに返す助言が異なるため)."""
    assert salvage_kind("```python\nprint('x')\n") == SALVAGE_UNCLOSED_FENCE
    assert salvage_kind("```python\nprint('x')\n```") is None


def test_escaped_quotes_outside_string_are_repaired(extractor: PythonCodeExtractor) -> None:
    """文字列の外のクォートのエスケープを戻して実行可能にする.

    実測(MBPPタスク305)でgpt-ossがfew-shotの if report["success"]: を
    if report[\"success\"]: と書き、SyntaxErrorで4反復(1500トークン)を溶かした。
    """
    text = '```python\nreport = {"success": True}\nif report[\\"success\\"]:\n    print(1)\n```'
    code = extractor.extract(text)
    assert code is not None
    compile(code, "<test>", "exec")           # 構文が通る形に直っている
    assert 'report["success"]' in code
    assert salvage_kind(text) == SALVAGE_ESCAPED_QUOTES


def test_repair_keeps_legitimate_escapes_inside_triple_quotes(extractor: PythonCodeExtractor) -> None:
    """三連引用符の中の \\" は正当なので壊さない(一括置換してはいけない)."""
    inner = 'solution = """def f():\n    \\"\\"\\"doc.\\"\\"\\"\n    return 1\n"""'
    text = f"```python\n{inner}\nif True:\n    print(solution)\n```"
    code = extractor.extract(text)
    assert code is not None
    compile(code, "<test>", "exec")
    namespace: dict[str, object] = {}
    exec(code, namespace)                      # 実行しても docstring が壊れていない
    assert '"""doc."""' in str(namespace["solution"])
    assert salvage_kind(text) is None          # もともと構文が通るので救済扱いにしない


def test_extra_closing_brackets_are_removed(extractor: PythonCodeExtractor) -> None:
    """文字列内の括弧まで数えて書き足した閉じ括弧だけを取り除く.

    実測(nemotron-3-super, sympy-14711 step 10): 下の行を書き、unmatched ')' を8反復続けた。
    """
    line = ('print(run_command(command="cd /testbed && python -c \\"from x import N; '
            'print(sum([N.x, (0 * N.x)]))\\""))))')
    text = f"Thought: test it.\n```python\n{line}\n```"
    code = extractor.extract(text)
    assert code == line[:-2]                  # 余分な2個だけが消え、文字列の中は変わらない
    compile(code, "<test>", "exec")
    assert salvage_kind(text) == SALVAGE_UNMATCHED_CLOSERS


@pytest.mark.parametrize("source", [
    "def f(:\n    pass)",       # 閉じ括弧の余りではない構文エラー
    "print((1)",                # 閉じ括弧が足りない(どこに足すかは推測しない)
])
def test_other_syntax_errors_are_not_rewritten(extractor: PythonCodeExtractor, source: str) -> None:
    """閉じ括弧の余り以外の構文エラーは書き換えず、そのまま実行させて構文エラーを返す."""
    text = f"```python\n{source}\n```"
    assert extractor.extract(text) == source
    assert salvage_kind(text) is None


def test_valid_code_is_left_untouched(extractor: PythonCodeExtractor) -> None:
    """構文が通るコードには一切手を入れない."""
    text = '```python\nprint("a\\"b")\n```'
    assert extractor.extract(text) == 'print("a\\"b")'
    assert salvage_kind(text) is None


def test_opening_fence_on_the_thought_line_is_matched(extractor: PythonCodeExtractor) -> None:
    """Thoughtと同じ行に開始フェンスを書かれても正規ブロックとして扱う.

    実測(MBPPタスク251/395/108)でモデルが改行を入れずに ```python を書き、行頭アンカーの
    せいで厳格パターンが0件マッチ -> 未閉鎖救済に落ちて末尾の ``` まで取り込み構文エラー、
    さらに「出力上限で切られた」という誤った原因をLLMに伝えていた。
    """
    text = "Thought: do it.```python\nx = 1\nprint(x)\n```\n"
    assert extractor.extract(text) == "x = 1\nprint(x)"
    assert salvage_kind(text) is None          # 救済ではなく正規ブロック扱い


def test_unclosed_salvage_drops_a_trailing_fence(extractor: PythonCodeExtractor) -> None:
    """未閉鎖救済の本体末尾に閉じフェンスが残っていたら落とす(構文エラー防止)."""
    code = extractor.extract("```python\nprint(1)\n```\ntrailing prose\n```python\nprint(2)\n")
    assert code is not None
    compile(code, "<test>", "exec")
    assert "```" not in code


def test_unwraps_json_code_payload(extractor: PythonCodeExtractor) -> None:
    """```python の中が {"code": "..."} の包みなら中のコードを取り出す(nemotron実測)."""
    text = '```python\n{\n    "code": "def f():\\n    return 1\\nprint(f())"\n}\n```'
    assert extractor.extract(text) == "def f():\n    return 1\nprint(f())"


def test_plain_dict_literal_is_not_unwrapped(extractor: PythonCodeExtractor) -> None:
    """codeキーを持たない普通のdictはそのまま実行する."""
    text = '```python\n{"a": 1}\n```'
    assert extractor.extract(text) == '{"a": 1}'


def test_strip_stop_sequences_removes_leaked_prefix() -> None:
    """閉じフェンスの直後に漏れた停止シーケンスの前半を取り除き、閉じフェンスを認識できる."""
    from src.agent.extractor.python_extractor import strip_stop_sequences
    leaked = "Thought: x\n```python\nprint(1)\n```<end_code"
    cleaned = strip_stop_sequences(leaked, ["<end_code>"])
    assert cleaned.rstrip().endswith("```")
    assert PythonCodeExtractor().extract(cleaned) == "print(1)"


def test_strip_stop_sequences_keeps_normal_text() -> None:
    """完全な停止シーケンスは除き、残骸の無い本文は変えない."""
    from src.agent.extractor.python_extractor import strip_stop_sequences
    assert strip_stop_sequences("a\n```\n<end_code>", ["<end_code>"]) == "a\n```\n"
    assert strip_stop_sequences("x = a < b", ["<end_code>"]) == "x = a < b"

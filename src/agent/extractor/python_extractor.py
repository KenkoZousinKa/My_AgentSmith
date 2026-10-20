"""Pythonコード用コード抽出機能を提供するモジュール.

LLM出力中の```python```フェンスブロックを抽出する具象クラス。
崩れた出力は救済し、その種類をsalvage_kind()で返し、orchstrator が[MALFORMED_CODE]としてLLMに伝える。

下記を提供
- PythonCodeExtractor
    - extract()
- salvage_kind()
    - 崩れの種類を返す
- strip_stop_sequence()
    - 停止シーケンスを取り除く
"""
import re
import ast

from src.agent.extractor.code_extractor import CodeExtractor

# ```python``` Pythonコードブロック
# [ \t]* ラベルのあとの空白、タブを許可
# \r?\n コードブロックあとの改行を許可(開始フェンスと地の文の境目)
# (.*?) コード本体。re.DOTALLで改行を含む任意の文字列を許可
# \r?\n? コードブロックの終わりの直前に改行を許可
# Thoughtと同じ行でフェンスを作成することがある
_PYTHON_CODE_BLOCK_PATTERN = re.compile(
    r"```[ \t]*(?:python|py)[ \t]*\r?\n(.*?)\r?\n[ \t]*```[ \t]*$",
    re.DOTALL | re.MULTILINE | re.IGNORECASE
)
# 未閉鎖ブロックの救済で本体末尾に閉じフェンスが残っていたら落とす。
_TRAILING_FENCE_PATTERN = re.compile(r"\r?\n[ \t]*```[ \t]*\Z")

# 閉じフェンスがない場合の救済。
# 出力トークン上限で応答が途中で途切れると```pythonのあとが閉じられずに終わる。
# 捨てると1反復分無駄になるので開始フェンス以降を本体として扱う。
# 崩れたブロックを解釈したら明示する要件あり?
_UNCLOSED_CODE_BLOCK_PATTERN = re.compile(
    r"```[ \t]*(?:python|py)[ \t]*\r?\n(.*)\Z",
    re.DOTALL | re.IGNORECASE
)

# フェンスなしのコードブロックの場合の救済。
# 素のPythonを本文に返すモデル用。(gpt-ossのMBPP235で実測した)
# 行頭が明らかにコードの位置から末尾までを候補にし、ast.parseで構文解析できるかを確認する。
_BARE_CODE_START_PATTERN = re.compile(
    r"^[ \t]*(?:final_answer\(|print\(|def |class |import |from |[A-Za-z_]\w*\s*=[^=])",
    re.MULTILINE
)

# 救済したコードがただの名前や文字列出ないことを確かめるために、要求されるASTノードの種類を定義する。
_CODE_LIKE_NODES = (
    ast.Call, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom
)

SALVAGE_UNCLOSED_FENCE = "uncosed_fence"
SALVAGE_UNFENCED = "unfenced"
SALVAGE_ESCAPED_QUOTES = "escaped_quotes"
SALVAGE_JSON_WRAPPED = "json_wrapped"
SALVAGE_MULTIPLE_BLOCKS = "multiple_blocks"
SALVAGE_UNMATCHED_CLOSERS = "unmatched_closers"

# 停止シーケンスの前半だけが本文末尾に漏れたものを取り除くときの最短文字数。
# 例えば停止シーケンスが"<end_code>"の場合、本文末尾に"<end"だけが漏れた場合に取り除く。
_MIN_LEAKED_STOP_PREFIX = 2


def strip_stop_sequence(text: str, stop_sequences: list[str]) -> str:
    """LLM出力から停止シーケンスと残骸を取り除く.

    停止シーケンスはコードの一部ではないので、コード抽出の前に取り除く。
    NVIDIA nemotron-3-superが17/22で``` ```<end_code```した。
    閉じフェンスと同じ行に残骸がある
    -> 閉じフェンスとして認識されない
    -> 未閉鎖ブロックの救済に回る
    -> 残骸ごと実行されSyntaxError

    Args:
        text (str): LLMが生成した出力テキスト全体。
        stop_sequences (list[str]): 停止シーケンスのリスト。

    Returns:
        str: 停止シーケンスと残骸を取り除いた文字列。
    """
    cleaned_text = text
    # まず停止シーケンスをすべて取り除く。
    for stop_sequence in stop_sequences:
        if stop_sequence:
            cleaned_text = cleaned_text.replace(stop_sequence, "")

    # 末尾に停止シーケンスの前半だけが漏れた場合に取り除く。
    stripped_text = cleaned_text.rstrip()
    for stop_sequence in stop_sequences:
        for length in range(len(stop_sequence) - 1, _MIN_LEAKED_STOP_PREFIX - 1, -1):
            if stripped_text.endswith(stop_sequence[:length]):
                return stripped_text[: -length].rstrip() + "\n"

    return cleaned_text


# 文字列の中の括弧まで数えて閉じ括弧を多く書くモデルがあるので、末尾の閉じ括弧を削除して構文が通る形を探す。
# print(run_command(command="python -c \"print(sum([a, (0 * b)]))\""))))
# 末尾の閉じ括弧を多く書きunmatched ')'を8反復続けた。
_UNMATCHED_CLOSERS = re.compile(r"unmatched '([)\]}])'")
# 末尾の閉じ括弧を削除して構文が通る形を探す回数の上限。
_MAX_CLOSER_REMOVALS = 5


def _repair_unmatched_closers(code: str) -> str | None:
    """構文解析で対応しない閉じ括弧がある場合、末尾の閉じ括弧を削除して構文が通る形を探す.

    Args:
        code (str): フェンスから取り出したコード。

    Returns:
        str | None: 修正されたコード文字列、もともと通る場合と修正できない場合はNone
    """
    # はじめに\nで分割して、行ごとに構文解析する。
    # ここsplitしてからast.parseして通すなら_pases()を使ってから分割すれば良くない？
    lines = code.split("\n")
    for attempt in range(_MAX_CLOSER_REMOVALS + 1):
        try:
            # ast.parseで構文解析できるかを確認する。
            ast.parse("\n".join(lines))
            return "\n".join(lines) if attempt else None
        except SyntaxError as error:
            match = _UNMATCHED_CLOSERS.match(error.msg or "")
            index, colum = (error.lineno or 0) - 1, (error.offset or 0) - 1
            if (
                match is None
                or not 0 <= index < len(lines)
                or not 0 <= colum < len(lines[index])
                or lines[index][colum] != match.group(1)
            ):
                return None
            lines[index] = lines[index][:colum] + lines[index][colum + 1 :]

    return None


# コードブロック全体をJSON文字列のようにエスケープしてしまうモデルがあるので、過剰なエスケープを戻す。
# `if report["success"]:` のようなコードが `if report[\"success\"]:` のように文字列外のバックスラッシュで
# エスケープされSyntaxErrorになることがある。
# 三連引用符ないの\"は正当なので一括置換はできないため、構文エラーの行に限り適用。
_MAX_UNESCAPE_PASSES = 30


def _repair_escaped_quotes(code: str) -> str | None:
    """構文エラーの行に限り、クォートのエスケープを戻し構文が通る形を探す.

    Args:
        code (str): フェンスから取り出したコード。

    Returns:
        str | None: 修正されたコード文字列、もともと通る場合と修正できない場合はNone
    """
    try:
        ast.parse(code)
        # もともと構文が通る場合はNoneを返す
        return None
    except SyntaxError:
        pass

    lines = code.splitlines()
    for _ in range(_MAX_UNESCAPE_PASSES):
        try:
            # ast.parseで構文解析できるかを確認する。
            ast.parse("\n".join(lines))
            return "\n".join(lines)
        except SyntaxError as error:
            # 構文エラーの行番号は1始まりなので、0始まりのインデックスに変換する
            index = (error.lineno or 0) - 1
            # 構文エラーの行番号が範囲外の場合はNoneを返す
            if not 0 <= index < len(lines):
                return None

            # 構文エラーの行のクォートを戻す
            repaired = lines[index].replace('\\"', '"').replace("\\'", "'")
            if repaired == lines[index]:
                return None
            # 構文エラーの行を修正したものに置き換える
            lines[index] = repaired

    return None


def _unwrap_json_code(code: str) -> str | None:
    """```python ブロックの中身が {"code": "..." } のJSON文字列でラップされている場合中身を取り出す.

    ツール呼び出しのJSONで学習したモデルが書くことがあるらしい。(NVIDIAのnemtronがMBPP305で4反復連続)
    dictリテラルとして正しいPythonなので実行できてしまい何も起きずに反復だけ消費する。
    中身がcodeキーに文字列を持つdictだけの時に限り展開する。

    Args:
        code (str): フェンスから取り出したコード。

    Returns:
        str | None: アンラップされたコード文字列、アンラップできない場合はNone
    """
    # ast.parseで構文解析できないコードはNoneを返す。
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    # ast.parseで構文解析できても、実行するとSyntaxErrorになるようなコードはNoneを返す。
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Expr):
        return None

    # ast.parseで
    node = tree.body[0].value
    if not isinstance(node, ast.Dict):
        return None

    # ast.literal_evalでdictに変換できない場合はNoneを返す。
    try:
        payload = ast.literal_eval(node)
    except ValueError:
        return None

    # 取り出したpayloadのキーがargumentsのときはargumentsの中身をpayloadにする。
    if isinstance(payload.get("arguments"), dict):
        payload = payload["arguments"]
    # payloadの中にcodeキーがあり、文字列であればそれを返す。
    inner_code = payload.get("code")
    if isinstance(inner_code, str) and inner_code.strip():
        return inner_code

    return None


def _extract_bare_code(llm_output: str) -> str | None:
    """フェンスなしの素のPythonコードを抽出する.

    Args:
        llm_output (str): LLMが生成した出力テキスト全体。

    Returns:
        str | None: 抽出されたコード
        または抽出できなかった場合(コードブロックが見つからない)はNone
    """
    # まず行頭がコードっぽい位置を探す。
    for match in _BARE_CODE_START_PATTERN.finditer(llm_output):

        # その位置から末尾までを候補として構文解析してみる。
        candidate_code = llm_output[match.start():].strip()
        if not candidate_code:
            continue
        try:
            tree = ast.parse(candidate_code)
        except SyntaxError:
            continue
        # ast.walkでASTを巡回し、関数定義やクラス定義などのコードらしいノードがあるかを判定する。
        if any(isinstance(node, _CODE_LIKE_NODES) for node in ast.walk(tree)):
            return candidate_code

    return None


def _parses(code: str) -> bool:
    """コードがPythonとして構文解析可能かを判定する.

    Args:
        code (str): 調べるPythonコード文字列

    Returns:
        bool: 構文解析可能ならTrue、構文エラーならFalse
    """
    try:
        ast.parse(code)
    except SyntaxError:
        return False
    return True


def _call_final_answer(code: str) -> bool:
    """コード中にfinal_answer()の呼び出しがあるかを判定する.

    Args:
        code (str): Pythonコード文字列

    Returns:
        bool: final_answer()の呼び出しがある場合はTrue、ない場合はFalse
    """
    # ast.parseで構文解析できないコードはFalseを返す。
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False

    # ast.walkでASTを巡回し、Callノードで関数名が"final_answer"のものがあるかを判定する。
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "final_answer"
        for node in ast.walk(tree)
    )


def _extract_with_kind(llm_output: str) -> tuple[str | None, str | None]:
    """コードを抽出し、崩れを救済した場合はその種類を返す.

    Args:
        llm_output (str): LLMが生成した出力テキスト全体。
    
Returns:
        tuple[str | None, str | None]: (抽出されたコード, 崩れ(救済)の種類)
        コードが抽出できなかった場合は(None, None)を返す。正規のブロックをそのまま抽出した場合は(コード, None)を返す。
    """
    # まず正規の```python```ブロックを抽出する。
    blocks = [str(block.rstrip() for block in _PYTHON_CODE_BLOCK_PATTERN.findall(llm_output))]

    kind: str | None = None
    code: str | None = None
    # 複数のブロックがある場合
    if len(blocks) > 1:
        # 関数定義のブロックとそれを検証するブロックに分けて書くモデルがある(nemtron)
        # 最後のブロックだけを実行すると定義がなくてエラーになる。
        # 連結して構文が通れば全部を順番に実行、通らなければ最後のブロックだけを返す。
        # -> ただし最後以外のブロックにfinal_answer()が含まれる場合は連結しない。
        joined = "\n\n".join(blocks)
        if not any(_call_final_answer(block) for block in blocks[:-1]) and _parses(joined):
            code, kind = joined, SALVAGE_MULTIPLE_BLOCKS
        else:
            code = blocks[-1]

    # 1つのブロックしかない場合
    elif blocks:
        code = blocks[0]

    # 1つもブロックがない場合は、閉じフェンスなし、フェンスなしの素のPythonコード、JSONラップなどを救済する。
    else:
        match = _UNCLOSED_CODE_BLOCK_PATTERN.search(llm_output)
        if match and match.group(1).strip():
            body = _TRAILING_FENCE_PATTERN.sub("", str(match.group(1)))
            code = body.rstrip()
            kind = SALVAGE_UNCLOSED_FENCE
        else:
            code = _extract_bare_code(llm_output)
            if code is not None:
                kind = SALVAGE_UNFENCED

    if code is None:
        return None, None

    unwrapped = _unwrap_json_code(code)
    if unwrapped is not None:
        return unwrapped, SALVAGE_JSON_WRAPPED

    repaired = _repair_escaped_quotes(code)
    if repaired is not None:
        return repaired, SALVAGE_ESCAPED_QUOTES

    repaired = _repair_unmatched_closers(code)
    if repaired is not None:
        return repaired, SALVAGE_UNMATCHED_CLOSERS

    return code, kind


def salvage_kind(llm_output: str) -> str | None:
    """LLM出力のコード抽出で崩れを救済した場合はその種類を返す.

    Args:
        llm_output (str): LLMが生成した出力テキスト全体。
    
    Returns:
        str | None: 崩れ(救済)の種類、正規のブロックをそのまま抽出した場合はNoneを返す。
    """
    _, kind = _extract_with_kind(llm_output)
    return kind


class PythonCodeExtractor(CodeExtractor):
    """LLMの出力テキストからPythonブロックのコードを抽出する具象クラス."""

    def extract(self, llm_output: str) -> str | None:
        """LLMの出力テキストからPythonコードを抽出する.

        複数のPythonコードブロックが存在する場合
        - 連結して構文が通れば全部を順番に実行する形で返す。
        - 最後以外のブロックがfinal_answer()を含む場合は連結しない。
        - それ以外は最後のブロックを返す。
        救済する崩れた出力
        - 閉じフェンスなし
        - フェンスなしの素のPythonコード
        - 過剰なエスケープ
        - JSON文字列でラップされている
        - 余分な閉じ括弧

        Args:
            llm_output (str): LLMが生成した出力テキスト全体。

        Returns:
            str | None: 抽出されたコード
            または抽出できなかった場合(コードブロックが見つからない)はNone
        """
        code, _ = _extract_with_kind(llm_output)
        return code
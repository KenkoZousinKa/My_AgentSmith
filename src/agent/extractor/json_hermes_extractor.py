"""JSON/Hermes形式のツール呼び出しをPythonコードに変換して抽出するモジュール.

Hermes系のモデルが出力する
    <tool_call>{"name": "read_file", "arguments": {"filepath": "/testbed/x.py"}}</tool_call>
    形式をサンドボックスがそのまま実行できる
    print(read_file(filepath='/testbed/x.py'))
    に変換する。
<tool_call>タグがない素のJSONオブジェクトにも対応する。
"""
import re
import json
from typing import Any

from src.agent.extractor.code_extractor import CodeExtractor
from src.agent.extractor.tools import is_tool_name, render_tool_call, python_literals

_TOOL_CALL_TAG_PATTERN = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.DOTALL | re.IGNORECASE
)

# タグなしのJSONを探す時の1つあたりの試行回数の上限("{"が大量にある出力の中で探す時に遅くならないように)
_MAX_BARE_JSON_ATTEMPTS = 50


def _call_saurce(payload: dict[str, Any]) -> str | None:
    """JSON/Hermesのpayloadからツール名と引数を取り出す.

    Args:
        payload (dict[str, Any]): {"name": "...", "arguments": {...}}形式の辞書。

    Returns:
        str | None: Pythonコードの呼び出し文。payloadが不正な場合はNone。
    """
    tool_name = payload.get("name")
    if not is_tool_name(tool_name):
        return None

    arguments = payload.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return None

        if not isinstance(arguments, dict):
            return None

    return render_tool_call(str(tool_name), python_literals(arguments))


def _bare_json_objects(llm_output: str) -> list[dict[str, Any]]:
    """<tool_call>タグなしのJSONオブジェクトを先頭から順に取り出す.

    正規表現では{}の入れ子構造を数えられないので、"{"で始まる位置からjson.JSONDecoder.raw_decode()で
    そこから始まる1つのJSONを読み取る。

    Args:
        llm_output (str): LLMの出力テキスト。

    Returns:
        list[dict[str, Any]]: 取り出したJSONオブジェクトのリスト。
    """
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    position = llm_output.find("{")
    attempts = 0
    while position != -1 and attempts < _MAX_BARE_JSON_ATTEMPTS:
        attempts += 1
        try:
            value, end = decoder.raw_decode(llm_output, position)
        except json.JSONDecodeError:
            position = llm_output.find("{", position + 1)
            continue
        if isinstance(value, dict):
            objects.append(value)
        position = llm_output.find("{", end)

    return objects


class JSONHermesCodeExtractor(CodeExtractor):
    """JSON / Hermes形式のツール呼び出しをPythonコードに変換して抽出する具象クラス."""

    def extract(self, llm_output: str) -> str | None:
        """LLMの出力テキストからJSON / Hermesコードを抽出する.

        <tool_call>タグがあればその中身だけを使い、ない場合本文中の素のJSONオブジェクトにも対応する。

        Args:
            llm_output (str): LLMの出力テキスト

        Returns:
            str: 抽出されたJSON / Hermesコード
        """
        payloads: list[dict[str, Any]] = []
        tagged_payloads = _TOOL_CALL_TAG_PATTERN.findall(llm_output)
        # タグ付きのJSONがあればそれを優先して使う。
        if tagged_payloads:
            for candidate in tagged_payloads:
                try:
                    payload = json.loads(candidate)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    payloads.append(payload)

        # タグなしのJSONは本文中に{}が大量にあると遅くなるので、タグ付きがあれば無視する。
        else:
            payloads = _bare_json_objects(llm_output)

        lines = [source for source in map(_call_saurce, payloads) if source is not None]

        return "\n".join(lines) if lines else None

"""xmlコード抽出機能を提供するモジュール.

Anthropic系のモデルが出力する
    <invoke name="read_file"><parameter name="filepath">/testbed/x.py</parameter></invoke>
形式をサンドボックスがそのまま実行できる
    print(read_file(filepath='/testbed/x.py'))
に変換する。
"""
import re

from src.agent.extractor.code_extractor import CodeExtractor
from src.agent.extractor.tools import is_tool_name, render_tool_call, literal_for

# <invoke_name="tool">...</invoke>を1件づつ取り出す。
_INVOKE_PATTERN = re.compile(
    r"<invoke\s+name\s*=\s*[\"']([^\"']+)[\"']\s*>(.*?)</invoke>",
    re.DOTALL | re.IGNORECASE
)

_PARAMETER_PATTERN = re.compile(
    r"<parameter\s+name\s*=\s*[\"']([^\"']+)[\"']\s*>(.*?)</parameter>",
    re.DOTALL | re.IGNORECASE
)


class XMLCodeExtractor(CodeExtractor):
    """XML形式のツール呼び出しをPythonコードに変換する具象クラス."""

    def extract(self, llm_output: str) -> str | None:
        """LLMの出力テキストからXML形式のツール呼び出しをPythonコードに変換する.

        Args:
            llm_output (str): LLMの出力テキスト

        Returns:
            str | None: 変換されたPythonコード。XML呼び出しがなければNone。
        """

        lines: list[str] = []
        for tool_name, inner_xml in _INVOKE_PATTERN.findall(llm_output):
            # 関数名として呼び出せない名前(空白入り、予約語など)は無視する。
            if not is_tool_name(tool_name):
                continue

            # 引数の値をPythonリテラルに変換する。
            arguments: dict[str, str] = {
                name: literal_for(value) for name, value in _PARAMETER_PATTERN.findall(inner_xml)
            }
            lines.append(render_tool_call(tool_name, arguments))

        return "\n".join(lines) if lines else None

"""複数フォーマットを順に試すコード抽出器を提供するモジュール."""

from src.agent.extractor.code_extractor import CodeExtractor
from src.agent.extractor.python_extractor import PythonCodeExtractor
from src.agent.extractor.json_hermes_extractor import JSONHermesCodeExtractor
from src.agent.extractor.xml_extractor import XMLCodeExtractor
from src.agent.extractor.react_extractor import ReactCodeExtractor


class CompositeCodeExtractor(CodeExtractor):
    """登録順に抽出を試し最初に成功した結果を返す抽出器."""

    def __init__(self, extractors: list[CodeExtractor] | None = None) -> None:
        """抽出器の優先順を決めて初期化する.

            Args:
                extractors (list[CodeExtractor] | None): 試す抽出器のリスト。
                NoneならPython -> JSON/Hermes -> XML -> ReActの 順に試す。
                Pythonブロックが主系なので最優先
            """
        self.extractors: list[CodeExtractor] = extractors if extractors is not None else [
                    PythonCodeExtractor(),
                    JSONHermesCodeExtractor(),
                    XMLCodeExtractor(),
                    ReactCodeExtractor(),
                ]

    def extract(self, llm_output: str) -> str | None:
        """登録順に抽出を試し最初に成功した結果を返す.

        Args:
            llm_output (str): LLMの出力テキスト。

        Returns:
            str | None: 抽出されたコード。どの抽出器でも抽出できなければNone。
        """
        for extractor in self.extractors:
            code = extractor.extract(llm_output)
            if code is not None and code.strip():
                return code

        return None

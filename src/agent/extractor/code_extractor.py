"""コード抽出機能を提供するモジュール.

LLMの出力テキストから、サンドボックスで実行するコードブロックを取り出す責務を持つ。
抽出の形式ごとに具象クラス(Python / XML / JSON-Hermes / React)を用意し、
orchestratorはCodeExtractor型として扱い形式差を吸収する。

- [ ] CodeExtracterをベースに、形式別にサブクラスを作成する。
    - [ ] Pythonコード
    - [ ] XML形式
    - [ ] JSON-Hermes形式
    - [ ] React形式
"""
from abc import ABC, abstractmethod


class CodeExtractor(ABC):
    """LLMの出力テキストからコードを抽出する抽象基底クラス.

    具象クラスはextract()メソッドを実装。
    抽出できなかった場合はNoneを返す。
    例外は投げず、LLMがコード未提出時は再促し対象にする。
    """

    @abstractmethod
    def extract(self, llm_output: str) -> str | None:
        """LLMの出力テキストからコードを抽出する.

        P0: Pythonコード
        P1: XML形式, JSON / Hermes形式, React形式
        非Pythonコードは、コードブロックの中に含まれる場合があるため、
        正規表現やパターンマッチングを使用して抽出する。

        Args:
            llm_output (str): LLMが生成した出力テキスト全体。

        Returns:
            str | None: 抽出されたコード
            または抽出できなかった場合(コードブロックが見つからない)はNone
        """
        # 正規表現やastを使ってコードブロックを抽出するなどでコード抽出のロジックを実装する
        # 実際には抽出したコードを返す

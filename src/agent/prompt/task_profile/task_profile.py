"""TaskProfileのベースクラスを定義するモジュール.

タスク種別ごとのプロンプト差分の注入口。
共通テンプレートに差し込む、タスク種別で変わる要素を抽象メソッドとして持つ。
新しいタスク種別を足すときは、このクラスを継承したプロファイルを1つ実装する。
- [x] models/以下に移動可能性あり。
- [ ] MBPPProfile, SWEBenchProfileが継承、他にタスクを増やしたい時用。
- [ ] few-shotを1例、各プロファイルごとに定義する。
- [ ] manualはname(args) -> ret: + 1行説明。非自明のものは小例をつける。
    - [ ] sandbox.manual()から動的差し込みし、実際のツール数に合わせる。
"""
from abc import ABC, abstractmethod

from src.models.sandbox_base import SandboxBase


class TaskProfile(ABC):
    """タスク種別ごとのプロンプト差分を提供する抽象基底クラス.

    具象クラスが下記4メソッドを実装する。
    """

    @abstractmethod
    def task_instructions(self) -> str:
        """このタスクの進め方を返す.

        具体的な問題分は、orchestratorがuserメッセージとして別途与えるため含めない。
        MBPP -> 「関数を書き、printでテストを出力し、final_answer(関数のソース)で提出」。

        Returns:
            str: タスクの指示
        """

    @abstractmethod
    def final_answer_specification(self) -> str:
        """final_answer()に何を渡すべきか、最終的な回答の仕方を返す.

        Returns:
            str: 最終的な回答の仕様
        """

    @abstractmethod
    def few_shot_example(self) -> str:
        """出力形式を教えるためのFew-shotの例を返す.

        Thought -> Code -> Observation -> final_answer
        実タスクとは無関係な例。形式を示すためだけの固定のテキスト。

        Returns:
            str: Few-shotの例
        """

    @abstractmethod
    def manual(self, sandbox: SandboxBase) -> str:
        """接続中MCPサーバーのツールスキーマから動的生成した、LLM向けツールマニュアルを返す.

        このタスクで使えるツール / 環境の説明を返す。
        ツールはハードコードせずに、sandbox.manual()から動的に取得する。

        Args:
            sandbox (SandboxBase): サンドボックスのインスタンス

        Returns:
            str: LLM向けツールマニュアル
        """

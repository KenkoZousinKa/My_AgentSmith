"""TaskProfileのベースクラスを定義するモジュール.

タスク種別ごとのプロンプト差分の注入口。
共通テンプレートに差し込む、タスク種別で変わる要素を抽象メソッドとして持つ。
新しいタスク種別を足すときは、このクラスを継承したプロファイルを1つ実装する。

プロンプト以外にもタスク種別で変わる出力形式のルール、提出物の扱いをフックとして持つ。
Orchestratorはタスク種別を知らずにフックを呼び出し、MBPPとSWEBenchの差分はプロファイルの差し替えで吸収する。

下記を提供
- TaskProfile:
    タスク種別ごとのプロンプト差分と提出物の扱いを提供する抽象基底クラス。
- def format_rules() -> str:
    システムプロンプトの出力形式のルールを返す。
- def sanitize_submission()
    final_answer()に渡された提出物を整形する。
- def submission_rejection()
    提出物を受理していいか検査、ダメならLLMへ返す理由を返す。
- def is_fallback_candidate()
    エラーなく実行できたコードを打ち切り時に提出する候補として残すかを返す。
- def fallback_solution()
    提出がないまま打ち切られた時、環境から回収できる最善の提出物を返す。

- [x] models/以下に移動可能性あり。
- [x] MBPPProfile, SWEBenchProfileが継承、他にタスクを増やしたい時用。
- [ ] few-shotを1例、各プロファイルごとに定義する。
- [ ] manualはname(args) -> ret: + 1行説明。非自明のものは小例をつける。
    - [ ] sandbox.manual()から動的差し込みし、実際のツール数に合わせる。
- [ ] 追加した5メソッドの具象の実装。
"""
from abc import ABC, abstractmethod

from src.models.sandbox_base import SandboxBase

DEFAULT_FORMAT_RULES = """- Each turn: write a brief Thought line, then exactly ONE code block fenced as ```python ... ```.
- Put the closing ``` on its own line, then write <end_code> to end your turn.
- Only what you print() (and any error or traceback) is returned in the Observation."""


class TaskProfile(ABC):
    """タスク種別ごとのプロンプト差分と提出物の扱いを提供する抽象基底クラス.

    具象クラスが下記4メソッドを実装する。
    出力形式のルール、提出物の整形と検査、打ち切り時の回収は既定の実装があり、
    必要なプロファイルが上書きする。
    """

    def format_rules(self) -> str:
        """システムプロンプトの出力形式のルールを返す.

        Returns:
            str: 出力形式のルール。## Output Format に入れる箇条書き。
        """
        return DEFAULT_FORMAT_RULES

    def sanitize_submission(self, raw: str) -> str:
        """final_answer()に渡された提出物を整形する.

        既定は空白除去だけにし、
        MBPPはコードフェンスを落とす。

        Args:
            raw (str): LLMからの提出物。

        Returns:
            str: 整形済みの提出物。
        """
        return raw.strip()

    def submission_rejection(self, candidate: str) -> str | None:
        """提出物を受理していいか検査、ダメならLLMへ返す理由を返す.

        既定は空の提出を拒否するだけにし、
        MBPPはASTの構文チェックも行う。

        Args:
            candidate (str): sanitize_submission()に渡し済みの提出物。

        Returns:
            str | None: 拒否理由の文字列。受理する場合はNone。
        """
        if not candidate:
            return "final_answer() received an empty input."
        return None

    def is_fallback_candidate(self, code: str) -> bool:
        """エラーなく実行できたコードを打ち切り時に提出する候補として残すかを返す.

        既定は残さない(何が提出できる形かはタスクごとに異なるため、プロファイルで判断させる)、
        MBPPは構文が通り、関数定義を含むコードだけを候補として残す。

        Args:
            code (str): その反復の時点で実行したコード。

        Returns:
            bool: 提出候補として残す場合はTrue、残さない場合はFalse。
        """
        return False

    def fallback_solution(self, sandbox: SandboxBase) -> str:
        """提出がないまま打ち切られた時、環境から回収できる最善の提出物を返す.

        既定はから文字列を返し回収しない。
        SWEBenchは編集済みのバッチ(git diff)を回収する。

        Args:
            sandbox (SandboxBase): 接続中のサンドボックスのインスタンス。

        Returns:
            str: 打ち切り時に提出するコード。
        """
        return ""

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

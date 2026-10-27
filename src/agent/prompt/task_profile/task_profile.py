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
"""
from abc import ABC, abstractmethod

from src.models.sandbox_base import SandboxBase

DEFAULT_FORMAT_RULES = """- One brief Thought line (20 words max), then exactly ONE block fenced as ```python ... ```,
  then <end_code>.
- NEVER derive formulas or trace arithmetic in prose. Your turn is cut off at a hard output
  limit, and a reply that never closes a ```python block runs nothing and burns the budget.
  Write the candidate in code and let the Observation correct you.
- Only what you print() (plus errors and tracebacks) comes back in the Observation.
- The tools and final_answer are already defined globals: call them directly, never import them.
- The namespace persists between turns, but your FINAL answer must be SELF-CONTAINED.
- Limits on iterations, tokens and time are strict: keep turns short, never print large output."""


class TaskProfile(ABC):
    """タスク種別ごとのプロンプト差分と提出物の扱いを提供する抽象基底クラス.

    具象クラスが下記4メソッドを実装する。
    出力形式のルール、提出物の整形と検査、打ち切り時の回収は既定の実装があり、
    必要なプロファイルが上書きする。

    Attributes:
        history_window_size (int): LLMへ再送する直近の往復(assistant + observation)の数。デフォルトは2。
        observation_max_chars (int): 再送するObservationの1件の最大文字数。デフォルトは800。
        latest_observation_max_chars (int): 直前のObservation(これからLLMが読む)の最大文字数。
            テスト失敗の内容、読んだファイルの中身を途中で切らないために過去の分より長く残す。デフォルトは1500。
        assistant_max_chars (int): 再送するAssistantの発話1件の最大文字数。デフォルトは1200。
        rotate_after_missed (int | None): 提出できなかった反復がこの回数続いたら別のプロバイダに切り替える。
            同じプロバイダだと同じ傾向になることが多いのでプロバイダごと切り替える。デフォルトは2。
            SWE-Benchでは探索が多くなるのでNoneで切り替えない。
        rotate_after_repeats (int | None): 以前と同じコードの実行がこの回数続いたら別のプロバイダに切り替える。
            Noneで切り替えない。
        iteration_warn_at (int): 反復の残り回数がこの値以下になったらLLMに警告する。デフォルトは1。
    """

    # 既定はMBPP向けの値。累積input_tokensの上限が6000のため短く絞る。
    history_window_size: int = 2
    observation_max_chars: int = 800
    latest_observation_max_chars: int = 1500
    assistant_max_chars: int = 1200
    rotate_after_missed: int | None = 2
    rotate_after_repeats: int | None = None
    iteration_warn_at: int = 1

    def format_rules(self) -> str:
        """システムプロンプトの出力形式のルールを返す.

        Returns:
            str: 出力形式のルール。## Output Format に入れる箇条書き。
        """
        return DEFAULT_FORMAT_RULES

    def submit_hint(self) -> str:
        """反復の残り回数が少ない時にどう提出するか、LLMに提出を促す文を返す.

        Returns:
            str: 提出を促す文。
        """
        return "Submit your best answer with final_answer(...) now."

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

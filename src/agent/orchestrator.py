"""Thought -> Code -> Observationのループを制御するOrchestratorモジュール.

1タスク分のループ本体。
system(共通のテンプレート + TaskProfile) + user(問題文)から開始し、
毎反復で
LimitTrackerの先頭ガード -> LLM生成 -> <end_code>除去 -> コード抽出 -> sandbox実行
 -> Observation生成 -> 履歴 / StepMetric追加
のループを回す。
final_answer()で成功終了、ハード制限で打ち切り。
"""
from collections.abc import Callable
from typing import NamedTuple, TypeAlias

from src.agent.extractor.code_extractor import CodeExtractor
from src.agent.extractor.python_extractor import salvage_kind, strip_stop_sequences
from src.agent.limits import LimitTracker, StopReason
from src.agent.llm.provider.provider import LLMGenerator, LLMResponse, LLMError
from src.agent.llm.transport.transport import TransportError
from src.agent.observation import (
    build_observation,
    observation_no_code,
    budget_note,
    iteration_note,
    malformed_code_note,
    repeated_code_note,
    submission_rejected_note
)
from src.agent.prompt.task_profile.task_profile import TaskProfile
from src.agent.prompt.template import build_system_prompt
from src.config.settings import Limits
from src.models.output import ExecuteResult, StepMetrics, SolutionOutput
from src.models.sandbox_base import SandboxBase

# LLMに送るメッセージ１件。{"role": "system / user / assistant", "content": "..."}
ChatMessage: TypeAlias = dict[str, str]
# LLMに送る会話の履歴(メッセージを古い順に並べたもの)
ChatHistory: TypeAlias = list[ChatMessage]
# 提出物を受理する前に検証する関数の型。提出物を受け取り、合否 / 不合格の理由を返す。
SolutionVerifier: TypeAlias = Callable[[str], VerificationResult]

_DEFAULT_STOP_SEQUENCES = ["<end_code>"]


class VerificationResult(NamedTuple):
    """提出物を検証した結果.

    Attributes:
        passed (bool): 検証に通ったかどうか。
        reason (str): 通らなかった理由。通ったら空文字列。
    """
    passed: bool
    reason: str


class Orchestrator:
    """1タスク分の Thought -> Code -> Observationのループを制御するOrchestratorクラス."""
    # 入力トークンの見積もりの係数の初期値。超えないために小さめに取る。
    _CHARS_PER_TOKEN = 3.0
    # 実測した1トークンあたりの文字数の安全側補正値。実測値より小さくなるようにする。
    _CHARS_PER_TOKEN_SAFETY = 0.95
    # メッセージ1件ごとに足すrole / contentのトークン数。
    _TOKENS_PER_MESSAGE = 4
    # 出力の残りが1反復の上限 * この倍率以下になったら提出を促す文をObservationの末尾に追加する。
    # 2にすると本番だと1反復目の直後に出てしまうので1.0にする。
    _BUDGET_WARN_FACTOR = 1


    def __init__(
        self,
        provider: LLMGenerator,
        extractor: CodeExtractor,
        sandbox: SandboxBase,
        profile: TaskProfile,
        limits: Limits,
        stop_sequences: list[str] | None = None,
        solution_verifier: SolutionVerifier | None = None,
        start_time: float | None = None
    ) -> None:
        """依存部品を注入してOrchestratorを初期化する.

        Args:
            provider (LLMGenerator): 1回の生成を行うLLMクライアント。
            extractor (CodeExtractor): LLMの出力から実行コードを取り出す抽出器。
            sandbox (SandboxBase): コードを実行するサンドボックス。
            profile (TaskProfile): タスク種別ごとのプロファイル(プロンプト差分、提出物の形式等)。
            limits (Limits): ループのハード制限(反復 / トークン / 時間)値
            stop_sequences (list[str] | None):
                LLMの出力を打ち切るためのシーケンスのリスト。Noneの場合["<end_code>"]
            solution_verifier (SolutionVerifier | None):
                提出物を検証する関数。Noneの場合は検証を行わない。
            start_time (float | None):
                プロセス起動直後のtime.monotonic()の値。Noneの場合はLimitTracker作成時刻。
        """
        self.provider = provider
        self.extractor = extractor
        self.sandbox = sandbox
        self.profile = profile
        self.limits = limits
        self.stop_sequences = stop_sequences if stop_sequences is not None else list(_DEFAULT_STOP_SEQUENCES)
        self.solution_verifier = solution_verifier
        self.start_time = start_time
        # 入力トークンの見積もりの係数(1トークンあたりの文字数)。実測に合わせ安全側には補正OK。
        self._chars_per_token = self._CHARS_PER_TOKEN

    def run(self, task_id: str, benchmark: str, task_message: str) -> SolutionOutput:
        """1タスク分のループを回しSolutionOutputを生成する.

        fail safe: どういうケースでどういう処理が走るか。
        - 反復、入力、出力、時間のどれかが上限。
            ループの先頭で止める。errorにStopReason。提出物はbest_solutionか回収したもの。
        - 履歴が長く入力トークンの残りに入らない。
            往復を1つづつ減らし、長い発話は中央を省く。0往復でも入らなければ送らずにMAX_INPUT_TOKENS。
            (_fit_window, _window_messages)
        - 入力トークンの見積もりがズレる。
            実際の文字数 / 入力トークンを見て係数を直す。
            (_learn_chars_per_token)
        - 1回の出力が長すぎる。
            max_tokens = min(1反復の上限、出力の残り)にし、累積の出力の上限を超えない。
        - 全部のプロバイダ、キーで失敗。
            ResilientLLMClientがAllProvidersExhaustedを投げ、LLM_UNAVAILABLE。
        - 提出したコードがない。
            [NO_CODE]で知らせる。extractorがコードを見つけられない。MBPPは2回続いたら別のプロバイダへ。
        - 提出したコードが崩れてる。
            [MALFORMED_CODE]で知らせる。extractorがコードを直して実行。
        - 提出したコードが同じを繰り返す。
            [REPEATED]で知らせる。SWE-Benchは2回続いたら別のプロバイダへ。
        - 提出したコードを実行、例外、時間切れ、出力過多。
            ラベルと助言付きのObservationで知らせる。
        - 提出が空、形式違い、検査に落ちる。
            整形 -> 検査 -> 検証し、落ちたら理由付きで知らせる。そのまま出せる形ならbest_solutionに残す。
            (sanitize_submission, submission_rejection, solution_verifier)
        - トークンの残りが少ない
            [BUDGET]で知らせる。今の最善を提出させる。
        - 提出物がないまま打ち切られた。
            空の提出をなるべく避けるために回収する。SWE-Benchは編集済みのパッチ。回収で例外が出たら空にする。
            (profile.fallback_solution)


        Args:
            task_id (str): タスク識別子(MBPPのtask_idまたはSWE-benchのinstance_id)
            benchmark (str): ベンチマークの種類: 'mbpp' または 'swebench'
            task_message (str): LLMに渡す問題文

        Returns:
            SolutionOutput:
                成功ならエージェントの最終的な解答とメトリクスを含むSolutionOutputオブジェクト。
                打ち切りなら errorに打ち切り理由を含むSolutionOutputオブジェクト。
        """
        # システムプロンプトとユーザープロンプトを組み合わせて、最初のメッセージを作成
        system_prompt = build_system_prompt(self.profile, self.sandbox)
        messages: ChatHistory = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task_message}
        ]

        # =================== ループ前の下準備 ===================
        # LimitTrackerを初期化し、ステップのメトリクスを保持するリストを作る。
        tracker = LimitTracker(self.limits, start_time=self.start_time)
        steps: list[StepMetrics] = []
        # 打ち切り時に提出するコードの補を保持する変数。Observationが生成されるたびに更新される。
        # TaskProfileがそのまま提出できると判断したものを入れる。
        best_solution: str = ""
        # {実行したコードの文字列: 実行したstepの番号}。同じコードの再実行指摘用。
        executed_codes: dict[str, int] = {}
        # 提出できなかった反復の連続回数。続いたら別プロバイダに切り替える用。
        misses_in_a_row = 0
        # 以前と同じコードを実行した反復の連続数。指摘し繰り返すなら別のプロバイダに切り替える用。
        repeats_in_a_row = 0

        # ================== ループ本体 ==================
        while True:
            # ループの先頭で制限をチェックし、打ち切りならSolutionOutputを返す
            stop_reason = tracker.start_iteration()
            if stop_reason is not None:
                return self._build_solution(
                    task_id=task_id,
                    benchmark=benchmark,
                    success=False,
                    solution=best_solution,
                    tracker=tracker,
                    steps=steps,
                    system_prompt=system_prompt,
                    error=stop_reason.value
                )

            # 送信する履歴を制限に収まるように切り詰める。
            windowed = self._fit_window(messages, tracker)
            # もし収まらなければSolutionOutputを返す
            if windowed is None:
                # LLMにリクエストを送る前に止めるのでこの反復はstep、反復に数えない。
                tracker.cancel_iteration()
                return self._build_solution(
                    task_id=task_id,
                    benchmark=benchmark,
                    success=False,
                    solution=best_solution,
                    tracker=tracker,
                    steps=steps,
                    system_prompt=system_prompt,
                    error=StopReason.MAX_INPUT_TOKENS.value
                )

            # min(1反復の出力トークン上限, 残りの出力トークン上限)LLMの応答で使うトークンを予算内に制限
            max_tokens = min(
                self.limits.max_output_tokens_per_iteration,
                tracker.remaining_output_tokens()
            )
            # LLMにリクエストを送信し、レスポンスを取得する
            try:
                response: LLMResponse = self.provider.generate(
                    messages=windowed,
                    stop_sequences=self.stop_sequences,
                    max_tokens=max_tokens
                )
            # ResilientLLMClient.generate()は全部のプロバイダ / 全部のキーを試しても成功しなかった場合
            # AllProvidersExhausted(LLMError)を送出する。
            # その他のLLMGeneratorを単体で使用した場合に、generate()の例外はLLMError / TransportErrorが送出される。
            except (LLMError, TransportError) as error:
                # 総試行回数を取得する
                failed_requests = getattr(error, "attempts", 1)
                # LLMにリクエストを送っているが、出力が生成されなかったのでstep、反復に数えない。
                tracker.cancel_iteration()
                # 消費トークン数をLimitTrackerに記録する
                tracker.record_usage(
                    getattr(error, "input_tokens", 0),
                    getattr(error, "output_tokens", 0)
                )
                return self._build_solution(
                    task_id=task_id,
                    benchmark=benchmark,
                    success=False,
                    solution=best_solution,
                    tracker=tracker,
                    steps=steps,
                    system_prompt=system_prompt,
                    error="LLM_UNAVAILABLE",
                    failed_requests=failed_requests
                )

            # =========== トークンの制限クリア -> LLMへのリクエストが成功 ==========
            # 消費トークン数をLimitTrackerに記録する
            tracker.record_usage(
                response.input_tokens,
                response.output_tokens,
            )
            # 送った文字数と報告された入力トークン数から見積もりの係数を安全側に補正する。
            self._learn_chars_per_token(sent=windowed, response=response)
            # LLMのレスポンスを履歴に追加する
            messages.append(
                {"role": "assistant", "content": response.text}
            )

            # ========== コードを抽出する ==========
            cleaned_code = strip_stop_sequences(response.text, self.stop_sequences)
            code = self.extractor.extract(cleaned_code)
            # 抽出できなかったらObservationを生成して次のループに進む。
            if code is None:
                # 1反復の出力上限まで使い切っていたら散文で考え込んで切れているのでそれを伝える。
                cut_off_at = response.output_tokens if response.output_tokens >= max_tokens else None
                # ========== 次ループ前共通の処理 ==========
                observation = self._with_budget_note(
                    observation_no_code(cut_off_at), tracker
                )
                # Observationを履歴に追加し、StepMetricsを作成してstepsに追加する。
                messages.append(
                    {"role": "user", "content": observation}
                )
                # 何も実行していないのでsandbox_input / sandbox_outputは空文字列でStepMetricsを作る。
                steps.append(
                    self._build_step(len(steps) + 1, response, "", "")
                )
                misses_in_a_row = self._count_miss(misses_in_a_row, submitted=False)
                continue

            # ============= LLMの出力からコードが抽出できた =============
            # サンドボックスで実行しObservationを生成する
            result: ExecuteResult = self.sandbox.run(code)
            observation = build_observation(result)

            # 以前と同じコードなら、Observationの先頭に[REPEATED]を付ける。
            # fingerprintで改行、空白の違いだけのコードは同じとみなす
            fingerprint = " ".join(code.split())
            if fingerprint in executed_codes:
                observation = f"{repeated_code_note(executed_codes[fingerprint])}\n{observation}"
                repeats_in_a_row = self._count_repeat(repeats_in_a_row)
            else:
                executed_codes[fingerprint] = len(steps) + 1
                repeats_in_a_row = 0

            # 崩れたコードを救済実行した場合は[MALFORMED_CODE]の種類をLLMに伝えるためにobservationの前に追加
            salvaged = salvage_kind(cleaned_code)
            if salvaged is not None:
                observation = f"{malformed_code_note(salvaged)}\n{observation}"

            # 最終的な提出物。提出物があり、かつ受理された場合のみ中身が入る。
            submission: str | None = None
            # final_answer()が呼ばれた場合、提出物を検査する。
            if result.final_answer_bool:
                raw_submission = result.final_answer or ""
                # 整形、検査、検証
                candidate, rejection = self._review_submission(raw_submission)
                # 全て通れば提出
                if rejection is None:
                    submission = candidate
                else:
                    # 空の提出物はbuild_observation()でObservationに含まれるので追加しない。
                    if raw_submission.strip():
                        observation = f"{observation}\n{submission_rejected_note(rejection)}"
                    # 差し戻した提出物でもTaskProfileがそのまま提出できると判断した場合は、best_solutionに保持する。
                    if self.profile.is_fallback_candidate(candidate):
                        best_solution = candidate

            # final_answer()が呼ばれなかった場合、TaskProfileがそのまま提出できると判断した場合は、best_solutionに保持する。
            # 呼ばれているときはfinal_answer()のみの場合が多く、かつ間違っているならbest_solutionに保持する必要はない。
            elif result.error is None and not result.timeout and self.profile.is_fallback_candidate(code):
                best_solution = code

            # ========== 次ループ前共通の処理 ==========
            # 残りの出力 / 反復が少なければ提出を促す[BUDGET]文をObservationの末尾に追加する。
            observation = self._with_budget_note(observation, tracker)
            # Observationを履歴に追加し、StepMetricsを作成してstepsに追加する。
            messages.append(
                {"role": "user", "content": observation}
            )
            steps.append(
                self._build_step(len(steps) + 1, response, code, observation)
            )
            # 提出に至らない反復が続いたら別のプロバイダに切り替えるためのカウンタを更新する。
            # 今ってfinal_answerが呼ばれなかっただけで2回でプロバイダローテしてる？早くない？
            misses_in_a_row = self._count_miss(misses_in_a_row, submitted=submission is not None)

            # 提出物が受理された場合は、SolutionOutputを生成して返す
            if submission is not None:
                return self._build_solution(
                    task_id=task_id,
                    benchmark=benchmark,
                    success=True,
                    solution=submission,
                    tracker=tracker,
                    steps=steps,
                    system_prompt=system_prompt,
                    error=None
                )

    def _build_step(
        self,
        step: int,
        response: LLMResponse,
        sandbox_input: str,
        sandbox_output: str
    ) -> StepMetrics:
        """1反復分のStepMetricsを構築するヘルパー関数.

        Args:
            step (int): 1から始まるイテレーション番号
            response (LLMResponse): LLMの生成結果
            sandbox_input (str): サンドボックスに送信したコード
            sandbox_output (str): LLMへ返すObservationの文字列

        Returns:
            StepMetrics: 1反復分のStepMetricsオブジェクト
        """
        return StepMetrics(
            step=step,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            request_time_ms=response.request_time_ms,
            api_url=response.api_url,
            model_name=response.model_name,
            llm_output=response.text,
            sandbox_input=sandbox_input,
            sandbox_output=sandbox_output,
            retries=response.retries
        )

    def _build_solution(
        self,
        task_id: str,
        benchmark: str,
        success: bool,
        solution: str,
        tracker: LimitTracker,
        steps: list[StepMetrics],
        system_prompt: str,
        error: str | None = None,
        failed_requests: int = 0
    ) -> SolutionOutput:
        """ループの結果からSolutionOutputを構築するヘルパー関数(成功 / 打ち切り共通).

        提出物がないまま打ち切られた場合TaskProfileに提出物を回収させる。
        SWEbenchなら編集済みのパッチ。空の提出は可能な限りさせない。

        Args:
            task_id (str): タスク識別子(MBPPのtask_idまたはSWE-benchのinstance_id)
            benchmark (str): ベンチマークの種類: 'mbpp' または 'swebench'
            success (bool): エージェントがタスクを解決したと判断したかどうか
            solution (str):
                MBPPの場合: Pythonの関数コード。SWE-benchの場合: gitパッチ（diff）
            tracker (LimitTracker): ループの制限を追跡するLimitTrackerオブジェクト
            steps (list[StepMetrics]): ループの各反復のStepMetricsのリスト
            system_prompt (str): LLMに送信された完全なシステムプロンプト（出所確認用）
            error (str | None): エージェントが失敗した場合のエラーメッセージ
                （成功した場合はNone）
            failed_requests (int): LLM呼び出しが失敗した場合の総試行回数（リトライを含む / 既定0）

        Returns:
            SolutionOutput: 提出物、消費量、各反復の記録を入れたSolutionOutput

        """
        # 提出物の回収
        if not success and not solution:
            try:
                solution = self.profile.fallback_solution(self.sandbox)
            # 回収はサンドボックス、ツールに左右される。SIGTERMの直前サーバーのみ先に終了しているなど。
            # (MCPでget_patch()呼び出し時、ツールサーバー落ち、コンテナが消えている、パイプが閉じている等)
            # 失敗したら握りつぶす。中断は止めない。
            except Exception:
                solution = ""

        return SolutionOutput(
            task_id=task_id,
            benchmark=benchmark,
            success=success,
            solution=solution,
            iterations=tracker.iterations,
            total_requests=sum(step.retries + 1 for step in steps) + failed_requests,
            total_input_tokens=tracker.total_input_tokens,
            total_output_tokens=tracker.total_output_tokens,
            total_time_seconds=tracker.elapsed_seconds(),
            steps=steps,
            system_prompt=system_prompt,
            error=error
        )

    def _count_miss(self, misses_in_a_row: int, submitted: bool) -> int:
        """提出に至らなかった反復の連続回数を更新する.

        閾値を超えたら別のプロバイダに切り替えるためのカウンタ。
        閾値はTaskProfileが決める。MBPPは2、SWE-BenchはNoneで切り替えない。

        Args:
            misses_in_a_row (int): これまでの提出に至らなかった反復の連続回数。
            submitted (bool): 今回の反復で提出物が受理されたか。

        Returns:
            int: 更新後の提出に至らなかった反復の連続回数。切り替えたら0にリセットする。
        """
        if submitted:
            return 0
        misses_in_a_row += 1
        threshold = self.profile.rotate_after_missed
        if threshold is not None and misses_in_a_row >= threshold:
            self._rotate_provider()
            return 0
        return misses_in_a_row

    def _count_repeat(self, repeats_in_a_row: int) -> int:
        """同じコードの再実行の連続回数を更新する.

        閾値を超えたら別のプロバイダに切り替えるためのカウンタ。
        閾値はTaskProfileが決める。MBPPはNoneで切り替えない、SWE-Benchは2。
        [REPEATED]の指摘の後も同じコードを出し続けるモデルは履歴からは抜けられないことがある。

        Args:
            repeats_in_a_row (int): これまでの同じコードの再実行の連続回数。

        Returns:
            int: 更新後の同じコードの再実行の連続回数。切り替えたら0にリセットする。
        """
        repeats_in_a_row += 1
        threshold = self.profile.rotate_after_repeats
        if threshold is not None and repeats_in_a_row >= threshold:
            self._rotate_provider()
            return 0
        return repeats_in_a_row

    def _rotate_provider(self) -> None:
        """LLMクライアントが切り替えに対応していれば別のプロバイダに切り替える.

        ResilientLLMClientは内部で次のプロバイダに切り替えるrotate()を持つ。
        """
        rotate = getattr(self.provider, "rotate", None)
        if callable(rotate):
            rotate()

    def _with_budget_note(self, observation: str, tracker: LimitTracker) -> str:
        """出力 / 反復の残りが少なければ提出を促す文をObservationの末尾に追加する.

        出力予算が切れて打ち切られると不合格なので、残りが1反復になった時点で今の最善を提出させる。

        Args:
            observation (str): 組み立て済みの生成されたObservation
            tracker (LimitTracker): 今の消費状況。

        Returns:
            str: 必要ならObservationの末尾に提出を促す文を追加した文字列。
        """
        remaining = tracker.remaining_output_tokens()
        # 出力トークンの残りチェック
        # max_output_tokens_per_iteration -> MBPP 600 / SWE-Bench 1200(config.json)
        # 0以下なら次の反復の先頭で打ち切られるから促しても送られないのでつけない。1反復分の残りがあれば促す。
        if 0 < remaining <= self.limits.max_output_tokens_per_iteration * self._BUDGET_WARN_FACTOR:
            return f"{observation}\n{budget_note(remaining)}"

        # 反復回数のチェック
        # profole.iteration_warn_at -> MBPP 1 / SWE-Bench 4
        iterations_left = self.limits.max_iterations - tracker.iterations
        if 0 < iterations_left <= self.profile.iteration_warn_at:
            return f"{observation}\n{iteration_note(iterations_left, self.profile.submit_hint())}"

        return observation

    def _fit_window(self, messages: ChatHistory, tracker: LimitTracker) -> ChatHistory | None:
        """累積入力トークンの上限に収まる送信用の履歴を返す。どう縮めても収まらなければNone.

        直近の profile.history_window_size(MBPP2 / SWE-Bench6) ... systemとタスク文だけの順に縮める。
        履歴はいきなり全部捨てると直前の失敗と原因(Observation)がLLMに伝わらず同じ失敗を繰り返すので、
        1往復ずつ減らす。

        Args:
            messages (ChatHistory): これまでの全履歴
            tracker (LimitTracker): 今の消費状況。

        Returns:
            ChatHistory | None: 送信用のメッセージ列。収まらなければNone。
        """
        # 送信可能なトークン数の予算を計算する
        budget = self.limits.max_input_tokens - tracker.total_input_tokens
        # history_window_size, ...,  1, 0の順に履歴を切り詰めて、収まるものを返す。収まらなければNone。
        # MBPPの時に3往復目には　履歴が１個も送られない？まずくない？
        for window_size in range(self.profile.history_window_size, -1, -1):
            candidate = self._window_messages(messages, window_size)
            # これから送るメッセージのトークンを見積もり予算内なら送る。
            if self._estimate_tokens(candidate) <= budget:
                return candidate

        return None

    def _window_messages(self, messages: ChatHistory, window_size: int) -> ChatHistory:
        """LLMに送る履歴を直近のwindow_size往復に切りつめて返す.

        Chat Completionは状態を持たず、毎回すべての履歴を送る。
        全履歴を送り続けると累積トークンは反復の回数の2乗で増えるので、
        system + task_message + 直近のwindow_size往復(assistant + Observation)だけを送る。
        長いObservationとassistantの発話はプロファイルごとの上限文字数まで中央を省いて縮める。

        Args:
            messages (ChatHistory): これまで[system, user, (assistant, user)...]の全履歴
            window_size (int): 残す往復の数。0ならsystemとタスク文だけ。

        Returns:
            ChatHistory: 切り詰めた送信用のメッセージ列。
        """
        # systemとタスク文は必ず残す。
        head = messages[:2]
        # 1往復はassistantの発話 + Observationの2件なので、直近window_size往復は末尾の * 2件
        # window_size == 0だと[-0:]だと全て残ってしまうので0の時は空リストにする。
        tail = messages[2:][-window_size * 2:] if window_size > 0 else []

        max_chars_by_role = {
            "user": self.profile.observation_max_chars,
            "assistant": self.profile.assistant_max_chars
        }
        trimmed: ChatHistory = []
        for index, message in enumerate(tail):
            max_chars = max_chars_by_role[message["role"]]
            # 最後のObservationはこれからLLMが読んで次の手を決めるので長めに残す。
            if index == len(tail) - 1 and message["role"] == "user":
                max_chars = self.profile.latest_observation_max_chars

            trimmed.append({"role": message["role"], "content": _truncate_middle(message["content"], max_chars)})

        return head + trimmed

    def _estimate_tokens(self, messages: ChatHistory) -> int:
        """これから送るメッセージ列のトークン数を見積もる.

        累積input_tokensの上限を超えないようにするための事前ガード。
        越えると不合格になるので少し大きく見積もる。

        Args:
            messages (ChatHistory): これから送るメッセージ列

        Returns:
            int: 見積もった入力トークン数
        """
        characters = sum(len(message["content"]) for message in messages)
        return int(characters / self._chars_per_token) + 1 + self._TOKENS_PER_MESSAGE * len(messages)

    def _learn_chars_per_token(self, sent: ChatHistory, response: LLMResponse) -> None:
        """実際に送った文字数と報告された入力トークン数から、1トークンあたりの文字数の係数を安全側に補正する.

        トークナイザーを使うと正確に計算できるが、トークナイザーの実装はプロバイダごとに異なるため、
        実測値を使って安全側に補正する。
        実測の比が今の係数より小さければ係数を下げる。
        リトライがあったレスポンス(retries > 0)は失敗した試行のトークンが足されているので補正に使わない。
        3000文字送って1200トークン使ったと返ってきたら 2.5文字/トークン で今の3.0より小さいので係数を2.5に下げる。

        Args:
            sent (History): このリクエストで送ったメッセージ列
            response (LLMResponse): このリクエストの応答。報告されたinput tokensとリトライの回数を使う。
        """
        if response.retries or response.input_tokens <= 0:
            return

        characters = sum(len(message["content"]) for message in sent)
        observed = characters / response.input_tokens * self._CHARS_PER_TOKEN_SAFETY

        # 1トークンあたりの文字数の係数を補正する。実測値より小さくなるようにする。
        if 0 < observed < self._chars_per_token:
            self._chars_per_token = observed

    def _review_submission(self, raw_submission: str) -> tuple[str, str | None]:
        """final_answer()で提出されたコードを整形し受理できるか検査する.

        TaskProfileの整形 -> TaskProfileの検査 -> SolutionVerifierの検査の順に行う。
        前の段階で拒否されたら、後の段階はスキップする。

        Args:
            raw_submission (str): final_answer()で提出されたコード

        Returns:
            tuple[str, str | None]: (整形後の提出物, 拒否理由)
                受理された場合の拒否理由はNone。
        """
        # 提出物の整形。
        candidate = self.profile.sanitize_submission(raw_submission)
        # 整形後の提出物の検査。
        rejection = self.profile.submission_rejection(candidate)
        if rejection is None and self.solution_verifier is not None:
            # 検査に通らなかった場合は、拒否理由を返す。
            verified, detail = self.solution_verifier(candidate)
            if not verified:
                rejection = f"The submission did not pass the task's checks: {detail}"

        return candidate, rejection


# _truncate_middle()が省いた中央の代わりに置く目印。
_TRUNCATED_MIDDLE_MARKER = "\n... [truncated] ...\n"


def _truncate_middle(content: str, max_chars: int) -> str:
    """文字列の中央を省略してmax_charsに収める.

    Observationは先頭に実行結果(status / stdout / stderr)があり、
    末尾に'--- note ---'の助言を置いている。
    先頭だけ残す切り詰めだと行動を促す助言(切り詰めの警告、提出の却下理由)が消えるので中央を省略する。

    Args:
        content (str): 省略する文字列
        max_chars (int): 省略後の最大文字数

    Returns:
        str: max_charsに収めた文字列。超えていれば中央を目印に置き換える。
    """
    if len(content) <= max_chars:
        return content

    # 上限の2/3を先頭、残りの1/3を末尾に残す。中央は目印に置き換える。
    head_size = max_chars * 2 // 3
    tail_size = max_chars - head_size
    return f"{content[:head_size]}{_TRUNCATED_MIDDLE_MARKER}{content[-tail_size:]}"

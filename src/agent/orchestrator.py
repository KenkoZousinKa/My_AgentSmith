"""Thought -> Code -> Observationのループを制御するOrchestratorモジュール.

1タスク分のループ本体。
system(共通のテンプレート + TaskProfile) + user(問題分)から開始し、
毎反復で
LimitTrackerの先頭ガード -> LLM生成 -> <end_code>除去 -> コード抽出 -> sandbox実行
 -> Observation生成 -> 履歴 / StepMetric追加
 のループを回す。
 final_answer()で成功終了、ハード制限で打ち切り。
"""
from collections.abc import Callable

from src.agent.extractor.code_extractor import CodeExtractor
from src.agent.extractor.python_extractor import salvage_kind, strip_stop_sequences
from src.agent.limits import LimitTracker, StopReason
from src.agent.llm.provider.provider import LLMGenerator, LLMResponse, LLMError
from src.agent.observation import (
    build_observation,
    observation_no_code,
    malformed_code_note,
    submission_rejected_note
)
from src.agent.llm.transport.transport import TransportError
from src.agent.prompt.task_profile.task_profile import TaskProfile
from src.agent.prompt.template import build_system_prompt
from src.config.settings import Limits
from src.models.output import SolutionOutput, StepMetrics
from src.models.sandbox_base import SandboxBase
from src.models.output import ExecuteResult

_DEFAULT_STOP_SEQUENCE = ["<end_code>"]

# 提出物を受理する前に検証する関数の型。提出物を受け取り、合否 / 不合格の理由を返す。
SolutionVerifier = Callable[[str], tuple[bool, str]]


class Orchestrator:
    """1タスク分の Thought -> Code -> Observationのループを制御するOrchestratorクラス."""

    def __init__(
        self,
        provider: LLMGenerator,
        extractor: CodeExtractor,
        sandbox: SandboxBase,
        profile: TaskProfile,
        limits: Limits,
        stop_sequence: list[str] | None = None,
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
            stop_sequence (list[str] | None, optional):
                LLMの出力を打ち切るためのシーケンスのリスト。Noneの場合["<end_code>"]
            solution_verifier (SolutionVerifier | None, optional):
                提出物を検証する関数。Noneの場合は検証を行わない。
            start_time (float | None, optional):
                CLI起動時からのタスク開始時刻。
        """
        self.provider = provider
        self.extractor = extractor
        self.sandbox = sandbox
        self.profile = profile
        self.limits = limits
        self.stop_sequences = stop_sequence if stop_sequence is not None else list(_DEFAULT_STOP_SEQUENCE)
        self.solution_verifier = solution_verifier
        self.start_time = start_time
        # 入力トークンの見積もりの係数(1トークンあたりの文字数)。実測に合わせ安全側には補正OK。
        self._chars_per_token = self._CHARS_PER_TOKEN

    def run(self, task_id: str, benchmark: str, task_message: str) -> SolutionOutput:
        """1タスク分のループを回しSolutionOutputを生成する.

        Args:
            task_id (str): タスク識別子(MBPPのtask_idまたはSWE-benchのinstance_id)
            benchmark (str): ベンチマークの種類: 'mbpp' または 'swebench'
            task_message (str): LLMに渡す問題分

        Returns:
            SolutionOutput:
                成功ならエージェントの最終的な解答とメトリクスを含むSolutionOutputオブジェクト。
                打ち切りなら errorに打ち切り理由を含むSolutionOutputオブジェクト。
        """
        # システムプロンプトとユーザープロンプトを組み合わせて、最初のメッセージを作成
        system_prompt = build_system_prompt(self.profile, self.sandbox)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task_message}
        ]

        # ループ前の下準備
        tracker = LimitTracker(self.limits, start_time=self.start_time)
        steps: list[StepMetrics] = []
        # 打ち切り時に提出するコードの候補を保持する変数。Observationが生成されるたびに更新される。
        # TaskProfileがそのまま提出できると判断したものを入れる。
        best_solution: str = ""

        # ループ本体
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

            # 送信する履歴を制限に収まるように切り詰める。収まらなければSolutionOutputを返す
            windowed = self._fit_window(messages, tracker)
            if windowed is None:
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

            # LLMにリクエストを送信し、レスポンスを取得する
            max_tokens = min(
                self.limits.max_output_tokens_per_iteration,
                tracker.remaining_output_tokens()
            )
            try:
                response: LLMResponse = self.provider.generate(
                    messages=windowed,
                    stop_sequences=self.stop_sequences,
                    max_tokens=max_tokens
                )
            # ResilientLLMClient.generate()は全部のプロバイダ / 全部のキーを試しても成功しなかった場合
            # AllProvidersExhaustedを送出する。
            # その他のLLMGeneratorを単体で使用した場合に、generate()の例外はLLMError / TransportErrorが送出される。
            except (LLMError, TransportError) as error:
                # 総試行回数を取得する
                failed_requests = getattr(error, "attempts", 1)
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

            # 消費トークン数をLimitTrackerに記録する
            tracker.record_usage(
                response.input_tokens,
                response.output_tokens,
            )
            # 送った文字数と報告された入力トークン数から見積もりの係数を安全側に補正する。
            self._learn_chars_per_token(sent=messages, response=response)
            # LLMのレスポンスを履歴に追加する
            messages.append(
                {"role": "assistant", "content": response.text}
            )

            # レスポンスからコードを抽出する
            cleaned_code = strip_stop_sequences(response.text, self.stop_sequences)
            code = self.extractor.extract(cleaned_code)

            # コードが抽出できなかった場合は、Observationを生成して次のループに進む。
            if code is None:
                observation = observation_no_code()
                messages.append(
                    {"role": "user", "content": observation}
                )
                steps.append(
                    self._build_step(len(steps) + 1, response, "", observation)
                )
                continue

            # コードが抽出できた場合はサンドボックスで実行しObservationを生成する
            result: ExecuteResult = self.sandbox.run(code)
            observation = build_observation(result)

            # 崩れたコードを救済実行した場合は[MALFORMED_CODE]の種類をLLMに伝えるためにobservationの前に追加
            salvaged = salvage_kind(cleaned_code)
            if salvaged is not None:
                observation = f"{malformed_code_note(salvaged)}\n{observation}"

            # 最終的な提出物。提出物があり、かつ受理された場合のみ中身が入る。
            submission: str | None = None
            # final_answer()が呼ばれた場合、提出物を検査する。
            if result.final_answer_bool:
                raw_submission = result.final_answer or ""
                candidate, rejection = self._review_submission(raw_submission)
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

            # Observationを履歴に追加し、StepMetricsを作成してstepsに追加する。
            messages.append(
                {"role": "user", "content": observation}
            )
            steps.append(
                self._build_step(len(steps) + 1, response, code, observation)
            )

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

    # 入力トークンの見積もりの係数の初期値。超えないために小さめに取る。
    _CHARS_PER_TOKEN = 3.0
    # 実測した1トークンあたりの文字数の安全側補正値。実測値より小さくなるようにする。
    _CHARS_PER_TOKEN_SAFETY = 0.95
    # メッセージ1件ごとに足すrole / contentのトークン数。
    _TOKENS_PER_MESSAGE = 4

    def _fit_window(self, messages: list[dict[str, str]], tracker: LimitTracker) -> list[dict[str, str]] | None:
        """累積入力トークンの上限に収まる送信用の履歴を返す。どう縮めても収まらなければNone.

        直近の profile.history_window 往復 -> ... -> 1往復 -> systemとタスク文だけの順に縮める。
        履歴はいきなり全部捨てると直前の失敗と原因(Observation)がLLMに伝わらず同じ失敗を繰り返すので、
        1往復ずつ減らす。

        Args:
            messages (list[dict[str, str]]): これまでの全履歴
            tracker (LimitTracker): 今の消費状況。

        Returns:
            list[dict[str, str]] | None: 送信用のメッセージ列。収まらなければNone。
        """
        # 送信可能なトークン数の予算を計算する
        budget = self.limits.max_input_tokens - tracker.total_input_tokens
        # 2, 1, 0の順に履歴を切り詰めて、収まるものを返す。収まらなければNone。
        for window_size in range(self.profile.history_window_size, -1, -1):
            candidate = self._window_messages(messages, window_size)
            if self._estimate_tokens(candidate) <= budget:
                return candidate

        return None

    def _window_messages(self, messages: list[dict[str, str]], window_size: int) -> list[dict[str, str]]:
        """LLMに送る履歴を直近のwindow_size往復に切りつめて返す.

        Chat Completionは状態を持たず、毎回すべての履歴を送る。
        全履歴を送り続けると累積トークンは反復の回数の2乗で増えるので、
        system + task_message + 直近のwindow_size往復(assistant + Observation)だけを送る。
        長いObservationとassistantの発話はプロファイルごとの上限文字数まで中央を省いて縮める。

        Args:
            messages (list[dict[str, str]]): これまで[system, user, (assistant, user)...]の全履歴
            window_size (int): 残す往復の数。0ならsystemとタスク文だけ。

        Returns:
            list[dict[str, str]]: 切り詰めた送信用のメッセージ列。
        """
        # systemとタスク文は必ず残す。
        head = messages[:2]
        # 1往復はassistantの発話 + Observationの2件なので、直近window_size往復は末尾の * 2件
        # window_size == 0だど[-0:]だと全て残ってしまうので0の時は空リストにする。
        tail = messages[2:][-window_size * 2:] if window_size > 0 else []

        max_chars_by_role = {
            "user": self.profile.observation_max_chars,
            "assistant": self.profile.assistant_max_chars
        }
        trimmed: list[dict[str, str]] = []
        for index, message in enumerate(tail):
            max_chars = max_chars_by_role[message["role"]]
            if index == len(tail) - 1 and message["role"] == "user":
                max_chars = self.profile.latest_observation_max_chars

            trimmed.append({"role": message["role"], "content": _truncate_middle(message["content"], max_chars)})

        return head + trimmed

    def _estimate_tokens(self, messages: list[dict[str, str]]) -> int:
        """これから送るメッセージ列のトークン数を見積もる.

        累積input_tokensの上限を超えないようにするための事前ガード。
        越えると不合格になるので少し小さく見積もる。

        Args:
            messages (list[dict[str, str]]): これから送るメッセージ列

        Returns:
            int: 見積もった入力トークン数
        """
        characters = sum(len(message["content"]) for message in messages)
        return int(characters / self._chars_per_token) + 1 + self._TOKENS_PER_MESSAGE * len(messages)

    def _learn_chars_per_token(self, sent: list[dict[str, str]], response: LLMResponse) -> None:
        """実際に送った文字数と報告された入力トークン数から、1トークンあたりの文字数の係数を安全側に補正する.

        トークナイザーを使うと正確に計算できるが、トークナイザーの実装はプロバイダごとに異なるため、
        実測値を使って安全側に補正する。
        実測の比が今の係数より小さければ係数を下げる。
        リトライがあったレスポンス(retries > 0)は失敗した試行のトークンが足されているので補正に使わない。
        3000文字送って1200トークン使ったと返ってきたら 2.5文字/トークン で今の3.0より小さいので係数を2.5に下げる。

        Args:
            sent (list[dict[str, str]]): このリクエストで送ったメッセージ列
        """
        if response.retries or response.input_tokens <= 0:
            return

        characters = sum(len(message["content"]) for message in sent)
        observed = characters / response.input_tokens * self._CHARS_PER_TOKEN_SAFETY

        # 1トークンあたりの文字数の係数を補正する。実測値より小さくなるようにする。
        if 0 < observed < self._chars_per_token:
            self._chars_per_token = observed

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
        """ループの結果からSolutionOutputを構築するヘルパー関数.(成功 / 打ち切り共通)

        提出物がないまま打ち切られた場合TaskProfileに提出物を回収させる。
        SWEbenchなら編集済みのバッチ。空の提出は可能な限りさせない。

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


_TRUNCATED_MIDDLE_MARKER = "\n... [truncated] ...\n"


def _truncate_middle(content: str, max_chars: int) -> str:
    """文字列の中央を省略してmax_charsに収める.

    Observationは先頭に実行結果(status / stdout / stderr)があり、
    末尾に'--- note ---'の助言を置いている。
    先頭だけ残す切り詰めだと行動を促す助言(切り詰めの警告、提出の却下理由)が消えるので中央を省略する。

    Args:
        text (str): 省略する文字列
        max_chars (int): 省略後の最大文字数

    Returns:
        str: max_charsに収めた文字列。超えていれば中央を目印に置き換える。
    """
    if len(content) <= max_chars:
        return content

    # 上限の2/3を先頭(systemとタスク文とそれ以降)、下限の1/3を末尾に残す。中央は目印に置き換える。
    head_size = max_chars * 2 // 3
    tail_size = max_chars - head_size
    return f"{content[:head_size]}{_TRUNCATED_MIDDLE_MARKER}{content[-tail_size:]}"

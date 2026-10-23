"""Orchestrator(orchestrator.py)のループ制御テスト。LLMはStubProviderで決定的に差替."""
from src.agent.llm.resilient_client import AllProvidersExhausted
from src.agent.extractor.composite_extractor import CompositeCodeExtractor
from src.agent.extractor.python_extractor import PythonCodeExtractor
from src.agent.llm.provider.provider import LLMProvider, LLMResponse
from src.agent.orchestrator import Orchestrator
from src.agent.prompt.task_profile.mbpp_profile import MBPPProfile
from src.agent.prompt.task_profile.swebench_profile import SWEBenchProfile
from src.config.settings import Limits
from src.models.sandbox_base import SandboxBase
from src.sandbox.mock import MockSandbox

_RESP_PRINT = "Thought: test it.\n```python\nprint('hello')\n```\n<end_code>"
_RESP_FINAL = "Thought: submit.\n```python\nfinal_answer('def f():\\n    return 1')\n```\n<end_code>"
_RESP_NO_CODE = "I think the answer is 42 but I will not write any code block."
_RESP_ENDCODE_INSIDE = "Thought: oops.\n```python\nprint('x')<end_code>\n```"


class StubProvider(LLMProvider):
    """台本どおりに応答を返す決定的プロバイダ(ネットワーク不要)."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self._index = 0

    def generate(self, messages: list[dict[str, str]], stop_sequences: list[str], max_tokens: int) -> LLMResponse:
        text = self._responses[self._index]
        self._index += 1
        return LLMResponse(
            text=text, input_tokens=10, output_tokens=5, request_time_ms=1.0,
            api_url="stub", model_name="stub", retries=0,
        )

    def _build_request(self, messages: list[dict[str, str]], stop_sequences: list[str], max_tokens: int):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def _parse_response(self, body: str, request_time_ms: float) -> LLMResponse:
        raise NotImplementedError


def _limits(**kw: object) -> Limits:
    base: dict[str, object] = dict(
        max_iterations=5, max_input_tokens=10**9, max_output_tokens=10**9,
        total_time_sec=10**9, time_margin_sec=1.0,
    )
    base.update(kw)
    return Limits(**base)  # type: ignore[arg-type]


def _orchestrator(responses: list[str], **limit_kw: object) -> Orchestrator:
    return Orchestrator(
        provider=StubProvider(responses),
        extractor=PythonCodeExtractor(),
        sandbox=MockSandbox(),
        profile=MBPPProfile(),
        limits=_limits(**limit_kw),
    )


def _block(code: str) -> str:
    """1つのPythonブロックだけを含むLLMの応答を作る."""
    return f"Thought: step.\n```python\n{code}\n```\n<end_code>"


def test_final_answer_success() -> None:
    """1反復で final_answer 提出 -> success / solution / iterations."""
    solution = _orchestrator([_RESP_FINAL]).run("82", "mbpp", "task")
    assert solution.success is True
    assert solution.solution == "def f():\n    return 1"
    assert solution.iterations == 1
    assert len(solution.steps) == 1
    assert solution.error is None


def test_no_code_then_success() -> None:
    """コード無し -> 再促し -> 次反復で提出成功(2反復)."""
    solution = _orchestrator([_RESP_NO_CODE, _RESP_FINAL]).run("82", "mbpp", "task")
    assert solution.success is True
    assert solution.iterations == 2
    assert solution.steps[0].sandbox_input == ""
    assert solution.steps[0].sandbox_output.startswith("[NO_CODE]")


def test_limit_stop_max_iterations() -> None:
    """final_answer を出さないと max_iterations で打切り。printだけの断片は提出候補にしない(A-12)."""
    solution = _orchestrator([_RESP_PRINT, _RESP_PRINT], max_iterations=2).run("82", "mbpp", "task")
    assert solution.success is False
    assert solution.error == "MAX_ITERATIONS"
    assert solution.iterations == 2
    assert solution.solution == ""


def test_endcode_inside_block_is_stripped() -> None:
    """コードブロック内の <end_code> を抽出前に除去して実行できる(回収#2)."""
    solution = _orchestrator([_RESP_ENDCODE_INSIDE, _RESP_FINAL]).run("82", "mbpp", "task")
    assert solution.steps[0].sandbox_output.startswith("[OK]")
    assert "x" in solution.steps[0].sandbox_output
    assert solution.success is True


def test_solution_metrics_totals() -> None:
    """トークン累計 / リクエスト数 / 反復数が集計される."""
    solution = _orchestrator([_RESP_PRINT, _RESP_FINAL]).run("82", "mbpp", "task")
    assert solution.total_input_tokens == 20
    assert solution.total_output_tokens == 10
    assert solution.total_requests == 2
    assert solution.iterations == 2


class _RaisingProvider:
    """generate が必ず AllProvidersExhausted を送出する(全滅の再現)."""

    def generate(self, messages: list[dict[str, str]], stop_sequences: list[str], max_tokens: int) -> LLMResponse:
        raise AllProvidersExhausted("all providers/keys exhausted")


def test_llm_unavailable_is_graceful() -> None:
    """generateが全滅例外でもクラッシュせず success=False / error=LLM_UNAVAILABLE を返す."""
    orchestrator = Orchestrator(
        provider=_RaisingProvider(), extractor=PythonCodeExtractor(), sandbox=MockSandbox(),
        profile=MBPPProfile(), limits=_limits(),
    )
    solution = orchestrator.run("82", "mbpp", "task")
    assert solution.success is False
    assert solution.error == "LLM_UNAVAILABLE"
    assert solution.steps == []
    assert solution.solution == ""
    assert solution.total_requests == 0  # attempts未指定(=0)の全滅なら試行加算も0


class _RetryingStub(LLMProvider):
    """各応答に retries 回数を持たせて返すスタブ(total_requests計上の検証用)."""

    def __init__(self, responses: list[tuple[str, int]]) -> None:
        self._responses = responses
        self._index = 0

    def generate(self, messages: list[dict[str, str]], stop_sequences: list[str], max_tokens: int) -> LLMResponse:
        text, retries = self._responses[self._index]
        self._index += 1
        return LLMResponse(
            text=text, input_tokens=10, output_tokens=5, request_time_ms=1.0,
            api_url="stub", model_name="stub", retries=retries,
        )

    def _build_request(self, messages, stop_sequences, max_tokens):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def _parse_response(self, body: str, request_time_ms: float) -> LLMResponse:
        raise NotImplementedError


def test_total_requests_includes_retries() -> None:
    """total_requests は各stepの (retries+1) 合計(HTTP試行数、リトライ込み)."""
    provider = _RetryingStub([(_RESP_PRINT, 2), (_RESP_FINAL, 0)])
    orchestrator = Orchestrator(
        provider=provider, extractor=PythonCodeExtractor(), sandbox=MockSandbox(),
        profile=MBPPProfile(), limits=_limits(),
    )
    solution = orchestrator.run("82", "mbpp", "task")
    # step1: retries=2 -> 3試行, step2: retries=0 -> 1試行 => 合計4
    assert solution.total_requests == 4
    assert solution.steps[0].retries == 2


class _ExhaustAfterFirstProvider:
    """1回目のgenerateは成功、2回目で attempts を消費して全滅する(途中全滅の再現)."""

    def __init__(self, first: LLMResponse, attempts: int) -> None:
        self._first = first
        self._attempts = attempts
        self._called = 0

    def generate(self, messages: list[dict[str, str]], stop_sequences: list[str], max_tokens: int) -> LLMResponse:
        self._called += 1
        if self._called == 1:
            return self._first
        raise AllProvidersExhausted("exhausted", attempts=self._attempts)


def test_total_requests_includes_failed_attempts() -> None:
    """途中で全滅した場合、成功step分 + 全滅時の試行数が total_requests に入る."""
    first = LLMResponse(
        text=_RESP_PRINT, input_tokens=10, output_tokens=5,
        request_time_ms=1.0, api_url="stub", model_name="stub", retries=0,
    )
    provider = _ExhaustAfterFirstProvider(first, attempts=3)
    orchestrator = Orchestrator(
        provider=provider, extractor=PythonCodeExtractor(), sandbox=MockSandbox(),
        profile=MBPPProfile(), limits=_limits(),
    )
    solution = orchestrator.run("82", "mbpp", "task")
    assert solution.success is False
    assert solution.error == "LLM_UNAVAILABLE"
    assert len(solution.steps) == 1          # 1回目のstepだけ積まれる
    assert solution.total_requests == 1 + 3  # step1の1試行 + 全滅時の3試行


class _EmptyThenExhaustedProvider:
    """全滅し、空応答で消費したトークンを例外に持たせて送出する."""

    def generate(self, messages: list[dict[str, str]], stop_sequences: list[str], max_tokens: int) -> LLMResponse:
        raise AllProvidersExhausted("exhausted", attempts=2, input_tokens=900, output_tokens=600)


def test_exhausted_wasted_tokens_are_counted_in_totals() -> None:
    """全滅しても、空応答で消費されたトークンは SolutionOutput の合計に入る(制限の判定を甘くしない)."""
    orchestrator = Orchestrator(
        provider=_EmptyThenExhaustedProvider(), extractor=PythonCodeExtractor(), sandbox=MockSandbox(),
        profile=MBPPProfile(), limits=_limits(),
    )
    solution = orchestrator.run("82", "mbpp", "task")
    assert solution.error == "LLM_UNAVAILABLE"
    assert (solution.total_input_tokens, solution.total_output_tokens) == (900, 600)
    assert solution.total_requests == 2


def test_unclosed_fence_is_executed_and_reported() -> None:
    """出力上限で閉じフェンスが欠けても実行し、救済したことを Observation の先頭で伝える(課題 V.1)."""
    truncated = "Thought: run it.\n```python\nprint('salvaged')\n"
    solution = _orchestrator([truncated, _RESP_FINAL]).run("82", "mbpp", "task")
    assert solution.steps[0].sandbox_input == "print('salvaged')"
    assert solution.steps[0].sandbox_output.startswith("[MALFORMED_CODE]")
    assert "salvaged" in solution.steps[0].sandbox_output
    assert solution.success is True


def test_leaked_stop_prefix_does_not_break_the_block() -> None:
    """停止シーケンスの前半(```<end_code)が漏れても、正規のブロックとして実行し救済扱いにしない."""
    leaked = "Thought: run it.\n```python\nprint('clean')\n```<end_code"
    solution = _orchestrator([leaked, _RESP_FINAL]).run("82", "mbpp", "task")
    assert solution.steps[0].sandbox_input == "print('clean')"
    assert solution.steps[0].sandbox_output.startswith("[OK]")


def test_draft_final_answer_in_an_earlier_block_is_not_submitted() -> None:
    """下書きの final_answer と直した版の2ブロックがあれば、直した版(最後)を提出する."""
    two_blocks = (
        "Draft:\n```python\nfinal_answer('def f():\\n    return 0')\n```\n"
        "Fixed:\n```python\nfinal_answer('def f():\\n    return 1')\n```\n<end_code>"
    )
    solution = _orchestrator([two_blocks]).run("82", "mbpp", "task")
    assert solution.success is True
    assert solution.solution == "def f():\n    return 1"


def _composite_orchestrator(responses: list[str]) -> Orchestrator:
    """CLIと同じCompositeCodeExtractorを使うOrchestrator(A-07)."""
    return Orchestrator(
        provider=StubProvider(responses),
        extractor=CompositeCodeExtractor(),
        sandbox=MockSandbox(),
        profile=MBPPProfile(),
        limits=_limits(),
    )


def test_react_final_answer_is_submitted_through_the_loop() -> None:
    """ReAct形式の final_answer が変換・実行され、引数名(answer)が違っても提出される."""
    react = 'Thought: done.\nAction: final_answer\nAction Input: {"answer": "def f():\\n    return 1"}'
    solution = _composite_orchestrator([react]).run("82", "mbpp", "task")
    assert solution.success is True
    assert solution.solution == "def f():\n    return 1"
    assert solution.steps[0].sandbox_input == "print(final_answer('def f():\\n    return 1'))"


def test_hermes_tool_call_then_python_final_answer() -> None:
    """Hermes形式の呼び出しを実行してObservationを返し、次の反復のPythonブロックで提出する."""
    hermes = '<tool_call>{"name": "print", "arguments": {"sep": "-"}}</tool_call>'
    solution = _composite_orchestrator([hermes, _RESP_FINAL]).run("82", "mbpp", "task")
    assert solution.success is True
    assert solution.iterations == 2
    assert solution.steps[0].sandbox_input == "print(print(sep='-'))"

    # ---- A-12: 提出の検査パイプラインと打ち切り時の回収 ----


def test_cutoff_submits_the_last_submittable_code() -> None:
    """打ち切り時は、エラーなく実行できた「提出できる形」のコードのうち最後のものを提出する."""
    responses = [
        _block("def f():\n    return 1"),
        _block("def f():\n    return 2"),
        _RESP_PRINT,  # 提出できる形ではないので、候補を上書きしない
    ]
    solution = _orchestrator(responses, max_iterations=3).run("82", "mbpp", "task")
    assert solution.success is False
    assert solution.error == "MAX_ITERATIONS"
    assert solution.solution == "def f():\n    return 2"


def test_code_that_raised_is_not_a_fallback_candidate() -> None:
    """関数定義を含んでいても、実行時に例外を投げたコードは候補にしない."""
    responses = [
        _block("def f():\n    return 1"),
        _block("def f():\n    return 2\nx = 1 / 0"),
    ]
    solution = _orchestrator(responses, max_iterations=2).run("82", "mbpp", "task")
    assert solution.solution == "def f():\n    return 1"


def test_rejected_submission_is_sent_back_with_the_reason() -> None:
    """検査に落ちた提出は受理せず、理由を Observation の末尾で伝え、次の反復で直した提出を受理する."""
    responses = [_block("final_answer('print(1)')"), _RESP_FINAL]
    solution = _orchestrator(responses).run("82", "mbpp", "task")
    assert solution.success is True
    assert solution.iterations == 2
    assert solution.solution == "def f():\n    return 1"
    first_observation = solution.steps[0].sandbox_output
    assert "--- submission rejected ---" in first_observation
    assert "no function definition" in first_observation
    assert first_observation.endswith("Fix it and call final_answer() again.")


def test_empty_final_answer_is_reported_once() -> None:
    """空の final_answer は [FINAL_ANSWER_INVALID] で伝え済みなので、差し戻しの節を重ねない."""
    responses = [_block("final_answer('')"), _RESP_FINAL]
    solution = _orchestrator(responses).run("82", "mbpp", "task")
    first_observation = solution.steps[0].sandbox_output
    assert first_observation.startswith("[FINAL_ANSWER_INVALID]")
    assert "--- submission rejected ---" not in first_observation
    assert solution.success is True
    assert solution.iterations == 2


def test_fenced_submission_is_sanitized_before_it_is_accepted() -> None:
    """コードフェンス付きの提出は、フェンスを落としてから検査・受理する."""
    fenced = "```python\ndef f():\n    return 1\n```"
    solution = _orchestrator([_block(f"final_answer({fenced!r})")]).run("82", "mbpp", "task")
    assert solution.success is True
    assert solution.solution == "def f():\n    return 1"


class _RecordingVerifier:
    """呼ばれた提出物を記録し、決まった合否を返す solution_verifier."""

    def __init__(self, verdicts: list[tuple[bool, str]]) -> None:
        self.verdicts = verdicts
        self.calls: list[str] = []

    def __call__(self, candidate: str) -> tuple[bool, str]:
        self.calls.append(candidate)
        return self.verdicts[len(self.calls) - 1]


def _verified_orchestrator(responses: list[str], verifier: _RecordingVerifier, **limit_kw: object) -> Orchestrator:
    return Orchestrator(
        provider=StubProvider(responses),
        extractor=PythonCodeExtractor(),
        sandbox=MockSandbox(),
        profile=MBPPProfile(),
        limits=_limits(**limit_kw),
        solution_verifier=verifier,
    )


def test_verifier_failure_sends_back_the_detail_and_keeps_the_candidate() -> None:
    """検証に落ちた提出は詳細つきで差し戻す。提出できる形なので、打ち切り時の候補には残す."""
    verifier = _RecordingVerifier([(False, "assert f() == 2 failed: got 1")])
    solution = _verified_orchestrator([_RESP_FINAL], verifier, max_iterations=1).run("82", "mbpp", "task")
    assert verifier.calls == ["def f():\n    return 1"]
    assert "assert f() == 2 failed: got 1" in solution.steps[0].sandbox_output
    assert solution.success is False
    assert solution.error == "MAX_ITERATIONS"
    assert solution.solution == "def f():\n    return 1"


def test_verifier_is_not_called_when_the_profile_rejects() -> None:
    """TaskProfile の検査で落ちた提出には、重い検証を走らせない."""
    verifier = _RecordingVerifier([(True, "")])
    responses = [_block("final_answer('print(1)')"), _RESP_FINAL]
    solution = _verified_orchestrator(responses, verifier).run("82", "mbpp", "task")
    assert verifier.calls == ["def f():\n    return 1"]
    assert solution.success is True


class _PatchCollectingProfile(SWEBenchProfile):
    """打ち切り時に環境からパッチを回収するプロファイル(A-22 の SWEBenchProfile の代わり)."""

    def __init__(self, collected: str = "diff --git a/x.py b/x.py\n", fail: bool = False) -> None:
        self.collected = collected
        self.fail = fail
        self.fallback_calls = 0

    def submission_rejection(self, candidate: str) -> str | None:
        """diff の目印が無い提出を拒否する."""
        return None if candidate.startswith("diff --git") else "Submit the output of get_patch()."

    def fallback_solution(self, sandbox: SandboxBase) -> str:
        """回収した回数を数え、決まったパッチを返す(fail なら例外を投げる)."""
        self.fallback_calls += 1
        if self.fail:
            raise RuntimeError("tool server is gone")
        return self.collected


def _swebench_orchestrator(responses: list[str], profile: _PatchCollectingProfile, **limit_kw: object) -> Orchestrator:
    return Orchestrator(
        provider=StubProvider(responses),
        extractor=PythonCodeExtractor(),
        sandbox=MockSandbox(),
        profile=profile,
        limits=_limits(**limit_kw),
    )


def test_cutoff_collects_the_patch_from_the_environment() -> None:
    """提出が無いまま打ち切られたら、プロファイルが環境から回収したものを提出する(成功扱いにはしない)."""
    profile = _PatchCollectingProfile()
    solution = _swebench_orchestrator([_RESP_PRINT], profile, max_iterations=1).run("x", "swebench", "task")
    assert solution.success is False
    assert solution.error == "MAX_ITERATIONS"
    assert solution.solution == "diff --git a/x.py b/x.py\n"
    assert profile.fallback_calls == 1


def test_rejected_handwritten_diff_does_not_block_the_collection() -> None:
    """差し戻した手書きの diff は候補に残さない。打ち切り時は環境から本物のパッチを回収する.

    テストブランチ版は差し戻した提出を無条件で候補に残したため、回収が走らず壊れた diff を提出していた。
    """
    profile = _PatchCollectingProfile()
    responses = [_block("final_answer('--- a/x.py\\n+++ b/x.py')")]
    solution = _swebench_orchestrator(responses, profile, max_iterations=1).run("x", "swebench", "task")
    assert "--- submission rejected ---" in solution.steps[0].sandbox_output
    assert solution.solution == "diff --git a/x.py b/x.py\n"
    assert profile.fallback_calls == 1


def test_collection_is_skipped_on_success() -> None:
    """検査を通った提出があれば、回収は呼ばない(SWEBenchProfileの整形で末尾の改行は残る・A-22)."""
    profile = _PatchCollectingProfile()
    responses = [_block("final_answer('diff --git a/y.py b/y.py\\n')")]
    solution = _swebench_orchestrator(responses, profile).run("x", "swebench", "task")
    assert solution.success is True
    assert solution.solution == "diff --git a/y.py b/y.py\n"
    assert profile.fallback_calls == 0


def test_collection_runs_when_the_llm_is_unavailable() -> None:
    """LLM が全滅して打ち切られた場合も、環境に残った編集を回収する."""
    profile = _PatchCollectingProfile()
    orchestrator = Orchestrator(
        provider=_RaisingProvider(), extractor=PythonCodeExtractor(), sandbox=MockSandbox(),
        profile=profile, limits=_limits(),
    )
    solution = orchestrator.run("x", "swebench", "task")
    assert solution.error == "LLM_UNAVAILABLE"
    assert solution.solution == "diff --git a/x.py b/x.py\n"


def test_failed_collection_does_not_crash() -> None:
    """回収が例外を投げても、空の提出と打ち切り理由を返す(結果の書き出しまで失わない)."""
    profile = _PatchCollectingProfile(fail=True)
    solution = _swebench_orchestrator([_RESP_PRINT], profile, max_iterations=1).run("x", "swebench", "task")
    assert solution.success is False
    assert solution.error == "MAX_ITERATIONS"
    assert solution.solution == ""
    assert profile.fallback_calls == 1


def test_start_time_counts_time_spent_before_run() -> None:
    """start_timeを渡すと、run()の前に使った時間(サーバーの起動など)も制限時間に入れる.

    起動から制限時間ぶん過ぎていれば、LLMを1回も呼ばずに TIME_LIMIT で返す。
    """
    import time
    provider = StubProvider([])  # 呼ばれたら IndexError で落ちる
    orchestrator = Orchestrator(
        provider=provider,
        extractor=PythonCodeExtractor(),
        sandbox=MockSandbox(),
        profile=MBPPProfile(),
        limits=_limits(total_time_sec=120.0, time_margin_sec=10.0),
        start_time=time.monotonic() - 115.0,  # 起動から115秒たってからrun()に入った
    )
    solution = orchestrator.run("1", "mbpp", "task")
    assert solution.success is False
    assert solution.error == "TIME_LIMIT"
    assert solution.iterations == 0
    assert solution.total_time_seconds >= 115.0



# ===================== A-10 / A-11: 履歴の窓と、累積入力の事前ガード =====================

from src.agent.orchestrator import _TRUNCATED_MIDDLE_MARKER  # noqa: E402


class _TokenizingProvider(StubProvider):
    """送られた文字数から入力トークン数を計算して報告し、送られたメッセージ列を記録するスタブ."""

    def __init__(self, responses: list[str], chars_per_token: float) -> None:
        super().__init__(responses)
        self.chars_per_token = chars_per_token
        self.sent: list[list[dict[str, str]]] = []

    def generate(self, messages: list[dict[str, str]], stop_sequences: list[str], max_tokens: int) -> LLMResponse:
        self.sent.append([dict(message) for message in messages])
        response = super().generate(messages, stop_sequences, max_tokens)
        tokens = int(sum(len(message["content"]) for message in messages) / self.chars_per_token)
        return response.model_copy(update={"input_tokens": tokens})


def _long_print(width: int) -> str:
    """長い出力を返すコードを書くLLMの応答(実行すると width 文字を print する)."""
    return f"Thought: look.\n```python\nprint('{'x' * width}')\n```"


def test_window_truncation_keeps_the_trailing_note() -> None:
    """長いObservationは中央を省いて両端を残す(末尾の --- note --- の助言を落とさない)."""
    observation = "[OK] head marker\n" + ("x" * 5000) + "\n--- note ---\nTAIL MARKER"
    windowed = _orchestrator([])._window_messages(
        [{"role": "system", "content": "s"}, {"role": "user", "content": "task"},
         {"role": "assistant", "content": "a"}, {"role": "user", "content": observation}],
        window_size=2,
    )
    sent = windowed[-1]["content"]
    assert len(sent) == MBPPProfile.latest_observation_max_chars + len(_TRUNCATED_MIDDLE_MARKER)
    assert sent.startswith("[OK] head marker")
    assert sent.endswith("TAIL MARKER")


def test_older_observations_are_trimmed_harder_than_the_latest() -> None:
    """直前のObservationは長めに残し、それより前のものと、assistantの発話は短く切り詰める."""
    marker = len(_TRUNCATED_MIDDLE_MARKER)
    windowed = _orchestrator([])._window_messages(
        [{"role": "system", "content": "s" * 9000}, {"role": "user", "content": "t" * 9000},
         {"role": "assistant", "content": "a" * 5000}, {"role": "user", "content": "OLD " + "y" * 5000},
         {"role": "assistant", "content": "b" * 5000}, {"role": "user", "content": "NEW " + "z" * 5000}],
        window_size=2,
    )
    assert [len(message["content"]) for message in windowed] == [
        9000, 9000,  # systemとタスク文は切り詰めない
        MBPPProfile.assistant_max_chars + marker, MBPPProfile.observation_max_chars + marker,
        MBPPProfile.assistant_max_chars + marker, MBPPProfile.latest_observation_max_chars + marker,
    ]


def test_only_the_latest_rounds_are_resent() -> None:
    """毎回送るのは system + タスク文 + 直近 history_window 往復だけ(全履歴を送らない)."""
    provider = _TokenizingProvider([_RESP_PRINT] * 5, chars_per_token=4.0)
    orchestrator = Orchestrator(
        provider=provider, extractor=PythonCodeExtractor(), sandbox=MockSandbox(), profile=MBPPProfile(),
        limits=_limits(max_iterations=5),
    )
    orchestrator.run("1", "mbpp", "task")
    assert [len(messages) for messages in provider.sent] == [2, 4, 6, 6, 6]  # MBPPは直近2往復
    assert [message["content"] for message in provider.sent[-1][:2]] == [provider.sent[0][0]["content"], "task"]


def test_input_guard_shrinks_window_before_giving_up() -> None:
    """累積入力の残りが少なくなったら窓を縮めて送り、それでも収まらなければ送らずに止める."""
    provider = _TokenizingProvider([_long_print(3000)] * 10, chars_per_token=4.0)
    orchestrator = Orchestrator(
        provider=provider, extractor=PythonCodeExtractor(), sandbox=MockSandbox(), profile=MBPPProfile(),
        limits=_limits(max_input_tokens=6000, max_iterations=10),
    )
    solution = orchestrator.run("1", "mbpp", "task")
    assert solution.total_input_tokens <= 6000
    assert solution.error == "MAX_INPUT_TOKENS"
    sizes = [len(messages) for messages in provider.sent]
    assert max(sizes) == 6 and min(sizes[sizes.index(6):]) < 6  # 一度広げた窓を、途中で縮めて送った


def test_input_guard_learns_a_finer_tokenizer_and_still_never_overshoots() -> None:
    """トークナイザが見積もりより細かくても(1トークン=2文字)、係数を学習して上限を踏み越えない.

    初期の係数(3.0文字/トークン)のままだと、見積もりが実際の2/3になり、上限を踏み越える。
    """
    provider = _TokenizingProvider([_long_print(3000)] * 10, chars_per_token=2.0)
    orchestrator = Orchestrator(
        provider=provider, extractor=PythonCodeExtractor(), sandbox=MockSandbox(), profile=MBPPProfile(),
        limits=_limits(max_input_tokens=6000, max_iterations=10),
    )
    solution = orchestrator.run("1", "mbpp", "task")
    assert solution.total_input_tokens <= 6000
    assert solution.error == "MAX_INPUT_TOKENS"
    assert orchestrator._chars_per_token < 2.0  # 実測の 2.0 よりさらに安全側(×0.95)


def test_swebench_keeps_a_wider_window() -> None:
    """SWE-benchは直近6往復を残す(ファイルを読んだ結果を、続く反復でも参照するため)."""
    provider = _TokenizingProvider([_RESP_PRINT] * 8, chars_per_token=4.0)
    orchestrator = Orchestrator(
        provider=provider, extractor=PythonCodeExtractor(), sandbox=MockSandbox(), profile=SWEBenchProfile(),
        limits=_limits(max_iterations=8),
    )
    orchestrator.run("demo-1", "swebench", "task")
    assert [len(messages) for messages in provider.sent] == [2, 4, 6, 8, 10, 12, 14, 14]


def test_input_guard_learns_from_what_was_actually_sent() -> None:
    """係数は「実際に送った(窓で切り詰めた)メッセージ」の文字数から学ぶ.

    1回目のあとに、細かいトークナイザ(1トークン=2文字)のモデルへ替わった場面を想定する
    (ResilientLLMClient のフォールバック)。2回目以降は履歴が窓で切り詰められているので、
    全履歴の文字数で割ると比が大きく出て係数を下げられず、上限を踏み越える(6,744 / 6,000)。
    """
    class _SwitchingTokenizer(_TokenizingProvider):
        def generate(self, messages: list[dict[str, str]], stop_sequences: list[str], max_tokens: int) -> LLMResponse:
            self.chars_per_token = 4.0 if not self.sent else 2.0
            return super().generate(messages, stop_sequences, max_tokens)

    provider = _SwitchingTokenizer([_long_print(3000)] * 10, chars_per_token=4.0)
    orchestrator = Orchestrator(
        provider=provider, extractor=PythonCodeExtractor(), sandbox=MockSandbox(), profile=MBPPProfile(),
        limits=_limits(max_input_tokens=6000, max_iterations=10),
    )
    solution = orchestrator.run("1", "mbpp", "task")
    assert solution.total_input_tokens <= 6000
    assert orchestrator._chars_per_token < 2.0


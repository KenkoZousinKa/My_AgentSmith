"""Orchestrator(orchestrator.py)のループ制御テスト。LLMはStubProviderで決定的に差替."""
from src.agent.llm.resilient_client import AllProvidersExhausted
from src.agent.extractor.python_extractor import PythonCodeExtractor
from src.agent.llm.provider.provider import LLMProvider, LLMResponse
from src.agent.orchestrator import Orchestrator
from src.agent.prompt.task_profile.mbpp_profile import MBPPProfile
from src.config.settings import Limits
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
    """final_answer を出さないと max_iterations で打切り(best-so-far を提出)."""
    solution = _orchestrator([_RESP_PRINT, _RESP_PRINT], max_iterations=2).run("82", "mbpp", "task")
    assert solution.success is False
    assert solution.error == "MAX_ITERATIONS"
    assert solution.iterations == 2
    assert solution.solution == "print('hello')"


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

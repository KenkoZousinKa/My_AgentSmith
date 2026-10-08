"""Orchestrator(orchestrator.py)のループ制御テスト。LLMはStubProviderで決定的に差替."""
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

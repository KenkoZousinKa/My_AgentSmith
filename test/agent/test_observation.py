"""Observation 生成(observation.py)のテスト."""
from src.agent.observation import Status, build_observation, collect_statuses, iteration_note, observation_no_code
from src.models.output import ExecuteResult


def _result(**kw: object) -> ExecuteResult:
    """既定=正常終了のExecuteResultを作り、必要フィールドだけ上書きするヘルパ."""
    base: dict[str, object] = dict(
        stdout="", stderr="", error=None, value=None,
        timeout=False, truncated=False, final_answer_bool=False, final_answer=None,
    )
    base.update(kw)
    return ExecuteResult(**base)  # type: ignore[arg-type]


def test_ok_shows_stdout() -> None:
    """正常: [OK] とstdoutを提示."""
    obs = build_observation(_result(stdout="[1, 2, 3]"))
    assert obs.startswith("[OK]")
    assert "--- stdout ---" in obs
    assert "[1, 2, 3]" in obs


def test_ok_no_output_placeholder() -> None:
    """stdout空なら (no output)."""
    assert "(no output)" in build_observation(_result(stdout=""))


def test_exception_shows_traceback_and_note() -> None:
    """例外: [EXCEPTION] と stderr/traceback 見出し・note."""
    obs = build_observation(_result(stdout="starting...", error="ZeroDivisionError: division by zero"))
    assert obs.startswith("[EXCEPTION]")
    assert "--- stderr / traceback ---" in obs
    assert "ZeroDivisionError" in obs
    assert "--- note ---" in obs


def test_timeout_and_truncated_cooccur_in_order() -> None:
    """同時発生: ラベルを決定的順序で全列挙([TIMEOUT][TRUNCATED])."""
    statuses = collect_statuses(_result(timeout=True, truncated=True))
    assert statuses == [Status.TIMEOUT, Status.TRUNCATED]
    obs = build_observation(_result(timeout=True, truncated=True, stdout="0\n1\n2"))
    assert obs.startswith("[TIMEOUT][TRUNCATED]")


def test_final_answer_empty_is_invalid() -> None:
    """final_answerが空: [FINAL_ANSWER_INVALID]."""
    statuses = collect_statuses(_result(final_answer_bool=True, final_answer="   "))
    assert Status.FINAL_ANSWER_INVALID in statuses


def test_final_answer_valid_is_ok() -> None:
    """final_answerに値がある場合はフラグを足さない(終了判定はA7)."""
    statuses = collect_statuses(_result(final_answer_bool=True, final_answer="def f(): ..."))
    assert statuses == [Status.OK]


def test_exception_with_truncated_cooccur() -> None:
    """例外+切詰の同時発生も全列挙."""
    statuses = collect_statuses(_result(error="RuntimeError: x", truncated=True))
    assert statuses == [Status.EXCEPTION, Status.TRUNCATED]


def test_no_code_helper() -> None:
    """NO_CODE補助: ラベルとヒント."""
    obs = observation_no_code()
    assert obs.startswith("[NO_CODE]")
    assert "code block" in obs


def test_value_of_last_expression_is_shown() -> None:
    """print し忘れた最後の式の値も Observation に出す(A-14d)."""
    observation = build_observation(_result(value="{'success': False}"))
    assert "--- value of the last expression ---\n{'success': False}" in observation


def test_no_value_section_without_a_value() -> None:
    assert "value of the last expression" not in build_observation(_result(stdout="hi"))


def test_iteration_note_is_singular_for_one_iteration() -> None:
    assert iteration_note(1, "Submit.") == "[BUDGET] Only 1 iteration remains for this task. Submit."
    assert iteration_note(3, "Submit.").startswith("[BUDGET] Only 3 iterations remain")

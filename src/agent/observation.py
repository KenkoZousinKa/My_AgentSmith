"""LLMに返すObservationの文字列の体裁をExecuteResultから成形するモジュール.

先頭にstatusラベル(全列挙)、1行要約、stdout, stderr / traceback, 任意でnoteを付与する。
巨大なstdout /stderrのトークン切り詰めは履歴の構築側で行う。
"""
from enum import Enum

from src.models.sandbox_base import ExecuteResult


class Status(str, Enum):
    """Observationの先頭に付与するステータスラベル."""

    OK = "OK"
    EXCEPTION = "EXCEPTION"
    TIMEOUT = "TIMEOUT"
    TRUNCATED = "TRUNCATED"
    FINAL_ANSWER_INVALID = "FINAL_ANSWER_INVALID"
    NO_CODE = "NO_CODE"


_SUMMARY: dict[Status, str] = {
    Status.OK: "Executed successfully.",
    Status.EXCEPTION: "An exception was raised during execution.",
    Status.TIMEOUT: "Execution exceeded the time limit.",
    Status.TRUNCATED: "Output was truncated by the sandbox size limit.",
    Status.FINAL_ANSWER_INVALID: "final_answer() was called with an empty value.",
    Status.NO_CODE: "No executable Python code block was found in your message."
}

_NOTE: dict[Status, str] = {
    Status.EXCEPTION: "Fix the error shown above, then re-run.",
    Status.TIMEOUT: "Add a termination condition and avoid unbounded loops.",
    Status.TRUNCATED: "Reduce the amount you print",
    Status.FINAL_ANSWER_INVALID: "Call final_answer() with the actual solution its argument.",
    Status.NO_CODE: "Write exactly one ```python ... ``` code block."
}


def collect_statuses(result: ExecuteResult) -> list[Status]:
    """ExecuteResultのフラグからObservationのステータスラベルを収集する.

    Args:
        result (ExecuteResult): sandbox.run()の実行結果。

    Returns:
        list[Status]: Observationに付与するステータスラベルのリスト。何もなければOK。
    """
    statuses: list[Status] = []
    if result.error is not None:
        statuses.append(Status.EXCEPTION)
    if result.timeout:
        statuses.append(Status.TIMEOUT)
    if result.truncated:
        statuses.append(Status.TRUNCATED)
    if result.final_answer_bool and not (result.final_answer or "").strip():
        statuses.append(Status.FINAL_ANSWER_INVALID)
    if not statuses:
        statuses.append(Status.OK)
    return statuses


def _render_observation(statuses: list[Status], stdout: str, detail: str) -> str:
    """ラベル、stdout、詳細からObservation文字列を構築する.

    Args:
        statuses (list[Status]): Observationに付与するステータスラベルのリスト。
        stdout (str): sandbox.run()の標準出力。(空ならno output)
        detail (str): sandbox.run()の標準エラーまたは例外トレースバック。

    Returns:
        str: 構築したObservation文字列。
    """
    label_prefix = "".join(f"[{status.value}]" for status in statuses)
    summary = " ".join(_SUMMARY[status] for status in statuses)
    lines: list[str] = [f"{label_prefix} {summary}", "--- stdout ---", stdout if stdout else "(no output)"]
    if detail:
        lines.append("--- stderr / traceback ---")
        lines.append(detail)
    notes = [_NOTE[status] for status in statuses if status in _NOTE]
    if notes:
        lines.append("--- note ---")
        lines.append(" ".join(notes))
    return "\n".join(lines)


def build_observation(result: ExecuteResult) -> str:
    """ExecuteResultからLLMへ返すObservation文字列を構築する.

    Args:
        result (ExecuteResult): sandbox.run()の実行結果。

    Returns:
        str: LLMに返すObservation文字列。
            [LABELS] 1行要約 \n\n --- stdout --- \n\n (stderr / traceback) --- \n\n --- note ---
    """
    statuses = collect_statuses(result)
    return _render_observation(statuses, stdout=result.stdout, detail=result.error or result.stderr)


def observation_no_code() -> str:
    """LLMに返すObservation文字列を構築する（コードがない場合）.

    Returns:
        str: LLMに返すObservation文字列。
            [NO_CODE] No executable Python code block was found in your message. \n\n --- note ---
    """
    return _render_observation([Status.NO_CODE], stdout="", detail="")

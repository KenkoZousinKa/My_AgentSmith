"""LLMに返すObservationの文字列の体裁をExecuteResultから成形するモジュール.

先頭にstatusラベル(全列挙)、1行要約、stdout, stderr / traceback, 任意でnoteを付与する。
巨大なstdout /stderrのトークン切り詰めは履歴の構築側で行う。

下記を提供
- Status
- collect_statuses()
- build_observation()
- observation_no_code()
- malformed_code_note()
- submission_rejected_note()
"""
from enum import Enum

from src.models.output import ExecuteResult
from src.agent.extractor.python_extractor import (
    SALVAGE_UNCLOSED_FENCE,
    SALVAGE_UNFENCED,
    SALVAGE_ESCAPED_QUOTES,
    SALVAGE_JSON_WRAPPED,
    SALVAGE_MULTIPLE_BLOCKS,
    SALVAGE_UNMATCHED_CLOSERS
)


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
    Status.TRUNCATED: "Reduce the amount you printi.",
    Status.FINAL_ANSWER_INVALID: "Call final_answer() with the actual solution as its argument.",
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


# [MALFORMED_CODE]の種類ごとのLLMへの説明文
_MALFORMED_NOTES: dict[str, str] = {
    SALVAGE_UNCLOSED_FENCE: (
        "[MALFORMED_CODE] Your ```python block was never closed, so your response was cut off "
        "by the per-turn output limit. I executed everything after the opening fence anyway. "
        "Write shorter turns so the block closes."
    ),
    SALVAGE_UNFENCED: (
        "[MALFORMED_CODE] You wrote bare Python with no ```python fence. I detected it and "
        "executed it anyway, but wrap your code in ```python ... ``` so it is read reliably."
    ),
    SALVAGE_ESCAPED_QUOTES: (
        "[MALFORMED_CODE] You backslash-escaped quotes outside a string literal (for example "
        'if report[\\"success\\"]: instead of if report["success"]:). That is a SyntaxError. '
        "I unescaped the broken lines and ran your code. Write plain Python quotes: this is a "
        "code block, not a JSON string."
    ),
    SALVAGE_JSON_WRAPPED: (
        "[MALFORMED_CODE] Your ```python block contained a JSON object like {\"code\": \"...\"} "
        "instead of Python. I took the string under \"code\" and executed it as Python. Write the "
        "Python statements directly inside the block."
    ),
    SALVAGE_UNMATCHED_CLOSERS: (
        "[MALFORMED_CODE] Your code had more closing brackets than opening ones (a SyntaxError: "
        "unmatched ')'), usually from counting the brackets inside a string literal. I removed only "
        "the extra closing brackets the Python parser reported and ran the code. Brackets inside "
        "quotes do not need closing outside them."
    ),
    SALVAGE_MULTIPLE_BLOCKS: (
        "[NOTE] Your message had several ```python blocks. I joined them in order and executed "
        "them as one program. Prefer exactly one block per turn."
    ),
}


def malformed_code_note(kind: str) -> str:
    """崩れたコードを救済実行したことをLLMへ明示する文を返す.

    崩れたコードブロックを解釈して実行したなら、それをLLMに説明することを明示。
    黙って実行すると、LLMは自分の出力が崩れていたことに気付かず同じ失敗を繰り返す。

    Args:
        kind (str): 救済の種類(python_extractorのSALVAGE_*定数)。

    Returns:
        str: Observationの先頭に付ける説明文。未知の種類なら空文字。
    """
    return _MALFORMED_NOTES.get(kind, "")


def submission_rejected_note(reason: str) -> str:
    """final_answer()の提出を差し戻したこととその理由をLLMへ伝える文を返す.

    差し戻した事実を伝えないとLLMは提出が受理されたと思い同じ提出を繰り返す、または止まる。

    Args:
        reason (str): 提出が受理されなかった理由。
            TaskProfile.submission_rejection()またはsolution_verifier()の返す文字列。

    Returns:
        str: Observationの末尾に付ける説明文。
    """
    return f"--- submission rejected ---\n{reason}\nFix it and call final_answer() again."

"""Checks before the result is sent and the final_answer function."""


from typing import Any


class FinalAnswer(BaseException):
    """Task complete signal.

    BaseException so generated code wrapping its work
    in try/except Exception cannot eat it.
    """
    def __init__(self, value: Any) -> None:
        """Init self with base exception inheritance."""
        super().__init__(value)
        self.value = value


def _truncate(text: str, limit: int) -> str:
    """Cap text, stating what was dropped.

    The marker matters: without it the LLM treats a cut-off result as
    complete and reasons from a false premise.
    """
    if len(text) <= limit:
        return text
    dropped = len(text) - limit
    return (
        f"{text[:limit]}\n[output truncated: {dropped} of {len(text)} "
        f"characters omitted; narrow your request to see the rest]"
    )

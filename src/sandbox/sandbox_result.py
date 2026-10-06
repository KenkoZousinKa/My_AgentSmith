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

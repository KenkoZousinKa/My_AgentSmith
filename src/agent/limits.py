"""反復回数 / トークン / 時間 などのハード制限を監視するモジュール.

ループの先頭のガードで反復数、累積入出力トークン、経過時間、1反復のマージンを判定。
超過、または超過しそうならStopReasonを返しOrchestraterにループを終了させる。
各LLM呼び出しのあとはrecord_usageで累積カウンタを更新するだけで判定はしない。
トークン制限は1タスクの全反復で累積(reasoning込)、時間経過はSIGKILLで全損するので事前ガード
max_tokensクランプ用にremaining_output_tokensを返す。
"""
import time
from enum import Enum
from collections.abc import Callable

from src.config.settings import Limits


class StopReason(str, Enum):
    """ハード制限超過によるループ終了理由.

    SolutionOutputのerrorフィールドに格納 + 分析用。
    """
    MAX_ITERATIONS = "MAX_ITERATIONS"
    MAX_INPUT_TOKENS = "MAX_INPUT_TOKENS"
    MAX_OUTPUT_TOKENS = "MAX_OUTPUT_TOKENS"
    TIME_LIMIT = "TIME_LIMIT"


class LimitTracker:
    """1タスク分のハード制限カウンタを保持し、ループの先頭で判定する。

    Attributes:
        iterations (int): 現在の反復回数.
        total_input_tokens (int): 現在の累積入力トークン数.
        total_output_tokens (int): 現在の累積出力トークン数
    """

    def __init__(self, limits: Limits, now: Callable[[], float] = time.monotonic) -> None:
        """トラッカーを初期化し、開始時刻を記録する.

        Args:
            limits (Limits): 注入するハード制限値.
            now (Callable[[], float], optional): 現在時刻を返す関数. デフォルトはtime.monotonic.
        """
        self._limits = limits
        self._now = now
        self._start_time = now()
        self.iterations = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def elapsed_seconds(self) -> float:
        """タスク開始からの経過時間を秒単位で返す.

        Returns:
            float: 経過時間（秒）.
        """
        return self._now() - self._start_time

    def start_iteration(self) -> StopReason | None:
        """次の生成の前にループの先頭で呼び出し、ハード制限を判定する.

        反復数、累積トークンは既に制限異常かどうか
        時間は経過時間 + time_margin_secondsがtotal_time_limit_secondsを超えるかどうかで判定する。
        (時間は1反復のmarginを考慮して、超過しそうなら止める)
        続行時は反復カウンタを1進める。
        判定順は
        iterations > total_input_tokens > total_output_tokens > elapsed_secondsの順で、最初に超過したものを返す。

        Returns:
            StopReason | None: 超過していればStopReasonを返す。超過していなければNoneを返す。
        """
        if self.iterations >= self._limits.max_iterations:
            return StopReason.MAX_ITERATIONS
        if self.total_input_tokens >= self._limits.max_input_tokens:
            return StopReason.MAX_INPUT_TOKENS
        if self.total_output_tokens >= self._limits.max_output_tokens:
            return StopReason.MAX_OUTPUT_TOKENS
        if self.elapsed_seconds() + self._limits.time_margin_sec >= self._limits.total_time_sec:
            return StopReason.TIME_LIMIT
        self.iterations += 1
        return None

    def record_usage(self, input_tokens: int, output_tokens: int) -> None:
        """LLM呼び出し後に累積トークン数を更新する.

        Args:
            input_tokens (int): 直前のLLM呼び出しで使用した入力トークン数.
            output_tokens (int): 直前のLLM呼び出しで使用した出力トークン数.
        """
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens

    def remaining_output_tokens(self) -> int:
        """この反復で使用可能な残り出力トークン数を返す.

        orchestraterがmax_tokensをmin(設定上限、この値)にクランプするために使用する。
        累積出力がmax_output_tokensを超えないようにするための値。
        負にならないように0で下限を設定。

        Returns:
            int: 残り出力トークン数.
        """
        return max(0, self._limits.max_output_tokens - self.total_output_tokens)

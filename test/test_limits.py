"""ハード制限監視(limits.py)のテスト."""
from src.agent.limits import LimitTracker, StopReason
from src.config.settings import Limits


class _Clock:
    """テスト用の差し替え時計。t を書き換えて時間を進める."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _limits(**kw: object) -> Limits:
    """小さめの制限値を作るヘルパ(必要分だけ上書き)."""
    base: dict[str, object] = dict(
        max_iterations=3, max_input_tokens=100, max_output_tokens=50,
        total_time_sec=120.0, time_margin_sec=10.0,
    )
    base.update(kw)
    return Limits(**base)  # type: ignore[arg-type]


def test_iterations_allows_exactly_max() -> None:
    """max_iterations=3 なら3回続行し4回目で MAX_ITERATIONS."""
    tracker = LimitTracker(_limits(max_iterations=3), now=_Clock())
    assert tracker.start_iteration() is None
    assert tracker.start_iteration() is None
    assert tracker.start_iteration() is None
    assert tracker.start_iteration() is StopReason.MAX_ITERATIONS
    assert tracker.iterations == 3


def test_input_tokens_stop() -> None:
    """累積入力が制限以上で MAX_INPUT_TOKENS."""
    tracker = LimitTracker(_limits(max_input_tokens=100), now=_Clock())
    assert tracker.start_iteration() is None
    tracker.record_usage(input_tokens=100, output_tokens=0)
    assert tracker.start_iteration() is StopReason.MAX_INPUT_TOKENS


def test_output_tokens_stop() -> None:
    """累積出力が制限以上で MAX_OUTPUT_TOKENS."""
    tracker = LimitTracker(_limits(max_output_tokens=50), now=_Clock())
    assert tracker.start_iteration() is None
    tracker.record_usage(input_tokens=0, output_tokens=50)
    assert tracker.start_iteration() is StopReason.MAX_OUTPUT_TOKENS


def test_time_limit_preempts_with_margin() -> None:
    """経過+margin が total 以上で TIME_LIMIT(1反復マージンの事前停止)."""
    clock = _Clock()
    tracker = LimitTracker(_limits(total_time_sec=120.0, time_margin_sec=10.0), now=clock)
    clock.t = 109.0  # 109+10=119 < 120 -> まだ続行
    assert tracker.start_iteration() is None
    clock.t = 111.0  # 111+10=121 >= 120 -> 停止
    assert tracker.start_iteration() is StopReason.TIME_LIMIT


def test_priority_iterations_first() -> None:
    """複数同時超過時は判定順(iterations が最優先)で1つ返す."""
    tracker = LimitTracker(_limits(max_iterations=1, max_input_tokens=1), now=_Clock())
    assert tracker.start_iteration() is None  # iterations 0->1
    tracker.record_usage(input_tokens=10, output_tokens=0)  # 入力も超過させる
    assert tracker.start_iteration() is StopReason.MAX_ITERATIONS  # iterations を先に返す


def test_remaining_output_tokens_clamp() -> None:
    """残り出力予算 = max_output_tokens - 累積、下限0."""
    tracker = LimitTracker(_limits(max_output_tokens=50), now=_Clock())
    assert tracker.remaining_output_tokens() == 50
    tracker.record_usage(input_tokens=0, output_tokens=30)
    assert tracker.remaining_output_tokens() == 20
    tracker.record_usage(input_tokens=0, output_tokens=40)  # 累積70 > 50
    assert tracker.remaining_output_tokens() == 0


def test_record_usage_accumulates() -> None:
    """record_usage が累積する."""
    tracker = LimitTracker(_limits(), now=_Clock())
    tracker.record_usage(input_tokens=10, output_tokens=5)
    tracker.record_usage(input_tokens=20, output_tokens=7)
    assert tracker.total_input_tokens == 30
    assert tracker.total_output_tokens == 12

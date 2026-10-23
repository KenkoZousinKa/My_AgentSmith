"""key_manager の複数キー解決 resolve_api_keys のテスト(環境変数はmonkeypatchで注入)."""
import pytest

from src.agent.llm.key_manager import resolve_api_keys

_BASE = "FAKE_API_KEY"


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    """FAKE_API_KEY系の環境変数をすべて消して既知の状態にする."""
    for suffix in ("", "_2", "_3", "_4", "_5"):
        monkeypatch.delenv(f"{_BASE}{suffix}", raising=False)


def test_single_base_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """基準名のみ設定 -> 1本のリスト."""
    _clear(monkeypatch)
    monkeypatch.setenv(_BASE, "k1")
    assert resolve_api_keys(_BASE) == ["k1"]


def test_numbered_keys_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """基準名 + _2 + _3 -> 宣言順のリスト."""
    _clear(monkeypatch)
    monkeypatch.setenv(_BASE, "k1")
    monkeypatch.setenv(f"{_BASE}_2", "k2")
    monkeypatch.setenv(f"{_BASE}_3", "k3")
    assert resolve_api_keys(_BASE) == ["k1", "k2", "k3"]


def test_stops_at_first_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    """連番が途切れたらそこで打ち切る(_2欠けなら_3以降は無視)."""
    _clear(monkeypatch)
    monkeypatch.setenv(_BASE, "k1")
    monkeypatch.setenv(f"{_BASE}_3", "k3")  # _2 が無い
    assert resolve_api_keys(_BASE) == ["k1"]


def test_base_missing_but_numbered_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """基準名が無くても _2 があれば収集する(基準名欠けを許容)."""
    _clear(monkeypatch)
    monkeypatch.setenv(f"{_BASE}_2", "k2")
    assert resolve_api_keys(_BASE) == ["k2"]


def test_whitespace_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    """前後の空白は除去する."""
    _clear(monkeypatch)
    monkeypatch.setenv(_BASE, "  k1  ")
    assert resolve_api_keys(_BASE) == ["k1"]


def test_duplicate_keys_removed_preserving_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """同一キーの重複は順序を保って除去する."""
    _clear(monkeypatch)
    monkeypatch.setenv(_BASE, "k1")
    monkeypatch.setenv(f"{_BASE}_2", "k1")  # 重複
    monkeypatch.setenv(f"{_BASE}_3", "k2")
    assert resolve_api_keys(_BASE) == ["k1", "k2"]


def test_no_keys_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """1本も無ければ空リスト(例外にしない)."""
    _clear(monkeypatch)
    assert resolve_api_keys(_BASE) == []

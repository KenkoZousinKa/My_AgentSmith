"""プロンプト生成(template.build_system_prompt)と各TaskProfileの単体テスト."""
import pytest

from src.agent.prompt.task_profile.mbpp_profile import MBPPProfile
from src.agent.prompt.task_profile.swebench_profile import SWEBenchProfile
from src.agent.prompt.template import build_system_prompt
from src.models.sandbox_base import ExecuteResult

_FAKE_MANUAL = "## Tools\nfinal_answer(value): submit your verified answer."


class _FakeSandbox:
    """テスト用サンドボックス(SandboxBase Protocolを構造的に満たす)."""

    def run(self, code: str) -> ExecuteResult:
        """ダミー実行結果を返す(本テストでは未使用)."""
        return ExecuteResult(
            stdout="",
            stderr="",
            error=None,
            value=None,
            timeout=False,
            truncated=False,
            final_answer_bool=False,
            final_answer=None,
        )

    def manual(self) -> str:
        """固定のマニュアル文字列を返す."""
        return _FAKE_MANUAL


@pytest.fixture
def sandbox() -> _FakeSandbox:
    """テスト用サンドボックスを返す."""
    return _FakeSandbox()


def test_mbpp_prompt_has_required_sections(sandbox: _FakeSandbox) -> None:
    """MBPPのsystem promptに必須節が含まれる."""
    prompt = build_system_prompt(MBPPProfile(), sandbox)
    assert "```python" in prompt          # コード形式
    assert "<end_code>" in prompt         # ターン終端
    assert "final_answer" in prompt       # 提出方法
    assert "SELF-CONTAINED" in prompt     # 自己完結規約(D23)
    assert _FAKE_MANUAL in prompt         # manual() 差し込み
    assert "MBPP" in prompt               # 種別の作法


def test_swebench_prompt_specifies_patch(sandbox: _FakeSandbox) -> None:
    """SWEのsystem promptはfinal_answer=diff/patchを指示する."""
    prompt = build_system_prompt(SWEBenchProfile(), sandbox)
    assert "```python" in prompt
    assert _FAKE_MANUAL in prompt
    assert "patch" in prompt or "diff" in prompt


def test_mbpp_final_answer_spec_is_code() -> None:
    """MBPPのfinal_answer仕様はソースコード."""
    assert "source code" in MBPPProfile().final_answer_specification()


def test_swebench_final_answer_spec_is_patch() -> None:
    """SWEのfinal_answer仕様はdiff/patch(旧 'Python code snippet' バグの回帰防止)."""
    spec = SWEBenchProfile().final_answer_specification()
    assert "diff" in spec or "patch" in spec


def test_few_shot_shows_loop_format() -> None:
    """few-shotはループ形式(Thought/コード/Observation/final_answer)を示す."""
    example = MBPPProfile().few_shot_example()
    assert "Thought:" in example
    assert "```python" in example
    assert "Observation:" in example
    assert "final_answer" in example


def test_profile_names() -> None:
    """name 属性が正しい."""
    assert MBPPProfile().name == "mbpp"
    assert SWEBenchProfile().name == "swebench"

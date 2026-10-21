"""プロンプト生成(template.build_system_prompt)と各TaskProfileの単体テスト."""
import pytest

from src.agent.extractor.python_extractor import PythonCodeExtractor
from src.agent.prompt.task_profile.mbpp_profile import MBPPProfile
from src.agent.prompt.task_profile.swebench_profile import SWEBenchProfile
from src.agent.prompt.task_profile.task_profile import DEFAULT_FORMAT_RULES, TaskProfile
from src.agent.prompt.template import build_system_prompt
from src.models.output import ExecuteResult
from src.models.sandbox_base import SandboxBase

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


def test_mbpp_few_shot_code_is_not_indented() -> None:
    """few-shotのコードが行頭インデント無しで、抽出→compileできる(IndentationError回帰防止)."""
    example = MBPPProfile().few_shot_example()
    code = PythonCodeExtractor().extract(example)
    assert code is not None
    assert code == code.lstrip(), "抽出コードが行頭インデントを持つ（手本が字下げされている）"
    compile(code, "<few_shot>", "exec")  # IndentationError/SyntaxError が出ないこと


def _output_format_section(prompt: str) -> str:
    """system promptから ## Output Format 節の本文(見出しの次の行から、次の見出しの手前まで)を取り出す."""
    after_heading = prompt.split("## Output Format (follow exactly)\n", 1)[1]
    return after_heading.split("\n\n## ", 1)[0]


def test_default_format_rules_fill_the_output_format_section(sandbox: _FakeSandbox) -> None:
    """既定の形式ルールが ## Output Format 節にそのまま入る(MBPPは既定のまま。SWE-benchはA-22で上書き)."""
    prompt = build_system_prompt(MBPPProfile(), sandbox)
    assert _output_format_section(prompt) == DEFAULT_FORMAT_RULES
    assert prompt.count(DEFAULT_FORMAT_RULES) == 1


def test_swebench_format_rules_replace_the_default(sandbox: _FakeSandbox) -> None:
    """SWE-benchは独自の形式ルール(ツールは文字列を返すのでprintする、など)が入り、既定のルールは入らない."""
    prompt = build_system_prompt(SWEBenchProfile(), sandbox)
    assert _output_format_section(prompt) == SWEBenchProfile().format_rules()
    assert DEFAULT_FORMAT_RULES not in prompt


class _TerseFormatProfile(MBPPProfile):
    """形式ルールだけを上書きしたプロファイル(フックの差し替えが効くかを見る)."""

    def format_rules(self) -> str:
        """独自の形式ルールを返す."""
        return "- Reply with ONE ```python block, then <end_code>. {braces stay as-is}"


def test_profile_format_rules_override_replaces_the_default(sandbox: _FakeSandbox) -> None:
    """プロファイルが format_rules() を上書きすると、既定のルールの代わりにそれが入る.

    ルールの文中の { } は str.format() に解釈されずそのまま残る(差し込む値は再解釈されない)。
    """
    prompt = build_system_prompt(_TerseFormatProfile(), sandbox)
    assert _output_format_section(prompt) == _TerseFormatProfile().format_rules()
    assert DEFAULT_FORMAT_RULES not in prompt
    assert "MBPP" in prompt  # 他の節(タスクの作法)は親のまま


class _MinimalProfile(TaskProfile):
    """抽象メソッドだけを実装したプロファイル(基底クラスの既定のフックを見る)."""

    def task_instructions(self) -> str:
        """固定の指示を返す."""
        return "instructions"

    def final_answer_specification(self) -> str:
        """固定の提出仕様を返す."""
        return "specification"

    def few_shot_example(self) -> str:
        """固定の例を返す."""
        return "example"

    def manual(self, sandbox: SandboxBase) -> str:
        """サンドボックスのマニュアルをそのまま返す."""
        return sandbox.manual()


def test_default_submission_hooks(sandbox: _FakeSandbox) -> None:
    """既定のフック: 前後の空白を落とし、空の提出だけを拒否し、打ち切り時は何も回収しない."""
    profile = _MinimalProfile()

    assert profile.sanitize_submission("\n  def f():\n    return 1\n\n") == "def f():\n    return 1"

    assert profile.submission_rejection(profile.sanitize_submission("def f():\n    return 1")) is None
    for empty in ("", "   \n\t"):
        reason = profile.submission_rejection(profile.sanitize_submission(empty))
        assert reason is not None
        assert "empty" in reason

    assert profile.is_fallback_candidate("def f():\n    return 1") is False
    assert profile.fallback_solution(sandbox) == ""

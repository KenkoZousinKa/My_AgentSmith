"""MockSandbox(sandbox/mock.py)のテスト."""
from src.sandbox.mock import MockSandbox


def test_print_captured_as_stdout() -> None:
    """print 出力が stdout に捕捉され、エラーは無い."""
    result = MockSandbox().run("print('hello')")
    assert result.stdout.strip() == "hello"
    assert result.error is None
    assert result.final_answer_bool is False


def test_namespace_is_stateful_across_runs() -> None:
    """run をまたいで名前空間が永続する(D23 stateful)."""
    sandbox = MockSandbox()
    sandbox.run("x = 41")
    result = sandbox.run("print(x + 1)")
    assert result.stdout.strip() == "42"


def test_final_answer_captured() -> None:
    """final_answer 呼び出しが ExecuteResult に反映される."""
    result = MockSandbox().run("final_answer('def f():\\n    return 1')")
    assert result.final_answer_bool is True
    assert result.final_answer == "def f():\n    return 1"
    assert result.error is None


def test_exception_goes_to_error_without_raising() -> None:
    """実行時例外は error に入り、run 自体は投げない."""
    result = MockSandbox().run("raise ValueError('boom')")
    assert result.error is not None
    assert "ValueError" in result.error
    assert result.final_answer_bool is False


def test_import_stdlib_works() -> None:
    """標準ライブラリの import が可能(mockは制限しない)."""
    result = MockSandbox().run("import math\nprint(math.isclose(1.0, 1.0))")
    assert result.stdout.strip() == "True"


def test_manual_mentions_final_answer() -> None:
    """manual() が final_answer に言及する."""
    assert "final_answer" in MockSandbox().manual()

"""cli.py のタスク文の整形(format_swebench_task)のテスト."""
from src.agent.cli import format_swebench_task
from src.models.input import SWEBenchTaskInput


def _task(**overrides: str) -> SWEBenchTaskInput:
    """テスト用のSWE-benchタスクを作る(指定したフィールドだけ差し替える)."""
    fields = {
        "instance_id": "calc__calc-1",
        "problem_statement": "  divide() multiplies instead of dividing.\n",
        "docker_image": "example/image:latest",
        "eval_script": "pytest",
        "hints_text": "",
        "repo": "calc/calc",
    }
    fields.update(overrides)
    return SWEBenchTaskInput(**fields)


def test_task_message_has_repository_and_issue() -> None:
    """リポジトリ名・場所(/testbed)・issueの本文(前後の空白を落とす)を含む。ヒントが無ければ節を作らない."""
    message = format_swebench_task(_task())
    assert message.startswith("Repository: calc/calc (checked out at /testbed)")
    assert "Issue:\ndivide() multiplies instead of dividing." in message
    assert "Hints" not in message


def test_instance_id_is_used_when_repo_is_missing() -> None:
    """repoは任意の欄なので、空ならinstance_idで代用する."""
    assert format_swebench_task(_task(repo="")).startswith("Repository: calc__calc-1 ")


def test_long_hints_are_truncated_and_marked() -> None:
    """長いヒントは4,000字で切り、切ったことを示す(毎反復の入力を圧迫しないため)."""
    message = format_swebench_task(_task(hints_text="h" * 5000))
    hints = message.split("Hints from the issue discussion:\n", 1)[1]
    assert hints == "h" * 4000 + "\n...[hints truncated]"


def test_short_hints_are_kept_as_is() -> None:
    """短いヒントはそのまま渡す."""
    message = format_swebench_task(_task(hints_text="Look at ops.py"))
    assert message.endswith("Hints from the issue discussion:\nLook at ops.py")

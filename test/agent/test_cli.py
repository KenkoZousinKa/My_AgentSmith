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




# ===================== A-20: 異常時も solution.json を必ず書く =====================
# 実際の入口(run_mbpp_agent / run_swe_agent / python -m agent_mbpp)を、LLMを呼ばずに失敗させる。

import json  # noqa: E402
import os  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

from src.agent.cli import run_mbpp_agent, run_swe_agent  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _mbpp_task_file(tmp_path: Path) -> Path:
    """MBPPのタスクファイルを書く."""
    path = tmp_path / "mbpp_task.json"
    path.write_text(json.dumps({
        "task_id": 11,
        "task_definition": "Write a function to add two numbers.",
        "function_definition": "def add(a, b):",
        "test_list": ["assert add(1, 2) == 3"],
    }), encoding="utf-8")
    return path


def _swe_task_file(tmp_path: Path) -> Path:
    """SWE-benchのタスクファイルを書く."""
    path = tmp_path / "swe_task.json"
    path.write_text(_task().model_dump_json(), encoding="utf-8")
    return path


def _read_solution(path: Path) -> dict[str, object]:
    """書き出されたsolution.jsonを読む."""
    solution: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return solution


def test_unknown_model_writes_failed_solution(tmp_path: Path) -> None:
    """providers.jsonにないモデル(order_providersのValueError)でも、失敗のsolution.jsonを書いて正常終了する."""
    output = tmp_path / "solution.json"
    run_mbpp_agent(str(_mbpp_task_file(tmp_path)), str(output), model_name="no-such/model")
    solution = _read_solution(output)
    assert solution["task_id"] == "11"
    assert solution["benchmark"] == "mbpp"
    assert solution["success"] is False
    assert solution["solution"] == ""
    assert str(solution["error"]).startswith("AGENT_CRASH: ValueError: ")


def test_unknown_transport_writes_failed_solution(tmp_path: Path) -> None:
    """未知のtransportでも、失敗のsolution.jsonを書いて正常終了する."""
    output = tmp_path / "solution.json"
    run_mbpp_agent(str(_mbpp_task_file(tmp_path)), str(output), transport="carrier-pigeon")
    assert str(_read_solution(output)["error"]).startswith("AGENT_CRASH: ValueError: Unknown transport: carrier-pigeon")


def test_mcp_server_that_dies_at_startup_writes_failed_solution(tmp_path: Path) -> None:
    """MCPServerが起動直後に落ちても(本物のサブプロセス)、失敗のsolution.jsonを書いて正常終了する."""
    output = tmp_path / "solution.json"
    command = f"{sys.executable} -c 'import sys; sys.exit(3)'"
    run_mbpp_agent(str(_mbpp_task_file(tmp_path)), str(output), command=command)
    assert str(_read_solution(output)["error"]).startswith("AGENT_CRASH: MCPConnectionError: ")


def test_broken_task_file_writes_failed_solution_into_a_new_directory(tmp_path: Path) -> None:
    """タスクファイルが壊れていても、task_id=unknown で書く。出力先のディレクトリが無ければ作る."""
    task_file = tmp_path / "broken.json"
    task_file.write_text("{not json", encoding="utf-8")
    output = tmp_path / "not" / "yet" / "solution.json"
    run_mbpp_agent(str(task_file), str(output))
    solution = _read_solution(output)
    assert solution["task_id"] == "unknown"
    assert str(solution["error"]).startswith("AGENT_CRASH: ValidationError: ")


def test_swe_unknown_model_writes_failed_solution(tmp_path: Path) -> None:
    """SWE-benchも同じ: instance_idとbenchmark=swebenchで失敗を書く(Dockerは起動しない)."""
    output = tmp_path / "solution.json"
    run_swe_agent(str(_swe_task_file(tmp_path)), str(output), model_name="no-such/model")
    solution = _read_solution(output)
    assert solution["task_id"] == "calc__calc-1"
    assert solution["benchmark"] == "swebench"
    assert solution["success"] is False
    assert str(solution["error"]).startswith("AGENT_CRASH: ValueError: ")


# initializeに答えず、SIGTERMを無視するMCPServerの偽物。
# 標準入力が閉じたら(エージェントのプロセスが終わったら)自分も終わる。
_SILENT_SERVER = """
import pathlib, signal, sys
signal.signal(signal.SIGTERM, signal.SIG_IGN)
pathlib.Path(sys.argv[1]).touch()
for _line in sys.stdin:
    pass
"""


def test_sigterm_from_the_grader_writes_solution_and_exits_143(tmp_path: Path) -> None:
    """採点側と同じ止め方(プロセスグループへのSIGTERM)で、solution.jsonを書いてから143で終わる.

    moulinetteの run-agent は start_new_session=True で起動し、時間切れで os.killpg(SIGTERM) を送る。
    エージェントがMCPServerの応答を待っている(readlineで止まっている)ところに送る。
    """
    server_script = tmp_path / "silent_server.py"
    server_script.write_text(_SILENT_SERVER, encoding="utf-8")
    started_marker = tmp_path / "server_started"
    output = tmp_path / "solution.json"
    process = subprocess.Popen(
        [sys.executable, "-m", "agent_mbpp",
         "--task-file", str(_mbpp_task_file(tmp_path)),
         "--output", str(output),
         "--command", f"{sys.executable} {server_script} {started_marker}"],
        cwd=_REPO_ROOT,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 30
        while not started_marker.exists():
            assert process.poll() is None, "エージェントがSIGTERMの前に終わった"
            assert time.monotonic() < deadline, "MCPServerの偽物が起動しない"
            time.sleep(0.05)
        time.sleep(0.3)  # initializeを送って応答待ちに入るまで
        sent_at = time.monotonic()
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        return_code = process.wait(timeout=10)  # 採点側はSIGTERMの10秒後にSIGKILLする
    finally:
        if process.poll() is None:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            process.wait()
    assert return_code == 143
    assert time.monotonic() - sent_at < 10
    solution = _read_solution(output)
    assert solution["task_id"] == "11"
    assert solution["success"] is False
    assert solution["error"] == "INTERRUPTED: _Terminated"

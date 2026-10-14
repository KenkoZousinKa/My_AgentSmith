"""SWE-bench 用のエージェントのモック（LLM の代わりに、決まったコードを順に流す）.

task.json → MCP サーバー起動（stdio, env 付き）→ Sandbox に tools を渡す → コードを実行 → solution.json

使い方（リポジトリの直下で）:
    # Docker で（moulinette の dump で作った task.json の docker_image を使う）
    uv run python -m tests.mock.mock_agent_swebench --task-file task.json --output solution.json
    # HTTP で（127.0.0.1:8000 が空いていれば、サーバーを --transport http で自動起動する）
    uv run python -m tests.mock.mock_agent_swebench --http --task-file task.json --output solution.json
    # Docker なしで（ローカルのフォルダを /testbed の代わりにする）
    uv run python -m tests.mock.mock_agent_swebench --task-file tests/mock/swebench_task_dummy.json \
        --output /tmp/solution.json --local /path/to/git/repo
    # 本番と同じく、moulinette の run-agent（時間切れでプロセスグループごと kill）から呼ぶ
    uv run --project ../pdf/moulinette moulinette_eval run-agent 900 \
        "uv run python -m tests.mock.mock_agent_swebench --task-file task.json --output solution.json"
"""

import sys
import time
import shlex
import argparse
from pathlib import Path
from typing import Any, Callable

from src.models.input import SWEBenchTaskInput
from src.models.output import SolutionOutput, StepMetrics
from src.mcp_core.client.client import MCPClient
from src.mcp_core.client.stdio import StdioClientTransport
from src.mcp_core.client.http import DEFAULT_URL, HttpClientTransport
from src.mcp_core.client.mcp_tool_function import MCPToolFunction
from src.sandbox.sandbox_main import Sandbox

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER = REPO_ROOT / "mcp_tools_swebench.py"
SEPARATOR = "# ---"  # --steps ファイルで、スニペットを区切る行


def load_steps(path: str | None, tool_names: set[str]) -> list[str]:
    """スニペット（LLM が書いたつもりのコード、1要素 = 1ステップ）のリストを返す."""
    if path is None:
        last = ("final_answer(get_patch())" if "get_patch" in tool_names else
                'out = run_command(command="git -c core.fileMode=false diff")\n'
                'final_answer(out.split("--- stdout ---\\n", 1)[1].rsplit("\\n--- stderr ---", 1)[0])')
        # ↑ get_patch がまだ無い間は run_command で代用。見出し（exit_code など）を切り落として diff だけにする
        return [
            'print(run_command(command="pwd && ls | head -20"))',
            'print(run_command(command="git status --short | head -20"))',
            last,
        ]
    text = Path(path).read_text(encoding="utf-8")
    return [s.strip() for s in text.split(SEPARATOR) if s.strip()]


def server_env(task: SWEBenchTaskInput, local: str | None) -> dict[str, str]:
    """MCP サーバーに渡す環境変数を作る."""
    if local is not None:
        return {"SWE_DOCKER_IMAGE": "", "TESTBED_PATH": str(Path(local).resolve())}
        # ↑ 空文字は False 扱い → LocalExecutor（親の環境に SWE_DOCKER_IMAGE があっても上書きする）
    return {"SWE_DOCKER_IMAGE": task.docker_image, "TESTBED_PATH": "/testbed"}


def main() -> int:
    parser = argparse.ArgumentParser(description="SWE-bench mock agent")
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--local", metavar="DIR", help="Docker を使わず、DIR を testbed にする")
    parser.add_argument("--http", action="store_true", help="stdio ではなく HTTP でサーバーとつなぐ")
    parser.add_argument("--steps", metavar="FILE", help=f"'{SEPARATOR}' 区切りのスニペット集")
    parser.add_argument("--model-name", help="受け取るだけ（quickstart と同じ形で呼べるように）")
    parser.add_argument("--provider-url", help="受け取るだけ")
    args = parser.parse_args()

    started = time.monotonic()
    task = SWEBenchTaskInput.model_validate_json(Path(args.task_file).read_text(encoding="utf-8"))
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(SERVER))}"
    # ↑ "python" ではなく今の Python（uv の venv）を使う。絶対パスなので、どこから起動しても src を import できる

    env = server_env(task, args.local)
    transport: StdioClientTransport | HttpClientTransport
    if args.http:
        transport = HttpClientTransport(DEFAULT_URL, command=f"{command} --transport http",
                                        env=env, start_timeout=610)
        # ↑ docker.start() が終わるまで待ち受けが始まらないので、その上限（600 秒）より少し長く待つ
    else:
        transport = StdioClientTransport(command, env=env)
    client = MCPClient(transport)
    sandbox: Sandbox | None = None
    steps: list[StepMetrics] = []
    answer: str | None = None
    error: str | None = None
    try:
        client.connect()  # Docker のときは、ここでコンテナの起動まで待つ
        tools: dict[str, Callable[..., Any]] = {
            t.name: MCPToolFunction(client, t) for t in client.list_tools()}
        sandbox = Sandbox(tools=tools)
        # ↑ client はエージェント（このファイル）が持ち、Sandbox には tools だけ渡す
        #   → Sandbox.close() は client を閉じない。閉じるのは下の finally
        system_prompt = f"{task.problem_statement}\n\n{sandbox.manual()}"

        for i, code in enumerate(load_steps(args.steps, set(tools)), start=1):
            result = sandbox.run(code)
            output = result.error or result.stdout + result.stderr
            print(f"--- step {i} ---\n{code}\n>>>\n{output}", file=sys.stderr)
            steps.append(StepMetrics(step=i, input_tokens=0, output_tokens=0, request_time_ms=0.0,
                                     sandbox_input=code, sandbox_output=output))
            if result.final_answer_bool:
                answer = result.final_answer
                break
        else:
            error = "final_answer が呼ばれませんでした"
    except Exception as e:
        system_prompt = ""
        error = f"{type(e).__name__}: {e}"
    finally:
        if sandbox is not None:
            sandbox.close()  # 先にワーカーを止める（fork でサーバーへのパイプを持っているため）
        client.close()       # EOF → サーバーの finally → コンテナ削除

    solution = SolutionOutput(
        task_id=task.instance_id, benchmark="swebench",
        success=bool(answer and answer.strip()), solution=answer or "",
        iterations=len(steps), total_requests=len(steps),
        total_input_tokens=0, total_output_tokens=0,
        total_time_seconds=time.monotonic() - started,
        steps=steps, system_prompt=system_prompt, error=error,
    )
    Path(args.output).write_text(solution.model_dump_json(indent=2), encoding="utf-8")
    print(f"wrote {args.output} (success={solution.success}, error={error})", file=sys.stderr)
    return 0 if error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())

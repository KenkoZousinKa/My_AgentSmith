"""SWE-bench用のエントリーポイントモジュール.

`uv run python3 -m agent_swebench
--task-file ../cache/swebench_task.json
--output ../cache/swebench_solution.json
--mode-name "model/name" --provider-url "http://provider.api/v1"`
"""
import fire


def agent_swebench(task_file: str, output: str, model_name: str, provider_url, **extra_args):
    """SWE-bench用のエントリーポイント関数."""
    if extra_args:
        print(f"Extra arguments: {extra_args}")


if __name__ == "__main__":
    fire.Fire(agent_swebench())

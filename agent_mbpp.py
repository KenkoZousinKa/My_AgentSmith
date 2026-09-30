"""MBPP用のエントリーポイントモジュール.

`uv run python3 -m agent_mbpp
--task-file ../cache/mbpp_task.json 
--output ../cache/mbpp_solution.json
--mode-name "model/name" --provider-url "http://provider.api/v1"`
"""
import fire


def agent_mbpp(task_file: str, output: str, model_name: str, provider_url, **extra_args):
    """MBPP用のエントリーポイント関数."""
    if extra_args:
        print(f"Extra arguments: {extra_args}")

if __name__ == "__main__":
    fire.Fire(agent_mbpp())
"""MBPP用のエントリーポイントモジュール.

`uv run python3 -m agent_mbpp
--task-file ../cache/mbpp_task.json
--output ../cache/mbpp_solution.json
--model-name "model/name" --provider-url "http://provider.api/v1"`
"""
import fire

from src.agent.cli import run_mbpp_agent


def agent_mbpp(
    task_file: str,
    output: str,
    model_name: str | None = None,
    provider_url: str | None = None,
    **extra_args: object
) -> None:
    """MBPP用のエントリーポイント関数.

    Args:
        task_file (str): MBPPタスクファイルのパス
        output (str): SolutionOutputを書き出すJSONファイルのパス
        model_name (str): 使用するLLMモデル名。Noneなら設定ファイルのデフォルトを使用
        provider_url (str): 使用するLLMプロバイダのURL。Noneなら設定ファイルのデフォルトを使用
        **extra_args: object: fireが解釈できなかった余分な引数。存在する場合はエラーを発生させる。
    """
    if extra_args:
        raise SystemExit(f"Unknown arguments: {list(extra_args)}")
    run_mbpp_agent(
        task_file_path=task_file,
        output_file_path=output,
        model_name=model_name,
        provider_url=provider_url
    )


if __name__ == "__main__":
    fire.Fire(agent_mbpp)

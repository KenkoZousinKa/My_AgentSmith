"""SWE-bench用のエントリーポイントモジュール."""
import fire



def agent_swebench(task_file: str, output: str, model_name: str, provider_url, **extra_args):
    """SWE-bench用のエントリーポイント関数."""
    if extra_args:
        print(f"Extra arguments: {extra_args}")

if __name__ == "__main__":
    fire.Fire(agent_swebench())
"""MBPP エージェントの組み立て、実行を担う配線.

タスクファイル読み込み -> 設定 / プロバイダ解決 ->
Provider / Sandbox / Orchestrator 構築 ->
実行 -> SolutionOutput 書き出し
fireはagent_mbpp.py / agent_swebench.py から呼ばれ、
検証済みの引数だけを受け取る関数郡

- [ ] BaseAgentCliArgsモデルを作成して検証を拡充
"""
from pathlib import Path

from src.agent.extractor.python_extractor import PythonCodeExtractor
from src.agent.llm.key_manager import resolve_api_key
from src.agent.llm.provider.openai_compat import OpenAICompatProvider
from src.agent.llm.transport.requests_transport import RequestsTransport
from src.agent.orchestrator import Orchestrator
from src.agent.prompt.task_profile.mbpp_profile import MBPPProfile
from src.config.settings import load_providers, load_settings, select_provider
from src.models.input import MBPPTaskInput
from src.sandbox.mock import MockSandbox


def format_mbpp_task(task_input: MBPPTaskInput) -> str:
    """MBPPTaskInputのタスク入力をLLMに渡すuser messages文字列に整形する.

    Args:
        task_input (MBPPTaskInput): タスクファイルから読み込んだMBPPTaskInputオブジェクト

    Returns:
        str: LLMに渡す問題分、関数シグネチャ、テストコードを含む文字列
    """
    lines = [
        f"Problem:\n{task_input.task_definition}\n",
        f"Function signature:\n{task_input.function_definition}\n",
    ]
    if task_input.test_list:
        lines.append("\nYour solution must pass these tests:\n")
        lines.extend(task_input.test_list)
    return "\n".join(lines)


def run_mbpp_agent(
    task_file_path: str,
    output_file_path: str,
    model_name: str | None = None,
    provider_url: str | None = None,
) -> None:
    """MBPPタスクを1問解くエージェントを実行し、SolutionOutputを書き出す.

    Args:
        task_file_path (str): MBPPタスクファイルのパス
        output_file_path (str): SolutionOutputを書き出すJSONファイルのパス
        model_name (str | None): 使用するLLMモデル名。Noneなら設定ファイルのデフォルトを使用
        provider_url (str | None): 使用するLLMプロバイダのURL。Noneなら設定ファイルのデフォルトを使用
    """
    # タスクファイル読み込み
    task_input = MBPPTaskInput.model_validate_json(Path(task_file_path).read_text(encoding="utf-8"))

    # 設定読み込みとプロバイダ解決
    settings = load_settings()
    provider_config = select_provider(load_providers(), model_name, provider_url)
    api_key = resolve_api_key(provider_config.keys_env)

    provider = OpenAICompatProvider(provider_config, RequestsTransport(), api_key)

    # Provider / Sandbox / Orchestrator 構築
    orchestrator = Orchestrator(
        provider=provider,
        extractor=PythonCodeExtractor(),
        sandbox=MockSandbox(),
        profile=MBPPProfile(),
        limits=settings.limits
    )

    # 実行 -> SolutionOutput 書き出し
    solution_output = orchestrator.run(
        str(task_input.task_id), "mbpp", format_mbpp_task(task_input)
    )
    solution_output_path = Path(output_file_path)
    solution_output_path.write_text(solution_output.model_dump_json(indent=2), encoding="utf-8")

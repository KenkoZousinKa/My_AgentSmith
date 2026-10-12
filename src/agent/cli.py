"""MBPP エージェントの組み立て、実行を担う配線.

タスクファイル読み込み -> 設定 / プロバイダ解決 ->
Provider / Sandbox / Orchestrator 構築 ->
実行 -> SolutionOutput 書き出し
fireはagent_mbpp.py / agent_swebench.py から呼ばれ、
検証済みの引数だけを受け取る関数郡

- [ ] BaseAgentCliArgsモデルを作成して検証を拡充
"""
import time
from pathlib import Path
from dotenv import load_dotenv

from src.agent.extractor.python_extractor import PythonCodeExtractor
from src.agent.llm.resilient_client import ResilientLLMClient
# from src.agent.llm.key_manager import resolve_api_key
# from src.agent.llm.provider.openai_compat import OpenAICompatProvider
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
    task_input = MBPPTaskInput.model_validate_json(
        Path(task_file_path).read_text(encoding="utf-8")
    )

    # 設定読み込み
    settings = load_settings()
    # .envから環境変数を読み込む
    load_dotenv()

    providers = load_providers()
    primary_provider = select_provider(providers, model_name, provider_url)
    # primary_providerを先頭にして優先度順に並べる
    providers = [primary_provider, *providers[1:]]

    # 時間制限を使い果たさないようにデッドラインを計算
    # バックオフ待機はこの残予算にクランプされる
    dead_line = time.monotonic() + settings.limits.total_time_sec - settings.limits.time_margin_sec
    client = ResilientLLMClient(
        providers=providers,
        transport=RequestsTransport(),
        retry=settings.retry,
        time_remaining=lambda: max(0, dead_line - time.monotonic()),
    )

    # Provider(ResilientLLMClient) / Sandbox / Orchestrator 構築
    orchestrator = Orchestrator(
        provider=client,
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

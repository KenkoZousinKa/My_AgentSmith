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
from src.models.input import MBPPTaskInput, SWEBenchTaskInput
from src.sandbox.sandbox_main import Sandbox
from src.models.sandbox_config import SandboxConfig
# from src.sandbox.mock import MockSandbox

# ========= add MangoMan ==========
from typing import Callable, Any
from src.mcp.client.http import HttpClientTransport
from src.mcp.models.client_transport import ClientTransport
from src.mcp.client.stdio import StdioClientTransport
from src.mcp.client.client import MCPClient, DEFAULT_URL, SWE_SERVER_COMMAND, MBPP_SERVER_COMMAND
from src.mcp.client.mcp_tool_function import MCPToolFunction
from src.models.output import SolutionOutput
# ========= add MangoMan ==========


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
    providers_file_path: str = "providers/providers.json",
    transport: str = "stdio",
    url: str | None = None,
    command: str | None = None,
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

    providers = load_providers(providers_file_path)
    # select_providerはpriority[0](最小)を基点に上書きコピーを返す
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

    # Sandbox構築
    sandbox_config = SandboxConfig(
        max_execution_time_seconds=int(settings.sandbox.exec_timeout_sec),
        max_memory_mb=settings.sandbox.memory_limit_mb
    )

    # ========= refac MangoMan ==========
    # MCPClient構築
    # httpならurlを取得。なければデフォルトで
    t: ClientTransport
    if transport == "stdio":
        t = StdioClientTransport(command=command or MBPP_SERVER_COMMAND)
    elif transport == "http":
        t = HttpClientTransport(url=url or DEFAULT_URL, command=MBPP_SERVER_COMMAND + " --transport http")
    else:
        raise

    try:
        with MCPClient(t) as c:

            # MCPServerから使えるツールを取得し、呼びだせる形にする
            tools: dict[str, Callable[..., Any]] = {
                tool.name: MCPToolFunction(c, tool)
                for tool in c.list_tools()
            }

            with Sandbox(
                config=sandbox_config,
                tools=tools
            ) as sandbox:

                # Provider(ResilientLLMClient) / Sandbox / Orchestrator 構築
                orchestrator = Orchestrator(
                    provider=client,
                    extractor=PythonCodeExtractor(),
                    sandbox=sandbox,
                    profile=MBPPProfile(),
                    limits=settings.limits
                )

                # 実行 -> SolutionOutput 書き出し
                solution_output = orchestrator.run(
                    str(task_input.task_id), "mbpp", format_mbpp_task(task_input)
                )
    except Exception as e:
        solution_output = SolutionOutput()

    # ========= refac MangoMan ==========

    solution_output_path = Path(output_file_path)
    solution_output_path.write_text(solution_output.model_dump_json(indent=2), encoding="utf-8")


def run_swe_agent(
    task_file_path: str,
    output_file_path: str,
    model_name: str | None = None,
    provider_url: str | None = None,
    providers_file_path: str = "providers/providers.json",
    transport: str = "stdio",
    url: str | None = None,
    command: str | None = None,
) -> None:
    """SWEタスクを1問解くエージェントを実行し、SolutionOutputを書き出す.

    Args:
        task_file_path (str): SWEタスクファイルのパス
        output_file_path (str): SolutionOutputを書き出すJSONファイルのパス
        model_name (str | None): 使用するLLMモデル名。Noneなら設定ファイルのデフォルトを使用
        provider_url (str | None): 使用するLLMプロバイダのURL。Noneなら設定ファイルのデフォルトを使用
    """
    # タスクファイル読み込み
    task_input = SWEBenchTaskInput.model_validate_json(
        Path(task_file_path).read_text(encoding="utf-8")
    )

    # 設定読み込み
    settings = load_settings()
    # .envから環境変数を読み込む
    load_dotenv()

    providers = load_providers(providers_file_path)
    # select_providerはpriority[0](最小)を基点に上書きコピーを返す
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

    # Sandbox構築
    sandbox_config = SandboxConfig(
        max_execution_time_seconds=int(settings.sandbox.exec_timeout_sec),
        max_memory_mb=settings.sandbox.memory_limit_mb
    )

    # ========= refac MangoMan ==========
    # MCPClient構築
    # httpならurlを取得。なければデフォルトで
    env = {
        "SWE_DOCKER_IMAGE": task_input.docker_image,
        "SWE_EVAL_SCRIPT": task_input.eval_script,
        "TESTBED_PATH": "/testbed"
    }

    t: ClientTransport
    if transport == "stdio":
        t = StdioClientTransport(command=command or SWE_SERVER_COMMAND, env=env)
    elif transport == "http":
        t = HttpClientTransport(url=url or DEFAULT_URL, command=SWE_SERVER_COMMAND + " --transport http",
                                env=env)
    else:
        raise

    with MCPClient(t) as c:

        # MCPServerから使えるツールを取得し、呼びだせる形にする
        tools: dict[str, Callable[..., Any]] = {
            tool.name: MCPToolFunction(c, tool)
            for tool in c.list_tools()
        }

        with Sandbox(
            config=sandbox_config,
            tools=tools
        ) as sandbox:

            import sys
            print(sandbox.tools)
            print()
            print(sandbox.tools['run_command'](command="cat README.rst"))
            sys.exit(1)

            # Provider(ResilientLLMClient) / Sandbox / Orchestrator 構築
            orchestrator = Orchestrator(
                provider=client,
                extractor=PythonCodeExtractor(),
                sandbox=sandbox,
                profile=MBPPProfile(),
                limits=settings.limits
            )

            # 実行 -> SolutionOutput 書き出し
            # solution_output = orchestrator.run(
            #     str(task_input.task_id), "mbpp", format_mbpp_task(task_input)
            # )
    # ========= refac MangoMan ==========

    # solution_output_path = Path(output_file_path)
    # solution_output_path.write_text(solution_output.model_dump_json(indent=2), encoding="utf-8")

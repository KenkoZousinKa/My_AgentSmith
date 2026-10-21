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

from src.agent.extractor.composite_extractor import CompositeCodeExtractor
from src.agent.llm.resilient_client import ResilientLLMClient
# from src.agent.llm.key_manager import resolve_api_key
# from src.agent.llm.provider.openai_compat import OpenAICompatProvider
from src.agent.llm.transport.requests_transport import RequestsTransport
from src.agent.orchestrator import Orchestrator
from src.agent.prompt.task_profile.mbpp_profile import MBPPProfile
from src.agent.prompt.task_profile.swebench_profile import SWEBenchProfile
from src.config.settings import load_providers, load_settings, order_providers
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
from mcp_tools_swebench import META_KEY
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


# SWE-Benchのissueにつくヒントの最大文字数。長いと毎反復のinput_tokenを圧迫するので制限する。
_HINTS_MAX_CHARS = 4000


def format_swebench_task(task_input: SWEBenchTaskInput) -> str:
    """SWEBenchTaskInputのタスク入力をLLMに渡すuser messages文字列に整形する.

    issueの本文、タスクファイルに含まれるヒント(issueのコメント)を渡す。
    ヒントはタスク入力の一部なので外部から回答を持ってくることはしない。

    Args:
        task_input (SWETaskInput): タスクファイルから読み込んだSWETaskInputオブジェクト

    Returns:
        str: LLMに渡す問題分、関数シグネチャ、テストコードを含む文字列
    """
    # repoは任意(既定で空)なのでなければinstance_idを使う。
    lines = [
        f"Repository: {task_input.repo or task_input.instance_id} (checked out at /testbed)\n",
        "",
        "Issue:",
        task_input.problem_statement.strip()
    ]
    hints = task_input.hints_text.strip()
    if hints:
        if len(hints) > _HINTS_MAX_CHARS:
            hints = hints[:_HINTS_MAX_CHARS] + "\n...[hints truncated]"
        lines += ["", "Hints from the issue discussion:", hints]

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
        providers_file_path (str): プロバイダーファイルのパス。デフォルトは"providers/providers.json"
        transport (str): MCPServerとの通信方法。stdioかhttpを指定。デフォルトはstdio
        url (str | None): http通信時のMCPServerのURL。NoneならデフォルトURLを使用
        command (str | None): stdio通信時のMCPServerのコマンド。Noneならデフォルトコマンドを使用
    """
    # タスクファイル読み込み
    task_input = MBPPTaskInput.model_validate_json(
        Path(task_file_path).read_text(encoding="utf-8")
    )

    # 設定読み込み
    settings = load_settings()
    # .envから環境変数を読み込む
    load_dotenv()

    original_providers = load_providers(providers_file_path)
    # CLIで指定されたmodel_name / provider_urlを先頭にし、残りはproviders.jsonのpriority順に並べる
    # providers.jsonにないモデル / URLは、ValueErrorで止める。
    providers = order_providers(original_providers, model_name, provider_url)
    # ===raise ValueErrorが登ってくるのをどっかで拾う(solution.json書き込みなしVer)===

    # 時間制限を使い果たさないようにデッドラインを計算
    # バックオフ待機はこの残予算にクランプされる
    dead_line = time.monotonic() + settings.limits.total_time_sec - settings.limits.time_margin_sec
    # Provider(ResilientLLMClient)構築
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

    # MCPClient構築
    # httpならurlを取得。なければデフォルトで
    t: ClientTransport
    if transport == "stdio":
        t = StdioClientTransport(command=command or MBPP_SERVER_COMMAND)
    elif transport == "http":
        t = HttpClientTransport(url=url or DEFAULT_URL, command=MBPP_SERVER_COMMAND + " --transport http")
    else:
        raise ValueError(f"Unknown transport: {transport}. (expected 'stdio' or 'http')")

    with MCPClient(t) as c:

        # MCPServerから使えるツールを取得し、呼びだせる形にする
        tools: dict[str, Callable[..., Any]] = {
            tool.name: MCPToolFunction(c, tool)
            for tool in c.list_tools()
        }

        # Sandbox構築
        with Sandbox(
            config=sandbox_config,
            tools=tools
        ) as sandbox:

            # Orchestrator 構築
            orchestrator = Orchestrator(
                provider=client,
                extractor=CompositeCodeExtractor(),
                sandbox=sandbox,
                profile=MBPPProfile(),
                limits=settings.limits
            )

            # 実行 -> SolutionOutput 書き出し
            solution_output = orchestrator.run(
                str(task_input.task_id), "mbpp", format_mbpp_task(task_input)
            )
    # === try: except でのエラー時のSolutionOutput書き出しは失敗するため一旦外しました。あとで全体を考慮して入れます。 ===

    solution_output_path = Path(output_file_path)
    solution_output_path.write_text(solution_output.model_dump_json(indent=2), encoding="utf-8")


def run_swe_agent(
    task_file_path: str,
    output_file_path: str,
    model_name: str | None = None,
    provider_url: str | None = None,
    providers_file_path: str = "providers/providers_swebench.json",
    transport: str = "stdio",
    url: str | None = None,
    command: str | None = None,
) -> None:
    """SWEタスクを1問解くエージェントを実行し、SolutionOutputを書き出す.

    Dockerコンテナの起動と片付けはMCPServer(mcp_tools_swebench)が担う。
    Agentはinit_metaでDockerイメージ名 / eval_script(評価スクリプト) / リポジトリの場所をMCPServerに渡す。

    Args:
        task_file_path (str): SWEタスクファイルのパス。
        output_file_path (str): SolutionOutputを書き出すJSONファイルのパス。
        model_name (str | None): 使用するLLMモデル名。Noneなら設定ファイルのデフォルトを使用。
        provider_url (str | None): 使用するLLMプロバイダのURL。Noneなら設定ファイルのデフォルトを使用。
        providers_file_path (str): プロバイダーファイルのパス。デフォルトは"providers/providers_swebench.json"
        transport (str): MCPServerとの通信方法。stdioかhttpを指定。デフォルトはstdio
        url (str | None): http通信時のMCPServerのURL。NoneならデフォルトURLを使用。
        command (str | None): stdio通信時のMCPServerのコマンド。Noneならデフォルトコマンドを使用。
    """
    # =============== タスクファイル読み込み ===============
    task_input = SWEBenchTaskInput.model_validate_json(
        Path(task_file_path).read_text(encoding="utf-8")
    )

    # ================== 設定読み込み ==================
    settings = load_settings()
    # SWE-BenchはMBPPと制限が違うのでswebench_limitsを使う。(-> Orchestrator, deadline計算)
    limits = settings.swebench_limits
    # .envから環境変数を読み込む
    load_dotenv()

    # ================== プロバイダ解決 ==================
    original_providers = load_providers(providers_file_path)
    # CLIで指定されたmodel_name / provider_urlを先頭にし、残りはproviders.jsonのpriority順に並べる
    # providers.jsonにないモデル / URLは、ValueErrorで止める。
    providers = order_providers(original_providers, model_name, provider_url)
    # === raise ValueErrorが登ってくるのをどっかで拾う(solution.json書き込みなしVer) ===

    # =============== Provider(ResilientLLMClient)構築 ===============
    # 時間制限を使い果たさないようにデッドラインを計算
    # バックオフ待機はこの残予算にクランプされる
    dead_line = time.monotonic() + limits.total_time_sec - limits.time_margin_sec
    client = ResilientLLMClient(
        providers=providers,
        transport=RequestsTransport(),
        retry=settings.retry,
        time_remaining=lambda: max(0, dead_line - time.monotonic()),
    )

    # =========== Sandbox config は SWE-Bench用に設定を変える？ ==========
    sandbox_config = SandboxConfig(
        max_execution_time_seconds=int(settings.sandbox.exec_timeout_sec),
        max_memory_mb=settings.sandbox.memory_limit_mb
    )

    # ================== MCPClient構築 ==================
    # サーバーにコンテナの起動に必要な情報を渡すためのinit_meta
    init_meta = {META_KEY: {"docker_image": task_input.docker_image,
                            "eval_script": task_input.eval_script,
                            "testbed_path": "/testbed"}}  # debug等で指定したPATHからToolsを動かしたい場合のみ使用

    # httpならurlを取得。なければデフォルトで
    t: ClientTransport
    if transport == "stdio":
        t = StdioClientTransport(command=command or SWE_SERVER_COMMAND)
    elif transport == "http":
        t = HttpClientTransport(url=url or DEFAULT_URL, command=SWE_SERVER_COMMAND + " --transport http")
    else:
        raise ValueError(f"Unknown transport: {transport}. (expected 'stdio' or 'http')")

    with MCPClient(t, init_meta=init_meta) as c:

        # MCPServerから使えるツールを取得し、呼びだせる形にする
        tools: dict[str, Callable[..., Any]] = {
            tool.name: MCPToolFunction(c, tool)
            for tool in c.list_tools()
        }

        # ================== Sandbox構築 ==================
        with Sandbox(
            config=sandbox_config,
            tools=tools
        ) as sandbox:

            # import sys
            # print(sandbox.tools)
            # print()
            # print(sandbox.tools['run_command'](command="cat README.rst"))
            # sys.exit(1)

            # ================= Orchestrator 構築 =================
            orchestrator = Orchestrator(
                provider=client,
                extractor=CompositeCodeExtractor(),
                sandbox=sandbox,
                profile=SWEBenchProfile(),
                limits=limits  # SWE-BenchはMBPPと制限が違うのでswebench_limitsを使う
            )

            # 実行 -> SolutionOutput 書き出し
            # 打ち切り時のパッチの回収をコンテナ内で行うので、コンテナが生きているうちに実行を終える。
            solution_output = orchestrator.run(
                str(task_input.instance_id), "swebench", format_swebench_task(task_input)
            )

    # === try: except でのエラー時のSolutionOutput書き出しは失敗するため一旦外しました。あとで全体を考慮して入れます。 ===
    solution_output_path = Path(output_file_path)
    solution_output_path.write_text(solution_output.model_dump_json(indent=2), encoding="utf-8")

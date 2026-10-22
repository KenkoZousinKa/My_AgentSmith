"""MBPP / SWE-Benchエージェントの組み立て、実行を担う配線.

タスクファイル読み込み -> 設定 / プロバイダ解決 ->
Provider / Sandbox / Orchestrator 構築 ->
実行 -> SolutionOutput 書き出し
fireはagent_mbpp.py / agent_swebench.py から呼ばれ、
検証済みの引数だけを受け取る関数郡

run_mbpp / swe _agent -> run_safely -> _solve_mbpp / swebench -> solve -> _solve_mbpp / swebench

- [ ] BaseAgentCliArgsモデルを作成して検証を拡充
"""
import signal
import sys
import time
import traceback
from pathlib import Path
from types import FrameType
from typing import TypeVar

from dotenv import load_dotenv
from pydantic import BaseModel

from src.agent.extractor.composite_extractor import CompositeCodeExtractor
from src.agent.llm.resilient_client import ResilientLLMClient
from src.agent.llm.transport.requests_transport import RequestsTransport
from src.agent.orchestrator import Orchestrator
from src.agent.prompt.task_profile.mbpp_profile import MBPPProfile
from src.agent.prompt.task_profile.swebench_profile import SWEBenchProfile
from src.config.settings import load_providers, load_settings, order_providers, Settings, Limits
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

_Task = TypeVar("_Task", bound=BaseModel)

# 終了コード。128 + シグナル番号で終了コードを返す。
_EXIT_CODE_KEYBOARD_INTERRUPT = 130  # 128 + SIGINT(2)
_EXIT_CODE_TERMINATED = 143  # 128 + SIGTERM(15)
# solution.jsonのerror欄に入れる例外メッセージの最大文字数。
_ERROR_MAX_CHARS = 500


class _Terminated(BaseException):
    """採点側のSIGTERMで止められたことを表す例外クラス.

    BaseExceptionを継承し途中のexcept Exceptionで拾われないようにする。
    """


def _raise_terminated(signum: int, frame: FrameType | None) -> None:
    """SIGTERMを受けたら_Terminated例外を投げるシグナルハンドラ.

    Args:
        signum (int): 受け取ったシグナル番号
        frame (FrameType | None): 現在のフレーム情報。Noneの場合もある。

    Raises:
        _Terminated: SIGTERMを受けたことを表す例外
    """
    raise _Terminated(f"Received signal ({signum})")


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
    # テストは解答 + test_imports + test_list の順に連結して行われるため形式を揃える。
    if task_input.test_imports:
        lines.append("\nThe tests run after these imports:\n")
        lines.extend(task_input.test_imports)

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
    # 採点側の制限時間の数え方がプロセスの起動から開始するので最初に起点を取る。
    start_time = time.monotonic()

    def solve(task_input: MBPPTaskInput) -> SolutionOutput:
        """MBPPタスクを解き、SolutionOutputを返す."""
        return _solve_mbpp(
            task_input,
            start_time,
            model_name,
            provider_url,
            providers_file_path,
            transport,
            url,
            command
        )

    _run_safely(
        benchmark="mbpp",
        start_time=start_time,
        task_file_path=task_file_path,
        output_file_path=output_file_path,
        task_model=MBPPTaskInput,
        task_id_of=lambda task_input: str(task_input.task_id),
        solve=solve
    )


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
    # 採点側の制限時間の数え方がプロセスの起動から開始するので最初に起点を取る。
    start_time = time.monotonic()

    def solve(task_input: SWEBenchTaskInput) -> SolutionOutput:
        """読み込んだSWE-benchタスクを解き、SolutionOutputを返す."""
        return _solve_swebench(
            task_input,
            start_time,
            model_name,
            provider_url,
            providers_file_path,
            transport,
            url,
            command
        )

    _run_safely(
        benchmark="swebench",
        start_time=start_time,
        task_file_path=task_file_path,
        output_file_path=output_file_path,
        task_model=SWEBenchTaskInput,
        task_id_of=lambda task_input: str(task_input.instance_id),
        solve=solve
    )


def _run_safely(
    benchmark: str,
    start_time: float,
    task_file_path: str,
    output_file_path: str,
    task_model: type[_Task],
    task_id_of: Callable[[_Task], str],
    solve: Callable[[_Task], SolutionOutput]
) -> None:
    """タスクを解く処理を安全に実行し、例外が起きてもSolutionOutputを書き出す.

    - 想定外の例外
        success=False, error=AGENT_CRASH を書いて正常終了する。
    - Ctrl+C / SIGTERM
        success=False, error=INTERRUPTED を書いて130 / 143で終了する。
    MCPServer / Sandbox の後片付けは solve()の中の with で行い、例外が _run_safely() に届く前に終了するようにする。

    Args:
        benchmark (str): "mbpp" or "swebench"
        start_time (float): プロセス起動直後の time.monotonic() の値。経過時間の計算に使う。
        task_file_path (str): タスクファイルのパス
        output_file_path (str): SolutionOutputを書き出すJSONファイルのパス
        task_model (type[_Task]): タスクファイルを読み込むモデルクラス(MBPPTaskInput or SWEBenchTaskInput)
        task_id_of (Callable[[_Task], str]): タスク入力からタスクIDを取得する関数
        solve (Callable[[_Task], SolutionOutput]): タスク入力を解き、SolutionOutputを返す関数
    """
    # タスクファイルを読み込む前に失敗した場合のtask_id
    task_id = "unknown"
    interrupted: BaseException | None = None
    # SIGTERMの既定の動作を無効化し、_raise_terminated()を呼ぶようにする。
    previous_handler = signal.signal(signal.SIGTERM, _raise_terminated)

    # 外側のtry: Ctrl+C / SIGTERMでの中断を受け止める。内側の処理中に来てもここで受ける。
    # MCPサーバーが先に落ち内側のtry:で捕捉、その後にエージェントが落ちる場合などを想定。
    # timeoutでSIGTERMが来るので、途中までのSolutionOutputの出力はOrchestratorのrun()が時間内でガードする。
    try:
        # 内側のtry: 想定外の例外を受け止める。
        try:
            # =============== タスクファイル読み込み ===============
            task_input = task_model.model_validate_json(
                Path(task_file_path).read_text(encoding="utf-8")
            )
            task_id = task_id_of(task_input)
            solution_output = solve(task_input)

        # 想定外の例外が起きた場合は、tracebackをstderrに出力し、SolutionOutputにAGENT_CRASHを書き込む。
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            solution_output = _failed_solution(
                task_id=task_id,
                benchmark=benchmark,
                start_time=start_time,
                error=f"AGENT_CRASH: {type(error).__name__}: {error}"
            )

    # Ctrl+C / SIGTERMで中断された場合は、SolutionOutputにINTERRUPTEDを書き込む。
    except (KeyboardInterrupt, _Terminated) as error:
        interrupted = error
        solution_output = _failed_solution(
            task_id=task_id,
            benchmark=benchmark,
            start_time=start_time,
            error=f"INTERRUPTED: {type(error).__name__}"
        )

    finally:
        signal.signal(signal.SIGTERM, previous_handler)

    # ================== SolutionOutput書き出し ==================
    solution_output_path = Path(output_file_path)
    solution_output_path.parent.mkdir(parents=True, exist_ok=True)
    solution_output_path.write_text(solution_output.model_dump_json(indent=2), encoding="utf-8")

    # Ctrl+C / SIGTERMで中断された場合は、終了コードを130 / 143で返す。
    if interrupted is not None:
        if isinstance(interrupted, KeyboardInterrupt):
            raise SystemExit(_EXIT_CODE_KEYBOARD_INTERRUPT)
        raise SystemExit(_EXIT_CODE_TERMINATED)


def _failed_solution(
    task_id: str,
    benchmark: str,
    start_time: float,
    error: str
) -> SolutionOutput:
    """Orchestratorの結果を受け取れずに終わった場合の失敗を表すSolutionOutputを作る.

    Args:
        task_id (str): タスクID(読み込む前に失敗したら"unknown")
        benchmark (str): "mbpp" or "swebench"
        start_time (float): プロセス起動直後の time.monotonic() の値。
        error (str): SolutionOutputのerror欄に入れるエラーメッセージ。

    Returns:
        SolutionOutput: success=FalseのSolutionOutput
    """
    return SolutionOutput(
        task_id=task_id,
        benchmark=benchmark,
        success=False,
        solution="",
        iterations=0,
        total_requests=0,
        total_input_tokens=0,
        total_output_tokens=0,
        total_time_seconds=time.monotonic() - start_time,
        error=error[:_ERROR_MAX_CHARS]
    )


def _solve_mbpp(
    task_input: MBPPTaskInput,
    start_time: float,
    model_name: str | None,
    provider_url: str | None,
    providers_file_path: str,
    transport: str,
    url: str | None,
    command: str | None
) -> SolutionOutput:
    """MBPPタスクを解き、SolutionOutputを返す.

    Args:
        task_input (MBPPTaskInput): タスクファイルから読み込んだMBPPTaskInputオブジェクト
        start_time (float): プロセス起動直後の time.monotonic() の値。経過時間の計算に使う。
        model_name (str | None): 使用するLLMモデル名。Noneなら設定ファイルのデフォルトを使用。
        provider_url (str | None): 使用するLLMプロバイダのURL。Noneなら設定ファイルのデフォルトを使用。
        providers_file_path (str): プロバイダーファイルのパス。
        transport (str): MCPServerとの通信方法。stdioかhttpを指定。
        url (str | None): http通信時のMCPServerのURL。NoneならデフォルトURLを使用。
        command (str | None): stdio通信時のMCPServerのコマンド。Noneならデフォルトコマンドを使用。

    Returns:
        SolutionOutput: タスクの解決結果。
    """
    # 設定読み込み
    settings = load_settings()
    # .envから環境変数を読み込む
    load_dotenv()

    # =============== Provider(ResilientLLMClient)構築 ===============
    client = _build_client(
        settings=settings,
        limits=settings.limits,
        start_time=start_time,
        model_name=model_name,
        provider_url=provider_url,
        providers_file_path=providers_file_path
    )

    # ===================== SandboxConfig構築 =====================
    sandbox_config = _build_sandbox(settings)

    # ===================== MCPClient構築 =====================
    client_transport = _build_transport(
        transport=transport,
        url=url,
        command=command,
        server_command=MBPP_SERVER_COMMAND
    )
    with MCPClient(client_transport) as c:
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

            # ================= Orchestrator 構築 =================
            orchestrator = Orchestrator(
                provider=client,
                extractor=CompositeCodeExtractor(),
                sandbox=sandbox,
                profile=MBPPProfile(),
                limits=settings.limits,
                start_time=start_time
            )

            # 実行 -> SolutionOutput 書き出し
            return orchestrator.run(
                str(task_input.task_id), "mbpp", format_mbpp_task(task_input)
            )


def _solve_swebench(
    task_input: SWEBenchTaskInput,
    start_time: float,
    model_name: str | None,
    provider_url: str | None,
    providers_file_path: str,
    transport: str,
    url: str | None,
    command: str | None
) -> SolutionOutput:
    """SWE-Benchタスクを解き、SolutionOutputを返す.

    Args:
        task_input (SWEBenchTaskInput): タスクファイルから読み込んだSWEBenchTaskInputオブジェクト
        start_time (float): プロセス起動直後の time.monotonic() の値。経過時間の計算に使う。
        model_name (str | None): 使用するLLMモデル名。Noneなら設定ファイルのデフォルトを使用。
        provider_url (str | None): 使用するLLMプロバイダのURL。 Noneなら設定ファイルのデフォルトを使用。
        providers_file_path (str): プロバイダーファイルのパス。
        transport (str): MCPServerとの通信方法。stdioかhttpを指定。
        url (str | None): http通信時のMCPServerのURL。NoneならデフォルトURLを使用。
        command (str | None): stdio通信時のMCPServerのコマンド。Noneならデフォルトコマンドを使用。

    Returns:
        SolutionOutput: タスクの解決結果。
    """
    # ================== 設定読み込み ==================
    settings = load_settings()
    # SWE-BenchはMBPPと制限が違うのでswebench_limitsを使う。(-> Orchestrator, deadline計算)
    limits = settings.swebench_limits
    # .envから環境変数を読み込む
    load_dotenv()

    # =============== Provider(ResilientLLMClient)構築 ===============
    client = _build_client(
        settings=settings,
        limits=limits,
        start_time=start_time,
        model_name=model_name,
        provider_url=provider_url,
        providers_file_path=providers_file_path
    )

    # ===================== SandboxConfig構築 =====================
    sandbox_config = _build_sandbox(settings)

    # ===================== MCPClient構築 =====================
    # サーバーにコンテナの起動に必要な情報を渡すためのinit_meta
    client_transport = _build_transport(
        transport=transport,
        url=url,
        command=command,
        server_command=SWE_SERVER_COMMAND
    )
    init_meta = {META_KEY: {"docker_image": task_input.docker_image,
                            "eval_script": task_input.eval_script,
                            "testbed_path": "/testbed"}}  # debug等で指定したPATHからToolsを動かしたい場合のみ使用
    with MCPClient(
        transport=client_transport,
        init_meta=init_meta
    ) as c:

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

            # ================= Orchestrator 構築 =================
            orchestrator = Orchestrator(
                provider=client,
                extractor=CompositeCodeExtractor(),
                sandbox=sandbox,
                profile=SWEBenchProfile(),
                limits=limits,
                start_time=start_time
            )

            # 実行 -> SolutionOutput 書き出し
            return orchestrator.run(
                str(task_input.instance_id), "swebench", format_swebench_task(task_input)
            )


def _build_client(
    settings: Settings,
    limits: Limits,
    start_time: float,
    model_name: str | None,
    provider_url: str | None,
    providers_file_path: str,
) -> ResilientLLMClient:
    """CLIの指定を反映したプロバイダの並びから残り時間を計算するResilientLLMClientを構築する.

    Args:
        settings (Settings): 設定オブジェクト
        limits (Limits): 制限値オブジェクト
        start_time (float): プロセス起動直後の time.monotonic() の値。
        model_name (str | None): 使用するLLMモデル名。Noneなら設定ファイルのデフォルトを使用。
        provider_url (str | None): 使用するLLMプロバイダのURL。Noneなら設定ファイルのデフォルトを使用。
        providers_file_path (str): プロバイダーファイルのパス。

    Returns:
        ResilientLLMClient: 構築されたResilientLLMClient

    Raises:
        ValueError: 指定されたmodel_name / provider_urlがproviders.jsonにない場合
    """
    # ================== プロバイダ解決 ==================
    original_providers = load_providers(providers_file_path)
    # CLIで指定されたmodel_name / provider_urlを先頭にし、残りはproviders.jsonのpriority順に並べる
    # providers.jsonにないモデル / URLは、ValueErrorで止める。
    providers = order_providers(original_providers, model_name, provider_url)
    # raise ValueErrorが登ってくるのをrun_safely()で捕まえてSolutionOutputに書き出す。

    # 時間制限を使い果たさないようにデッドラインを計算
    # バックオフ待機はこの残予算にクランプされる
    dead_line = start_time + limits.total_time_sec - limits.time_margin_sec
    # ============= Provider(ResilientLLMClient)構築 =============
    return ResilientLLMClient(
        providers=providers,
        transport=RequestsTransport(),
        retry=settings.retry,
        time_remaining=lambda: max(0, dead_line - time.monotonic()),
    )


def _build_sandbox(settings: Settings) -> SandboxConfig:
    """設定ファイルの値からSandboxConfigを構築する.

    Args:
        settings (Settings): 読み込んだ設定。

    Returns:
        SandboxConfig: 1回の実行の制限時間とメモリ上限を入れた設定。
    """
    return SandboxConfig(
        max_execution_time_seconds=int(settings.sandbox.exec_timeout_sec),
        max_memory_mb=settings.sandbox.memory_limit_mb
    )


def _build_transport(
    transport: str,
    url: str | None,
    command: str | None,
    server_command: str
) -> ClientTransport:
    """CLIの引数からMCPServerとの通信方法、ClientTransportを構築する.

    Args:
        transport (str): "stdio" or "http"
        url (str | None): http通信時のMCPServerのURL。NoneならデフォルトURLを使用。
        command (str | None): stdio通信時のMCPServerのコマンド。Noneならデフォルトコマンドを使用。
        server_command (str): このベンチマークの既定のサーバー起動コマンド。

    Returns:
        ClientTransport: 構築されたClientTransport(StdioClientTransport or HttpClientTransport)

    Raises:
        ValueError: transportが"stdio"でも"http"でもない場合
    """
    # httpならurlを取得。なければデフォルトで。サーバーがいなければ既定のサーバーを起動する。
    if transport == "stdio":
        return StdioClientTransport(command=command or server_command)
    if transport == "http":
        return HttpClientTransport(url=url or DEFAULT_URL, command=server_command + " --transport http")

    raise ValueError(f"Unknown transport: {transport}. (expected 'stdio' or 'http')")

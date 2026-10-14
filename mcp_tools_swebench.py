"""mcp_tools_swebench.py"""

import os
import signal
import argparse

from src.mcp_core.server.server import MCPServer
from src.mcp_core.server.http import HttpServerTransport
from src.mcp_core.swe_bench.executor import DockerExecutor, Executor, LocalExecutor

server = MCPServer(name="agent-smith-swebench", version="0.1.0")
TESTBED_PATH = os.environ.get("TESTBED_PATH", "/testbed")
COMMAND_TIMEOUT = 120
executor: Executor = LocalExecutor()


@server.tool()
def run_command(command: str, workdir: str = TESTBED_PATH) -> str:
    """Execute a shell command in the given working directory.

    Returns the command's stdout, stderr and exit code.
    """
    r = executor.run(command, workdir, COMMAND_TIMEOUT)
    return f"exit_code: {r.exit_code}\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"


def _on_sigterm(signum: int, frame: object) -> None:
    raise SystemExit(0)
    # ↑ SIGTERM を受けたら、SystemExit を起こす。これで main() の finally が動き、コンテナを片付けられる
    #   （何もしないと、Python は SIGTERM で即座に終わり、finally が動かない）


def main() -> None:
    parser = argparse.ArgumentParser(description="SWE-bench MCP Server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    global executor
    image = os.environ.get("SWE_DOCKER_IMAGE")
    if image:
        docker = DockerExecutor(image)
        docker.start()
        executor = docker
    signal.signal(signal.SIGTERM, _on_sigterm)
    try:
        if args.transport == "http":
            server.run(HttpServerTransport(host=args.host, port=args.port))
        else:
            server.run()
    finally:
        executor.close()


if __name__ == "__main__":
    main()

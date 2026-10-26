"""SWE-bench の tools が使う、コマンドの実行係（ローカルか Docker か）."""

import sys
import subprocess
import time
import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    exit_code: int


class Executor(Protocol):
    def run(self, command: str, workdir: str, timeout: int, input: str = "") -> CommandResult: ...
    def close(self) -> None: ...


class LocalExecutor:
    """TESTBED_PATHのフォルダーでコマンドを実行する."""

    def run(self, command: str, workdir: str, timeout: int, input: str = "") -> CommandResult:
        try:
            r = subprocess.run(["bash", "-c", command], cwd=workdir, input=input, capture_output=True,
                               text=True, timeout=timeout)
            #  Stdoutを汚さない
        except subprocess.TimeoutExpired as e:
            out: str = e.stdout.decode("utf-8", errors="replace") if isinstance(e.stdout, bytes) else ""
            return CommandResult(out, f"Timeout after {timeout}s", 124)
            # GNUのtimeoutコマンド
        return CommandResult(r.stdout, r.stderr, r.returncode)

    def close(self) -> None:
        pass


class DockerExecutor:
    """コンテナ起動後、その中でコマンドを実行する."""

    def __init__(self, image: str) -> None:
        self.image = image
        self.name = f"agentsmith-{uuid.uuid4().hex[:12]}"  # docker name
        self.process: subprocess.Popen[bytes] | None = None

    def start(self, timeout: int = 600) -> None:
        """コンテナを起動し、動き始めるまで待つ."""
        print('🐳Dockerコンテナを起動しています。', file=sys.stderr)
        self.process = subprocess.Popen(
            ["docker", "run", "-i", "--rm", "--name", self.name,
             "--network", "none", "--label", "agentsmith=1", self.image, "cat"],
            #   -i：コンテナの stdin を、docker runプロセスと繋ぐ(self.processを介してデーモンにコマンドに流せる
            #   cat：dockerを待機させるダミーコマンド。これがコンテナの主プロセスになる
            #   --rm：主プロセスが終わったら、コンテナを自動で消す
            #   --label:コンテナを後から探れるように
            #   SIGKILLでもコンテナが残らない
            stdin=subprocess.PIPE,  # docker runプロセスとこのプロセスをつなぐ
            stdout=subprocess.DEVNULL,  # docker run の出力をゴミ箱へ
        )
        deadline = time.monotonic() + timeout
        while not self._is_running():
            if self.process.poll() is not None:
                raise RuntimeError(f"コンテナの起動に失敗しました: {self.image}")
            if time.monotonic() > deadline:
                self.close()
                raise RuntimeError(f"コンテナが {timeout} 秒以内に起動しませんでした: {self.image}")
            time.sleep(0.5)
        print('✅Dockerコンテナが正常に起動しました。', file=sys.stderr)

    def _is_running(self) -> bool:
        """コンテナが起動しているか確認する。起動していればTrueで返る."""
        r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", self.name],
                           capture_output=True, text=True)
        return r.stdout.strip() == "true"

    def run(self, command: str, workdir: str, timeout: int, input: str = "") -> CommandResult:
        r = subprocess.run(
            ["docker", "exec", "-i", "-w", workdir, self.name,
             "timeout", "-s", "KILL", str(timeout), "bash", "-lc", command],
            input=input, capture_output=True, text=True)  # コンテナの中のコマンドを止めるためにtimeoutを設定
        # -i: inputをコンテナ内のコマンドのstdinに流す
        # bash -l: ログインシェルとして起動し、イメージが用意したtestbedのconda環境を有効にする。
        # bash -c: minicondaのbaseのPythonになり、リポジトリの依存がなくimportできない。
        # timeoutをSIGTERMからSIGKILLに変更
        return CommandResult(r.stdout, r.stderr, r.returncode)

    def close(self) -> None:
        """コンテナを消す."""
        if self.process is None:
            return
        if self.process.stdin is not None:
            self.process.stdin.close()            # cat に EOF
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            # 削除コマンドを実行
            subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)
        self.process = None

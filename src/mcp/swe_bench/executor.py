"""SWE-benchのツールが実行される環境ごとに用意されるクラス."""

import sys
import subprocess
import time
import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass
class CommandResult:
    """コマンド実行の結果を保持するデータクラス.

    Attributes:
        stdout (str): コマンドの標準出力
        stderr (str): コマンドの標準エラー出力
        exit_code (int): コマンドの終了コード
    """
    stdout: str
    stderr: str
    exit_code: int


class Executor(Protocol):
    """SWE-benchのツール実行環境単位で用意されるインターフェースプロトコル."""
    def run(self, command: str, workdir: str, timeout: int, input: str = "") -> CommandResult:
        """コマンドを実行する.

        標準入力を読むコマンドが渡された場合にはinputの内容が標準入力に渡される.
        inputが空文字であればEOFが送られるので親プロセス(クライアントとの通信)の標準入力を読むことはない.
        Args:
            command (str): 実行するコマンド
            workdir (str): 作業ディレクトリ
            timeout (int): タイムアウト時間（秒）
            input (str, optional): 標準入力に渡す文字列. Defaults to "".

        Returns:
            CommandResult: コマンド実行結果
        """
        ...

    def close(self) -> None:
        """実行環境を終了する."""
        ...


class LocalExecutor:
    """ローカルのTESTBED_PATHのフォルダーでコマンドを実行する."""

    def run(self, command: str, workdir: str, timeout: int, input: str = "") -> CommandResult:
        """ローカル環境でコマンドを実行する.

        Args:
            command (str): 実行するコマンド
            workdir (str): 作業ディレクトリ
            timeout (int): タイムアウト時間（秒）
            input (str, optional): 標準入力に渡す文字列. Defaults to "".

        Returns:
            CommandResult: コマンド実行結果
        """
        try:
            # capture_output=True: 標準出力と標準エラー出力をrに取得する
            r = subprocess.run(["bash", "-c", command], cwd=workdir, input=input, capture_output=True,
                               text=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            # 途中までの標準出力を取得する
            out: str = e.stdout.decode("utf-8", errors="replace") if isinstance(e.stdout, bytes) else ""
            return CommandResult(out, f"Timeout after {timeout}s", 124)  # GNUのtimeoutコマンド
        return CommandResult(r.stdout, r.stderr, r.returncode)

    def close(self) -> None:
        """ローカル環境の終了処理."""
        pass


class DockerExecutor:
    """Dockerコンテナ内のTESTBED_PATHのフォルダーでコマンドを実行する.

    Attributes:
        image (str): 使用するDockerイメージ
        name (str): コンテナ名
        process (subprocess.Popen[bytes] | None): Dockerデーモンに指示を送るためのプロセス
    """

    def __init__(self, image: str) -> None:
        """Dockerコンテナ実行環境を初期化する.

        Args:
            image (str): 使用するDockerイメージ
        """
        self.image = image
        self.name = f"agentsmith-{uuid.uuid4().hex[:12]}"  # docker name
        self.process: subprocess.Popen[bytes] | None = None

    def start(self, timeout: int = 600) -> None:
        """コンテナを立ち上げ、正常に起動するまで待機する.

        Args:
            timeout (int, optional): コンテナが起動するまでの最大待機時間（秒）. Defaults to 600.
        """
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
        # コンテナが起動までの待機ループ
        deadline = time.monotonic() + timeout
        while not self._is_running():
            # docker runプロセスが終了した場合
            if self.process.poll() is not None:
                raise RuntimeError(f"コンテナの起動に失敗しました: {self.image}")
            if time.monotonic() > deadline:
                self.close()
                raise RuntimeError(f"コンテナが {timeout} 秒以内に起動しませんでした: {self.image}")
            time.sleep(0.5)
        print('✅Dockerコンテナが正常に起動しました。', file=sys.stderr)

    def _is_running(self) -> bool:
        """コンテナが起動しているか確認する。起動していればTrueで返る.していなければFalseで返る."""
        r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", self.name],
                           capture_output=True, text=True)
        return r.stdout.strip() == "true"

    def run(self, command: str, workdir: str, timeout: int, input: str = "") -> CommandResult:
        """コンテナ内でコマンドを実行する.

        inputにはタスクで渡されるeval_scriptを書き込んだ一時ファイルのパスが渡される.
        Args:
            command (str): 実行するコマンド
            workdir (str): 作業ディレクトリ
            timeout (int): タイムアウト時間（秒）
            input (str, optional): コマンドに渡す標準入力. Defaults to "".

        Returns:
            CommandResult: コマンドの実行結果
        """
        r = subprocess.run(
            ["docker", "exec", "-i", "-w", workdir, self.name,
             "timeout", "-s", "KILL", str(timeout), "bash", "-lc", command],
            input=input, capture_output=True, text=True)  # コンテナの中のコマンドを止めるためにtimeoutを設定
        # -i: inputをコンテナ内のコマンドのstdinに流す
        # bash -lc: ログインシェルとして起動し、イメージが用意したtestbedのconda環境を有効にする。
        # kILL: timeoutをSIGTERMからSIGKILLに変更
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

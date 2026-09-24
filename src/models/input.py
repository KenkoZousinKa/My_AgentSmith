from pydantic import BaseModel, Field


class MBPPTaskInput(BaseModel):
    """Input for MBPP task evaluation."""
    task_id: int
    task_definition: str
    function_definition: str
    test_imports: list[str] = Field(default_factory=list)
    test_list: list[str] = Field(default_factory=list)


class SWEBenchTaskInput(BaseModel):
    """Input for a SWE-bench task, provided by the moulinette.

    Your agent receives this and must produce a git patch that fixes
    the issue.
    """
    instance_id: str = Field(..., description="SWE-bench instance identifier (e.g., 'sympy__sympy-23534')")
    problem_statement: str = Field(..., description="The GitHub issue description, what needs to be fixed")
    docker_image: str = Field(..., description="Full Docker image name to pull "
                              "(e.g., 'swebench/sweb.eval.x86_64. sympy_1776_sympy-23534:latest')")
    eval_script: str = Field(..., description="Bash script to run inside the container to evaluate the patch")
    hints_text: str = Field(default="", description="Optional hints about the issue (may be empty)")
    repo: str = Field(default="", description="Repository name (e.g., 'sympy/sympy')")

# class MBPPTaskInput(BaseModel):
#     """MBPPタスク評価用の入力データ。"""
#     task_id: int = Field(..., description="タスクの識別ID")
#     task_definition: str = Field(..., description="解決すべき問題の説明文")
#     function_definition: str = Field(..., description="作成する関数のシグネチャ（書き出し部分）")
#     test_imports: List[str] = Field(default_factory=list, description="テスト実行に必要なインポート文のリスト")
#     test_list: List[str] = Field(default_factory=list, description="コードを検証するためのassert文のリスト")


# class SWEBenchTaskInput(BaseModel):
#     """moulinetteから提供されるSWE-benchタスクの入力データ。

#     エージェントはこれを受け取り、問題を修正するgitパッチを生成しなければならない。
#     """
#     instance_id: str = Field(..., description="SWE-benchのインスタンス識別子（例: 'sympy__sympy-23534'）")
#     problem_statement: str = Field(..., description="GitHubのissueの説明、修正すべき内容")
#     docker_image: str = Field(..., description="プルする完全なDockerイメージ名
#                               （例: 'swebench/sweb.eval.x86_64.sympy_1776_sympy-23534:latest'）")
#     eval_script: str = Field(..., description="パッチを評価するためにコンテナ内で実行するBashスクリプト")
#     hints_text: str = Field(default="", description="問題に関するオプションのヒント（空の場合もある）")
#     repo: str = Field(default="", description="リポジトリ名（例: 'sympy/sympy'）")

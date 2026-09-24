from pydantic import BaseModel, Field


class SandboxConfig(BaseModel):
    """Sandbox configuration for student solutions.

    Uses allowlist approach: only imports in authorized_imports are
    allowed. Everything else is blocked by default.
    """
    authorized_imports: list[str] = Field(default_factory=lambda: [
        "math", "math.*",
        "collections", "collections.*",
        "itertools", "re", "json",
        "typing", "typing.*",
        "functools", "operator",
        "heapq", "bisect", "copy",
        "string", "random",
        "datetime", "datetime.*",
        "array", "cmath",
    ])
    allowed_directories: list[str] = Field(default_factory=lambda: [
        "/testbed", "/tmp/agent"
    ])
    max_execution_time_seconds: int = 30
    max_memory_mb: int = 512

# class SandboxConfig(BaseModel):
#     """学生のソリューション用サンドボックス設定。

#     許可リスト（allowlist）アプローチを使用し、authorized_importsにあるインポートのみを許可する。
#     デフォルトではその他のすべてはブロックされる。
#     """

#     # ".*" で終わるエントリは、そのモジュールのサブモジュールのインポートも許可する
#     # （例: "collections.*" は collections.abc を許可する）[cite: 1]
#     authorized_imports: List[str] = Field(
#         default_factory=lambda: [
#             "math", "math.*",
#             "collections", "collections.*",
#             "itertools", "re", "json",
#             "typing", "typing.*",
#             "functools", "operator",
#             "heapq", "bisect", "copy",
#             "string", "random",
#             "datetime", "datetime.*",
#             "array", "cmath",
#         ]
#     )

#     # サンドボックス内のコードがアクセスを許可されるディレクトリのリスト[cite: 1]
#     allowed_directories: List[str] = Field(
#         default_factory=lambda: [
#             "/testbed", "/tmp/agent"
#         ]
#     )

#     # 実行の最大許容時間（秒）[cite: 1]
#     max_execution_time_seconds: int = 30

#     # 実行時の最大許容メモリ（MB）[cite: 1]
#     max_memory_mb: int = 512

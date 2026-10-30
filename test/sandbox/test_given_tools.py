"""外から渡したツール(tools=)が、サンドボックスの中で呼べることのテスト.

エージェントはMCPClientを自分で持ち、MCPToolFunctionの辞書をSandbox(tools=...)に渡す。
Sandboxが自分でMCPClientを持つ場合(mcp_stdio / mcp_server)と同じように、
名前が定義され、位置引数も入力スキーマの順に引数名へ割り当てられることを確かめる。
"""
from typing import Any

from src.models.sandbox_config import SandboxConfig
from src.sandbox.sandbox_main import Sandbox


class _SchemaTool:
    """MCPToolFunctionと同じく、input_schemaを持ち、キーワード引数で呼ばれるツール."""

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"text": {"type": "string"}, "times": {"type": "integer"}},
    }

    def __call__(self, **arguments: Any) -> str:
        """受け取った引数をそのまま文字列にして返す.

        Args:
            **arguments (Any): サンドボックスから届いた引数。

        Returns:
            str: textをtimes回つなげた文字列。
        """
        return str(arguments["text"]) * int(arguments["times"])


def test_given_tool_is_defined_in_the_sandbox() -> None:
    """tools=で渡したツールの名前が、サンドボックスの名前空間に定義される."""
    with Sandbox(config=SandboxConfig(), tools={"repeat_text": _SchemaTool()}) as sandbox:
        result = sandbox.run("print(repeat_text(text='ab', times=2))")
    assert result.error is None
    assert result.stdout == "abab\n"


def test_given_tool_maps_positional_arguments_by_schema_order() -> None:
    """位置引数は、入力スキーマのpropertiesの順に引数名へ割り当てられる."""
    with Sandbox(config=SandboxConfig(), tools={"repeat_text": _SchemaTool()}) as sandbox:
        result = sandbox.run("print(repeat_text('xy', 3))")
    assert result.error is None
    assert result.stdout == "xyxyxy\n"

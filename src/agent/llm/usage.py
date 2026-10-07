"""トークン使用量の抽出を担うモジュール.

1レスポンスから input / output トークン数を取り出す。
ステップ横断での合計(SolutionOutput.total_input_tokens 等)の積み上げはOrchestratorが担う。
"""
from typing import Any


def extract_token_usage(response_json: dict[str, Any], text: str) -> tuple[int, int]:
    """レスポンスJSONから input_tokens / output_tokens トークン数を抽出する.

    usage情報がない場合は、textの文字数をもとに概算する。

    Args:
        response_json (dict[str, Any]): LLMプロバイダのレスポンスJSON。
        text (str): レスポンスのテキスト部分。

    Returns:
        tuple[int, int]: input_tokensとoutput_tokensのタプル。
        usageがない場合 input_tokensは0、output_tokensは概算値を返す。
    """
    usage = response_json.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
        return prompt_tokens, completion_tokens

    # usage情報がない場合は、textの文字数をもとに概算。1トークンあたり4文字と仮定
    approx_tokens = max(1, len(text) // 4)
    # input_tokensは不明なので0、output_tokensは概算値
    return 0, approx_tokens

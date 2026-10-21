"""トークン使用量の抽出を担うモジュール.

1レスポンスから input / output トークン数を取り出す。
ステップ横断での合計(SolutionOutput.total_input_tokens 等)の積み上げはOrchestratorが担う。

思考トークンも出力トークンとして数えるため、
プロバイダのusage情報が実際より小さい場合は過小計上を防ぐため大きい方を採用する。
"""
import math
from typing import Any

_CHARS_PER_TOKEN = 3  # 1トークンあたりの文字数の概算値


def estimate_tokens_from_text(text: str) -> int:
    """文字列からトークン数を概算する.

    Args:
        text (str): トークン数を概算したい文字列。

    Returns:
        int: 概算トークン数。
    """
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _as_int(value: Any) -> int | None:
    """usage情報の値を整数に変換する.数値でなければNone.

    Args:
        value (Any): usage内の変換したい値。

    Returns:
        int | None: 整数に変換できる場合はその値、できない場合はNone。
    """
    # boolはintのサブクラスなので、isinstance(value, int)はTrueになるため、boolを先に除外する
    # strの場合は壊れたusage情報として扱い、Noneを返す
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None

    # NaN / 無限大はint()で例外になり、負の値はトークン数として不正なのでNoneを返す
    if not math.isfinite(value) or value < 0:
        return None
    return int(value)


def extract_token_usage(response_json: dict[str, Any], text: str) -> tuple[int, int]:
    """レスポンスJSONから input_tokens / output_tokens トークン数を抽出する.

    出力トークン数は、次の中で最も大きい値を採用する。
    - completion_tokens (LLMプロバイダのusage情報)
    - 報告がない / 0 なのに本文がある場合は、本文の文字数をもとに概算した値
    - total_tokens - prompt_tokens (思考トークンをcompletion_tokensに含めないプロバイダの場合)

    Args:
        response_json (dict[str, Any]): LLMプロバイダのレスポンスJSON。
        text (str): レスポンスのテキスト部分。

    Returns:
        tuple[int, int]: input_tokensとoutput_tokensのタプル。
        usageがない場合 input_tokensは0、output_tokensは概算値を返す。
    """
    # usage情報がある場合はそれを優先して使用する
    usage = response_json.get("usage")
    # usageがdictでない場合は空のdictに置き換える
    if not isinstance(usage, dict):
        usage = {}

    prompt_tokens = _as_int(usage.get("prompt_tokens"))
    completion_tokens = _as_int(usage.get("completion_tokens"))
    total_tokens = _as_int(usage.get("total_tokens"))

    # input_tokensはprompt_tokensがあればそれを使用、なければ0
    input_tokens = prompt_tokens if prompt_tokens is not None else 0

    # output_tokens
    # 1. completion_tokensがあればそれを使用、なければ0
    output_tokens = completion_tokens if completion_tokens is not None else 0

    # 2. 報告がない / 0 なのに本文がある場合は、本文の文字数をもとに概算した値
    if output_tokens == 0:
        output_tokens = estimate_tokens_from_text(text)

    # 3. 合計から入力を引いた値のほうが大きければそれを使用する(隠れた思考トークンを含めるため)
    if total_tokens is not None and prompt_tokens is not None:
        output_tokens = max(output_tokens, total_tokens - prompt_tokens)

    return input_tokens, output_tokens

"""LLMプロバイダの抽象クラスと設定情報を定義するモジュール。

1リクエストを送って結果 / 例外を返すだけ。
認証、リトライ、キーローテーション、フォールバックなどの機能はProvider / KeyManagerが担当。

OpenRouterProvider / GroqProvider / TogetherProvider / FireWorksProvider / GeminiProvider 等
具体的なプロバイダは、この抽象クラスを継承して実装する。
プロバイダURL / モデル名 / キー郡などはJSONか.envで設定し、コードの変更なしでモデルを差し替えて
ベンチマークを実行できるようにする。

- [ ] 抽象クラスはmodels/以下に移動、各プロバイダのサブクラスは別途provider/以下に配置。
"""
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ProviderConfig(BaseModel):
    """LLMプロバイダの設定情報。"""
    name: str
    description: str
    model_name: str
    api_key: str | None = None
    additional_params: dict[str, Any] = {}


class LLMResponse(BaseModel):
    """1回のLLM生成の結果。StepMetricsへ直結."""
    # コード抽出前の生のレスポンス文字列。LLMの出力をそのまま保持する。
    text: str
    # 生成に使用されたトークン数。usage.pyで集計する。
    input_tokens: int
    # 生成に使用されたトークン数。usage.pyで集計する。
    output_tokens: int
    # APIリクエストの応答時間(秒)をミリ秒単位で保持する。LLMの応答時間を計測する。
    request_time_ms: float
    # "https://openrouter.ai/api/v1"
    api_url: str
    model_name: str
    # 成功までのリトライ回数(0なら初回で成功)
    retries: int


class LLMProvider(ABC):
    """LLMプロバイダの抽象クラス。"""

    @abstractmethod
    def generate(self, messages: str, model_name: str, stop_sequences: str, max_tokens: int) -> LLMResponse:
        """LLMにリクエストを送信し、レスポンスを返す.

        Args:
            messages (str): LLMに送信するメッセージ
            model_name (str): 使用するモデルの名前
            stop_sequences (str): 生成を停止するトークンのリスト
            max_tokens (int): 生成する最大トークン数
            ...: その他のパラメータ

        Returns:
            LLMResponse: LLMのレスポンス情報
        """
        return LLMResponse(
            text="",
            input_tokens=0,
            output_tokens=0,
            request_time_ms=0.0,
            api_url="",
            model_name=model_name,
            retries=0
        )

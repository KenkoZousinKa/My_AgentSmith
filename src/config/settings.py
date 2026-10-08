"""既定 -> ファイル(providers.json / config.json) -> CLIの順で設定を読み込むモジュール.

config.jsonはpydantic-settingsのBaseSettingsで読む。
優先度: CLI(init) > config.json > 環境変数 > .env > コード既定値。
APIキーは.envからのみ。
providers.jsonにはキーの値ではなく、keys_env(env変数名)だけ書く。
providers.jsonは構造化データなので、pydanticでProviderConfigモデルに変換して扱う。
pydantic-settingsを使うと、環境変数やJSON/YAMLファイルから設定を読み込むことができる。
- [ ] Limits.time_margin_secのデフォルト値は実際の計測時間に合わせて調整。
"""
import json
from pathlib import Path
from typing import Any
from pydantic import BaseModel, ConfigDict
from pydantic_settings import (
    BaseSettings,
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict
)

from src.agent.llm.provider.provider import ProviderConfig


class Limits(BaseModel):
    """反復 / トークン / 時間のハード制限値.監視、打ち切りはlimits.pyで行う."""
    model_config = ConfigDict(extra="forbid")

    max_iterations: int = 10
    max_input_tokens: int = 6000
    max_output_tokens: int = 1500
    total_time_sec: float = 120.0
    time_margin_sec: float = 10.0


class SandboxSettings(BaseModel):
    """サンドボックス実行の設定."""
    model_config = ConfigDict(extra="forbid")

    exec_timeout_sec: float = 10.0
    memory_limit_mb: int = 512


class LoggingSettings(BaseModel):
    """ログ設定(レベル / 出力パス / トレース有無)."""
    model_config = ConfigDict(extra="forbid")

    level: str = "INFO"
    path: str = "logs/agent.log"
    trace: bool = False


class ManualSettings(BaseModel):
    """ツールマニュアルの詳細度"""
    model_config = ConfigDict(extra="forbid")

    verbosity: str = "concise"


class Settings(BaseSettings):
    """config.json + env + CLIの階層設定.

    sourceの優先度:
    init(CLI) > config.json > 環境変数 > .env > コード既定値
    """
    model_config = SettingsConfigDict(
        json_file="config.json",
        json_file_encoding="utf-8",
        env_prefix="AGENT_",
        env_nested_delimiter="__",
        extra="forbid",
    )

    limits: Limits = Limits()
    sandbox: SandboxSettings = SandboxSettings()
    logging: LoggingSettings = LoggingSettings()
    manual: ManualSettings = ManualSettings()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """設定ソースの優先度を定義する.

        Args:
            settings_cls (type[BaseSettings]): 設定クラスの型。
            init_settings (PydanticBaseSettingsSource): CLI引数などの初期化設定。
            env_settings (PydanticBaseSettingsSource): 環境変数からの設定。
            dotenv_settings (PydanticBaseSettingsSource): .envファイルからの設定。
            file_secret_settings (PydanticBaseSettingsSource): ファイルシークレットからの設定。
        Returns:
            tuple[PydanticBaseSettingsSource, ...]: 設定ソースの優先度。
        """
        return (
            init_settings,
            JsonConfigSettingsSource(settings_cls),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )


def load_providers(providers_path: str = "providers.json") -> list[ProviderConfig]:
    """providers.jsonを読み込んでProviderConfigのリストに変換する.

    Args:
        providers_path (str): providers.jsonのパス。デフォルトは"providers.json"。

    Returns:
        list[ProviderConfig]: 読み込んだプロバイダ設定のリスト。

    Raises:
        FileNotFoundError: providers.jsonが存在しない、または空の場合。
        ValueError: providers.jsonに'providers'エントリがない場合。
    """
    path = Path(providers_path)
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(f"providers.json not found or empty: {providers_path}")

    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    entries: list[dict[str, Any]] = raw.get("providers", [])
    if not entries:
        raise ValueError(f"providers.json has no 'providers' entries: {providers_path}")

    providers: list[ProviderConfig] = [ProviderConfig(**entry) for entry in entries]
    return sorted(providers, key=lambda provider: provider.priority)  # priorityが小さい順にソートして返す


def select_provider(
    providers: list[ProviderConfig],
    model_name: str | None = None,
    provider_url: str | None = None
) -> ProviderConfig:
    """primaryプロバイダを1つ選ぶ。CLI引数で指定された場合はそれを優先する。

    priorityが最小を最優先し、--model_name / --provider_urlで指定された場合は上書きする。
    keys_envは主エントリのまま。
    残りのプロバイダはフォールバック用に保持する。
    """
    if not providers:
        raise ValueError("No providers available to select from.")

    primary = providers[0]  # priorityが最小のものをprimaryとする
    updates: dict[str, Any] = {}
    if provider_url:
        updates["provider_url"] = provider_url
    if model_name:
        updates["model"] = model_name

    return primary.model_copy(update=updates) if updates else primary


def load_settings(**cli_overrides: Any) -> Settings:
    """Settingsを構築して返す.

    config.json + env + CLI overridesを階層的に読み込む。

    Args:
        **cli_overrides: CLIからの上書き
    """
    return Settings(**cli_overrides)

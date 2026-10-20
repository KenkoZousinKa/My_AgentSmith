"""既定 -> ファイル(providers.json / config.json) -> CLIの順で設定を読み込むモジュール.

config.jsonはpydantic-settingsのBaseSettingsで読む。
優先度: CLI(init) > config.json > 環境変数 > .env > コード既定値。
APIキーは.envからのみ。
providers.jsonにはキーの値ではなく、keys_env(env変数名)だけ書く。
providers.jsonは構造化データなので、pydanticでProviderConfigモデルに変換して扱う。
pydantic-settingsを使うと、環境変数やJSON/YAMLファイルから設定を読み込むことができる。
- [ ] Limits.time_margin_secのデフォルト値は実際の計測時間に合わせて調整。

下記を提供
Limits
SandboxSettings
LoggingSettings
ManualSettings
RetrySettings
Settings
"""
import json
from urllib.parse import urlsplit
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
    max_output_tokens_per_iteration: int = 500
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


class RetrySettings(BaseModel):
    """ResilientLLMClientのリトライ / バックオフ設定.

    Attributes:
        max_retries_per_key (int): 1つのAPIキーでの最大リトライ回数。初回除くデフォルト2回。
        backoff_base_seconds (float): バックオフの基本秒数。指数バックオフの基準値。デフォルト1秒。
        backoff_max_seconds (float): バックオフの1回あたりの上限、最大秒数。デフォルト8秒。
        safety_margin_seconds (float): 時間予算からこの分を引いた範囲でしか持たない。
    """
    model_config = ConfigDict(extra="forbid")

    max_retries_per_key: int = 2
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 8.0
    safety_margin_seconds: float = 2.0


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
    retry: RetrySettings = RetrySettings()

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


def load_providers(providers_path: str) -> list[ProviderConfig]:
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


def _host_name(provider_url: str) -> str:
    """URLからホスト名を小文字で抽出し返す.

    Args:
        provider_url (str): プロバイダのURL。

    Returns:
        str: URLから抽出したホスト名（小文字）。
    """
    return (urlsplit(provider_url.strip()).hostname or "").lower()


def order_providers(
    providers: list[ProviderConfig],
    model_name: str | None = None,
    provider_url: str | None = None
) -> list[ProviderConfig]:
    """CLI引数(--model_name / --provider-url)を反映した、試す順番のプロバイダ設定リストを返す.

    使っていい「URLとキーの組」はproviders.jsonに書いているものだけで推測、キーの流用はしない。
    - 指定がなければproviders.jsonのpriorityの順番で返す。
    - provider_urlが指定されていれば、ホスト名が同じプロバイダを先頭にし、そのプロバイダのキー(keys_env)と、
    モデル別のパラメーターをそのまま使う。
    - --model-nameは設定ファイルにないモデルでも、そのプロバイダの先頭で試す。
    - URLの指定がされているときは、モデル名でプロパイダを探さない。
    - --model-nameが指定されていれば、指定されたモデル名を持つプロバイダを先頭にする。
    - 指定モデルはそのプロバイダの先頭に置き、同じプロバイダの他のモデルと他のプロバイダはフォールバックに残す。

    Args:
        providers (list[ProviderConfig]): 先頭が優先度の高い順に並んだプロバイダ設定リスト。
        model_name (str | None): CLIで指定されたモデル名。
        provider_url (str | None): CLIで指定されたプロバイダURL。

    Returns:
        list[ProviderConfig]: ホスト名でソートされたプロバイダ設定リスト。
    """
    # providersが空ならValueErrorを投げる
    if not providers:
        raise ValueError("No providers available to select from.")

    # model_nameもprovider_urlも指定されていなければ、providers.jsonのpriority順のまま返す
    if not model_name and not provider_url:
        return providers

    # provider_urlが指定されていれば、ホスト名が同じプロバイダを先頭にする
    if provider_url:
        host = _host_name(provider_url)
        matched = next(
            (index for index, provider in enumerate(providers) if host and _host_name(provider.provider_url) == host),
            None
        )
        # provider_urlが指定されているのに、providers.jsonにそのURLのホスト名が無ければValueErrorを投げる
        if matched is None:
            raise ValueError(
                f"--provider-url {provider_url} is not found in providers.json "
                 "Add an entry with its keys_env to use it."
             )
    # provider_urlが指定されていなければ、model_nameを持つプロバイダを先頭にする
    else:
        matched = next(
            (index for index, provider in enumerate(providers) if model_name in provider.models),
            None
        )
        # model_nameが指定されているのに、providers.jsonにそのモデル名を持つプロバイダが無ければValueErrorを投げる
        if matched is None:
            raise ValueError(
                f"--model-name {model_name!r} is not found in providers.json "
                 "Add it to a provider`s models, or pass --provider-url as well."
             )

    # matchedで見つかったプロバイダを先頭にして、残りは元の順番のまま返す
    base = providers[matched]
    updates: dict[str, Any] = {}
    # provider_urlが指定されていれば、先頭のプロバイダのURLを上書きする
    if provider_url:
        updates["provider_url"] = provider_url
    # model_nameが指定されていれば、先頭のプロバイダのmodelsを上書きする
    if model_name:
        updates["models"] = [model_name, *[model for model in base.models if model != model_name]]

    # matchedで見つかったプロバイダを上書きコピーして先頭に置く
    first = base.model_copy(update=updates)
    # matchedで見つかったプロバイダを除いた残りのプロバイダを元の順番のまま返す
    rest = [provider for index, provider in enumerate(providers) if index != matched]

    return [first, *rest]


def load_settings(**cli_overrides: Any) -> Settings:
    """Settingsを構築して返す.

    config.json + env + CLI overridesを階層的に読み込む。

    Args:
        **cli_overrides: CLIからの上書き
    """
    return Settings(**cli_overrides)

"""config/settings の読み込み・選択・階層の検証(pydantic-settings)."""
import json
from pathlib import Path

import pytest

from src.agent.llm.resilient_client import ResilientLLMClient
from src.agent.llm.transport.transport import HttpResponse, HttpTransport
from src.config.settings import RetrySettings, Settings, load_settings
from src.config.settings import load_providers, order_providers


def _write(path: Path, obj: object) -> str:
    path.write_text(json.dumps(obj), encoding="utf-8")
    return str(path)


def test_load_settings_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """config.jsonが無ければ既定値(CWDにファイル無し)."""
    monkeypatch.chdir(tmp_path)
    settings = load_settings()
    assert settings.limits.max_input_tokens == 6000
    assert settings.manual.verbosity == "concise"


def test_load_settings_reads_config_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """config.jsonの値が既定を上書き、未指定フィールドは既定のまま."""
    (tmp_path / "config.json").write_text(
        json.dumps({"limits": {"max_iterations": 3}}), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    settings = load_settings()
    assert settings.limits.max_iterations == 3        # ファイル値
    assert settings.limits.max_input_tokens == 6000   # 未指定は既定


def test_cli_override_is_highest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """CLI(init) が config.json より優先される(D29最優先)."""
    (tmp_path / "config.json").write_text(
        json.dumps({"limits": {"max_iterations": 3}}), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    settings = load_settings(limits={"max_iterations": 7})
    assert settings.limits.max_iterations == 7


def test_settings_rejects_unknown_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """未知キーは extra=forbid で ValidationError."""
    (tmp_path / "config.json").write_text(
        json.dumps({"limits": {"max_iteration": 3}}), encoding="utf-8"  # sが無い
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(Exception):  # pydantic.ValidationError
        load_settings()


# --- providers 系(07 §4のまま。パス引数で渡すので chdir 不要) ---
_PROVIDERS = {
    "providers": [
        {"name": "groq", "provider_url": "https://api.groq.com/openai/v1",
         "models": ["llama-3.3-70b-versatile"], "keys_env": "GROQ_API_KEY", "priority": 2,
         "model_params": {"llama-3.3-70b-versatile": {"temperature": 0.0}}},
        {"name": "openrouter", "provider_url": "https://openrouter.ai/api/v1",
         "models": ["qwen/qwen3-235b-a22b-2507"], "keys_env": "OPENROUTER_API_KEY", "priority": 1},
    ]
}


def test_load_providers_sorted_by_priority(tmp_path: Path) -> None:
    """priority昇順で先頭が主(openrouter)."""
    providers = load_providers(_write(tmp_path / "providers.json", _PROVIDERS))
    assert [p.name for p in providers] == ["openrouter", "groq"]


def test_order_providers_without_cli_keeps_priority(tmp_path: Path) -> None:
    """指定が無ければpriority順のまま."""
    providers = load_providers(_write(tmp_path / "providers.json", _PROVIDERS))
    assert [provider.name for provider in order_providers(providers)] == ["openrouter", "groq"]


def test_order_providers_known_url_uses_that_providers_key(tmp_path: Path) -> None:
    """--provider-url が既知のプロバイダなら、そのキーとモデル別パラメータで指定モデルを先頭に試す.

    指定モデル(x/y)がproviders.jsonに無くても試す。末尾のスラッシュ・ホスト名の大文字は無視して照合する。
    主エントリ(openrouter)のキーは使わない。
    """
    providers = load_providers(_write(tmp_path / "providers.json", _PROVIDERS))
    ordered = order_providers(providers, model_name="x/y", provider_url="https://API.GROQ.com/openai/v1/")
    assert ordered[0].name == "groq"
    assert ordered[0].keys_env == "GROQ_API_KEY"
    assert ordered[0].provider_url == "https://API.GROQ.com/openai/v1/"
    assert ordered[0].models == ["x/y", "llama-3.3-70b-versatile"]
    assert ordered[0].model_params == {"llama-3.3-70b-versatile": {"temperature": 0.0}}
    assert [provider.name for provider in ordered[1:]] == ["openrouter"]


def test_order_providers_known_url_only_moves_provider_first(tmp_path: Path) -> None:
    """--provider-url だけなら、そのプロバイダを先頭にし、モデルはproviders.jsonのまま."""
    providers = load_providers(_write(tmp_path / "providers.json", _PROVIDERS))
    ordered = order_providers(providers, provider_url="https://api.groq.com/openai/v1")
    assert [provider.name for provider in ordered] == ["groq", "openrouter"]
    assert ordered[0].models == ["llama-3.3-70b-versatile"]


def test_order_providers_model_name_only_moves_owner_first(tmp_path: Path) -> None:
    """URLの指定が無ければ、モデル名を持つプロバイダを先頭にする(重複させない)."""
    providers = load_providers(_write(tmp_path / "providers.json", _PROVIDERS))
    ordered = order_providers(providers, model_name="llama-3.3-70b-versatile")
    assert [provider.name for provider in ordered] == ["groq", "openrouter"]
    assert ordered[0].models == ["llama-3.3-70b-versatile"]


def test_order_providers_unknown_model_only_is_rejected(tmp_path: Path) -> None:
    """--model-name だけで、どのプロバイダにも無いモデルなら ValueError(黙って別のモデルで解かない)."""
    providers = load_providers(_write(tmp_path / "providers.json", _PROVIDERS))
    with pytest.raises(ValueError, match="x/y"):
        order_providers(providers, model_name="x/y")


@pytest.mark.parametrize("provider_url", [
    "https://api.together.xyz/v1",
    "http://provider.api/v1",
    "http://localhost:11434/v1",
    "http://127.0.0.1:8000/v1",
])
@pytest.mark.parametrize("model_name", [None, "m", "llama-3.3-70b-versatile"])
def test_order_providers_unknown_url_is_rejected(tmp_path: Path, provider_url: str, model_name: str | None) -> None:
    """providers.json に無いURLは、モデル名が既知でも未知でも無くても ValueError(どのキーも送らない)."""
    providers = load_providers(_write(tmp_path / "providers.json", _PROVIDERS))
    with pytest.raises(ValueError, match="provider-url"):
        order_providers(providers, model_name=model_name, provider_url=provider_url)


def test_order_providers_rejects_empty_list() -> None:
    """プロバイダが1つも無ければ ValueError."""
    with pytest.raises(ValueError):
        order_providers([], model_name="m")


class _RecordingTransport(HttpTransport):
    """送ったURLとAuthorizationヘッダを記録し、常に200を返すTransport."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def post(self, url: str, headers: dict[str, str], data: str, timeout: float = 60.0) -> HttpResponse:
        """送り先とキーを記録して、成功のレスポンスを返す."""
        self.sent.append((url, headers["Authorization"]))
        body = {"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        return HttpResponse(status=200, body=json.dumps(body))


def test_cli_provider_url_sends_that_providers_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """配線の回帰: --provider-url で groq を指定したら、groq のURLへ groq のキーが送られる(実際のProviderで確認)."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-openrouter")
    monkeypatch.setenv("GROQ_API_KEY", "sk-groq")
    providers = load_providers(_write(tmp_path / "providers.json", _PROVIDERS))
    transport = _RecordingTransport()
    client = ResilientLLMClient(
        providers=order_providers(providers, model_name="x/y", provider_url="https://api.groq.com/openai/v1"),
        transport=transport,
        retry=RetrySettings(),
    )
    client.generate([{"role": "user", "content": "hi"}], [], 16)
    assert transport.sent == [("https://api.groq.com/openai/v1/chat/completions", "Bearer sk-groq")]


def test_shipped_config_files_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    """リポジトリ直下の実 config.json / providers.json がそのままロードできる(出荷物の回帰)."""
    repo_root = Path(__file__).resolve().parents[2]   # test/agent/ の2つ上 = リポジトリ直下
    assert (repo_root / "config.json").is_file()        # 直下を指せていないと、既定値で黙って通ってしまう
    monkeypatch.chdir(repo_root)                        # Settings は CWD の config.json を読む
    settings = load_settings()
    assert settings.limits.max_input_tokens == 6000
    assert settings.logging.level == "INFO"
# test_shipped_config_files_parse:
    providers = load_providers(str(repo_root / "providers" / "providers.json"))
    assert providers[0].priority == 1                   # priority昇順で先頭が主


def test_load_providers_accepts_model_params(tmp_path: Path) -> None:
    """providers.json に model_params を書ける(ProviderConfig は extra=forbid なので、欄が無いと読込で落ちる)."""
    entry = {
        "name": "groq", "provider_url": "https://api.groq.com/openai/v1",
        "models": ["openai/gpt-oss-20b", "qwen/qwen3-32b"], "keys_env": "GROQ_API_KEY",
        "model_params": {"openai/gpt-oss-20b": {"reasoning_effort": "low"}},
    }
    providers = load_providers(_write(tmp_path / "providers.json", {"providers": [entry]}))
    assert providers[0].model_params == {"openai/gpt-oss-20b": {"reasoning_effort": "low"}}

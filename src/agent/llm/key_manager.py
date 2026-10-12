"""マルチキー・ローテ・フォールバックを管理する、LLMプロバイダのモジュール.

プロバイダごとの複数のAPIキーを管理し、リクエストごとに適切なキーを選択する。
通常時はキーを優先度順にローテーション。
429 / quota / rate-limit -> 次のキーに切り替え、記録しリトライ。
同プロバイダのすべてのキーが枯渇 -> 別プロバイダにフォールバック。
リトライ上限に達した場合は例外を返す。
- [ ] 現状はMVPで単一のキーのみ解決。
- [ ] マルチキー、ローテーション、プロバイダのフォールバックは後々実装。
"""
import os


def resolve_api_key(keys_env: str) -> str:
    """env変数名 keys_env から実APIキーを取得する.

    Args:
        keys_env (str): APIキーを格納した環境変数名。

    Returns:
        str: APIキー文字列。

    Raises:
        KeyError: 指定された環境変数が存在しない / 未設定の場合。
    """
    # 環境変数からAPIキーを取得
    key = os.environ.get(keys_env)
    # 環境変数が存在しない / 未設定の場合は KeyError を送出
    if not key:
        raise KeyError(f"Environment variable '{keys_env}' is not set.")

    return key


def resolve_api_keys(keys_env: str) -> list[str]:
    """連番サフィックス付きの環境変数から複数のAPIキーを取得する.

    基準名 keys_env ('GROQ_API_KEY')を先頭に
    '{keys_env}_2, '_3', ...を連番が途切れるまで取得する。
    各値はstripし、空文字 / 未設定は除外する。重複は順序を保って除去。

    Args:
        keys_env (str): APIキーを格納した環境変数名。

    Returns:
        list[str]: APIキー文字列のリスト(優先度順)。一本もなければ空リストを返す。
    """
    collected_keys: list[str] = []

    # 基準名の環境変数を取得
    base_key = os.environ.get(keys_env)
    if base_key:
        collected_keys.append(base_key.strip())

    # 連番サフィックス付きの環境変数を取得
    index = 2
    while True:
        raw_key = os.environ.get(f"{keys_env}_{index}")
        if not raw_key or not raw_key.strip():
            break
        collected_keys.append(raw_key.strip())
        index += 1

    # 重複を除去し、順序を保つ
    seen_keys: set[str] = set()
    unique_keys: list[str] = []
    for key in collected_keys:
        if key not in seen_keys:
            seen_keys.add(key)
            unique_keys.append(key)

    return unique_keys

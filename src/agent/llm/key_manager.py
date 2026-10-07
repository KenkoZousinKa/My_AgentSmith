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
    key = os.environ.get(keys_env)
    if not key:
        raise KeyError(f"Environment variable '{keys_env}' is not set.")
    return key

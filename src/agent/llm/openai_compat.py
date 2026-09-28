"""OpenAI互換のAPIを提供するプロバイダを統一的に扱うためのモジュール。

OpenRouter / Groq / Together / FireWorksなど。
リクエスト成形->送信->レスポンス成形
tokensはusage.pyで集計する、なければ概算。
-> LLMResponseを返す。リトライ、キー選択はkey_manager.pyに任せる。
"""

"""Application settings, loaded from environment / .env file.

Also exports the required API keys into ``os.environ`` so the underlying
LangChain integrations (ChatGroq, TavilySearch) pick them up automatically.
"""

from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- credentials ---
    groq_api_key: str = ""
    tavily_api_key: str = ""

    # --- model ---
    # NOTE: confirm a currently-served model at https://console.groq.com/docs/models
    groq_model: str = "openai/gpt-oss-120b"
    temperature: float = 0.3

    # --- behaviour ---
    max_search_results: int = 5
    max_subquestions: int = 5
    max_factcheck_retries: int = 1

    @property
    def keys_present(self) -> bool:
        return bool(self.groq_api_key) and bool(self.tavily_api_key)

    def missing_keys(self) -> list[str]:
        missing = []
        if not self.groq_api_key:
            missing.append("GROQ_API_KEY")
        if not self.tavily_api_key:
            missing.append("TAVILY_API_KEY")
        return missing


settings = Settings()

# Make keys visible to the LangChain integrations, which read them from env.
if settings.groq_api_key:
    os.environ["GROQ_API_KEY"] = settings.groq_api_key
if settings.tavily_api_key:
    os.environ["TAVILY_API_KEY"] = settings.tavily_api_key

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    gemini_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    gemini_model: str = "gemini-3.5-flash"
    gemini_lite_model: str = "gemini-3.5-flash-lite"

    exa_api_key: str = ""
    exa_mcp_url: str = "https://mcp.exa.ai/mcp"
    kiwi_mcp_url: str = "https://mcp.kiwi.com"
    duffel_access_token: str = ""

    data_mode: Literal["replay", "live"] = "replay"
    replay_scenario: str = "storm_ord"


@lru_cache
def settings() -> Settings:
    return Settings()

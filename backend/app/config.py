from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://commander:commander_pw@localhost:5433/commander_os"

    anthropic_api_key: str = ""
    google_api_key: str = ""
    llm_provider: str = "gemini"  # anthropic | gemini
    llm_model: str = "gemini-3.5-flash"
    llm_mock: bool = True

    # per-agent overrides: "provider:model" (e.g. "anthropic:claude-fable-5").
    # CEO thinks on Claude Fable 5 when an Anthropic key is present; falls back to default.
    ceo_model: str = "anthropic:claude-fable-5"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_mock: bool = True

    meta_agent_url: str = "http://localhost:8000"
    meta_agent_mock: bool = True

    price_input_thb_per_mtok: float = 110.0
    price_output_thb_per_mtok: float = 550.0

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://commander:commander_pw@localhost:5433/commander_os"

    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-20250514"
    llm_mock: bool = True

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

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    simulator_url: str = "http://localhost:8000"
    operator_key: str = "change-me"
    database_url: str = "sqlite:///./data/gta7.db"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # sync loop
    poll_interval_s: float = 1.0
    demand_history_limit: int = 2000

    # resilience
    sim_timeout_s: float = 4.0
    sim_retries: int = 3
    breaker_threshold: int = 5
    breaker_cooldown_s: float = 10.0

    # decision mode defaults
    decision_mode: str = "manual"  # manual | assisted
    auto_confidence_threshold: float = 0.8
    auto_max_quantity: float = 5000.0

    # LLM (used by app.intel.genai)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    groq_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    simulator_url: str = "http://localhost:8000"
    # all    = single process (dev): engine + API
    # engine = the single writer: tick loop, approvals, mode, chaos, live stream
    # api    = stateless read replica: serves reads from the engine's shared snapshot (scale this one)
    role: str = "all"
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
    decision_mode: str = "manual"  # manual | assisted | auto
    auto_confidence_threshold: float = 0.8
    auto_max_quantity: float = 5000.0
    auto_min_risk_drop: float = 0.20  # auto mode: approve when stockout risk falls by >= 20 points

    # LLM (used by app.intel.genai): OpenAI first, then Gemini, then Groq, then templates
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    groq_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()

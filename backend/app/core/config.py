# This file is responsible for loading settings from a .env file (or using 
# built-in defaults if a value is missing). Instead of hardcoding urls, 
# passwords, etc. everywhere they're needed in the code, this file reads 
# them once and makes them available anywhere in the app.

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
        
    PROJECT_NAME: str = "Autonomous Travel Disruption Concierge"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    DATABASE_URL: str = "sqlite+aiosqlite:///./travel_concierge.db"

    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_CHANNEL: str = "flight_events"

    SECRET_KEY: str = "supersecret_dev_key_change_in_production_environment_please"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    CORS_ORIGINS: str = ""
    DEMO_API_KEY: str = ""

    # Policy Thresholds
    POLICY_MAX_FARE_DELTA_INR: float = 5000.0
    POLICY_MAX_ARRIVAL_DELAY_HOURS: float = 3.0
    POLICY_MIN_AIRPORT_BUFFER_MINUTES: int = 45
    POLICY_MIN_CONNECTION_BUFFER_MINUTES: int = 45

    # LLM Settings & Models (driven by env vars; no hardcoded model name defaults)
    LLM_PROVIDER: str = "google"
    LLM_MODEL: str = ""
    LLM_GRADER_MODEL: str = "gemini-1.5-pro"
    LLM_COMPARE_MODELS: str = "gemini-1.5-flash,gemini-1.5-pro"
    GOOGLE_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    LLM_TEMPERATURE: float = 0.0

    # Agent Loop & Timeout Guardrails
    MAX_AGENT_STEPS: int = 6
    MAX_REVISIONS: int = 3
    MAX_LLM_CALLS_PER_EVENT: int = 6
    RUN_LIVE_LLM: int = 0
    LLM_TIMEOUT_SECONDS: float = 30.0
    PIPELINE_TIMEOUT_SECONDS: float = 90.0
    LLM_MAX_CONCURRENCY: int = 1
    LLM_MIN_INTERVAL_MS: int = 1000
    LLM_MAX_RETRIES: int = 3
    LLM_MODEL_LIMITS: str = (
        '{"gemini-3.5-flash-lite": {"rpm": 15, "rpd": 500}, '
        '"gemini-3.1-flash-lite": {"rpm": 15, "rpd": 500}, '
        '"gemini-3.6-flash": {"rpm": 5, "rpd": 20}, '
        '"gemini-3.7-flash": {"rpm": 5, "rpd": 20}, '
        '"gemini-3.8-flash": {"rpm": 5, "rpd": 20}, '
        '"gemini-3-flash": {"rpm": 5, "rpd": 20}}'
    )

    # Token, Cost & Daily Budget Settings
    MAX_TOKENS_PER_CALL: int = 2048
    DAILY_LLM_BUDGET_USD: float = 10.0
    DAILY_LLM_CALL_LIMIT: int = 100
    LLM_PRICE_INPUT_PER_MTOK_USD: float = 0.075
    LLM_PRICE_OUTPUT_PER_MTOK_USD: float = 0.30
    USD_TO_INR: float = 85.0  # Approximate conversion rate for UI/display metrics (manual setting)


    # Notifier / Email Config
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAILS_FROM_EMAIL: str = "concierge@reroute.travel"
    SENDGRID_API_KEY: str = ""

    # Poller
    POLLER_INTERVAL_SECONDS: int = 60

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore" 
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()


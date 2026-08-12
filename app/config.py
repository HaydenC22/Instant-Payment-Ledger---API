from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Instant Payment Ledger & API"
    environment: str = "local"

    database_url: str = "postgresql+asyncpg://ledger:ledger@localhost:5432/ledger"

    idempotency_key_header: str = "Idempotency-Key"

    webhook_max_attempts: int = 8
    webhook_backoff_base_seconds: float = 2.0
    webhook_backoff_max_seconds: float = 900.0


@lru_cache
def get_settings() -> Settings:
    return Settings()

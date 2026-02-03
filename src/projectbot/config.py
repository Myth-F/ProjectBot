from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    environment: str = "dev"
    log_level: str = "INFO"

    discord_token: str | None = Field(default=None, alias="DISCORD_TOKEN")

    database_url: str = Field(
        default="postgresql+asyncpg://projectbot:projectbot@db:5432/projectbot",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")

    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")

    worker_interval_seconds: int = Field(default=5, alias="WORKER_INTERVAL_SECONDS")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

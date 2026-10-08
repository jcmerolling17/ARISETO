from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """App settings, read from the environment or the repository's .env file."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    database_url: str
    test_database_url: str | None = None
    secret_key: str
    access_token_expire_minutes: int = 60 * 24 * 7
    jwt_algorithm: str = "HS256"
    frontend_dir: Path = REPO_ROOT / "frontend" / "public"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()

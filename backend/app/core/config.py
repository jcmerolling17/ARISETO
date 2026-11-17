from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "backend"


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
    # Optional so the API starts without it; weather fetching then reports missing_key.
    # SecretStr keeps the value out of reprs and logs.
    openweathermap_api_key: SecretStr | None = None

    # Disease detection model (Section 6, "Disease detection runtime (Phase 10)"). Read as
    # text and checked when the model loads, so a missing or bad value never stops the API:
    # disease detection is then off and POST /diagnoses answers 503 model_unavailable.
    disease_model_path: str | None = None
    disease_labels_path: str | None = None
    disease_model_version: str | None = None
    disease_confidence_threshold: str | None = None
    # Chatbot intent model (Section 6, "Chatbot runtime (Phase 12)"), read the same way: without
    # it the API runs and POST /chat/messages answers 503 model_unavailable.
    chatbot_model_path: str | None = None
    chatbot_labels_path: str | None = None
    chatbot_model_version: str | None = None
    chatbot_confidence_threshold: str | None = None
    # Leaf photos, stored as leaf/YYYY/MM/<diagnosis_id>.<ext> under this folder.
    leaf_image_dir: Path = BACKEND_DIR / "var" / "leaf_images"

    @field_validator(
        "disease_model_path",
        "disease_labels_path",
        "disease_model_version",
        "disease_confidence_threshold",
        "chatbot_model_path",
        "chatbot_labels_path",
        "chatbot_model_version",
        "chatbot_confidence_threshold",
        mode="before",
    )
    @classmethod
    def _empty_is_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    @field_validator("leaf_image_dir", mode="before")
    @classmethod
    def _leaf_dir(cls, value: object) -> object:
        """Empty means the default; a relative path is relative to backend/."""
        if value is None or (isinstance(value, str) and not value.strip()):
            return BACKEND_DIR / "var" / "leaf_images"
        path = Path(str(value).strip())
        return path if path.is_absolute() else BACKEND_DIR / path

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()

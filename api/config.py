from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration. Override via env vars (prefix ``UNDERSERVED_``)
    or a local ``.env`` file. e.g. ``UNDERSERVED_CORS_ORIGINS='["https://x"]'``.
    """

    model_config = SettingsConfigDict(
        env_prefix="UNDERSERVED_", env_file=".env", extra="ignore"
    )

    serving_dir: Path = PROJECT_ROOT / "serving" / "data"
    cors_origins: list[str] = ["*"]  # tighten to the real frontend origin in prod
    title: str = "NYC Underservice Risk Index API"
    version: str = "0.1.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()

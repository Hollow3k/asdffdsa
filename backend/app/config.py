"""Application configuration, read from environment variables (see .env.example)."""

from __future__ import annotations

from datetime import date
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Persistence -------------------------------------------------------
    # SQLite for local development, e.g. postgresql+psycopg://user:pw@host:5432/db for deployment.
    database_url: str = "sqlite:///./data/wind.db"

    # --- Elexon Insights Solution (BMRS) API ------------------------------
    elexon_base_url: str = "https://data.elexon.co.uk/bmrs/api/v1"
    elexon_timeout_seconds: float = 45.0
    elexon_max_retries: int = 4
    elexon_backoff_base_seconds: float = 1.0
    elexon_backoff_max_seconds: float = 20.0

    # --- HTTP / CORS -------------------------------------------------------
    # Comma separated list of allowed browser origins.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    log_level: str = "INFO"

    # --- Domain defaults ---------------------------------------------------
    default_calibration_start: date = date(2025, 10, 1)
    default_calibration_end: date = date(2025, 12, 31)
    decision_window_start: date = date(2026, 1, 1)
    decision_window_end: date = date(2026, 1, 31)
    default_cutoff_time: str = "17:00"
    # A calibration needs at least this many matched hourly pairs to be usable.
    min_calibration_pairs: int = 72
    # Below this many pairs, statistics are flagged as low-confidence.
    low_sample_pairs: int = 500
    # Per-bucket (e.g. hour-of-day) sample size under which a bucket is flagged.
    low_sample_bucket: int = 30
    max_calibration_days: int = 400

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

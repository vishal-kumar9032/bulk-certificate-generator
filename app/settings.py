import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database configuration (SQLite default, easily swappable to PostgreSQL)
    DATABASE_URL: str = "sqlite:///./certificates.db"

    # Storage directory for generated certificates and temporary artifacts
    STORAGE_DIR: Path = Path("./storage")

    # In-process worker thread pool size
    WORKER_THREADS: int = 4

    # Maximum allowed recipients per single bulk request
    MAX_RECIPIENTS_PER_JOB: int = 1000

    # Synchronous processing mode (useful for deterministic testing)
    SYNC_MODE: bool = False

    # Directory for bundled fonts
    FONTS_DIR: Path = Path(__file__).resolve().parent / "assets" / "fonts"


# Global settings singleton
settings = Settings()

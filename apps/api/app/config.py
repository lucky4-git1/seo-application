"""Centralized application configuration. Single place that reads env vars."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_files() -> tuple:
    """Resolve .env regardless of CWD: prefer repo-root .env, fall back to CWD."""
    files: list = []
    # config.py lives at <root>/apps/api/app/config.py -> root is parents[3]
    root_env = Path(__file__).resolve().parents[3] / ".env"
    if root_env.exists():
        files.append(root_env)
    cwd_env = Path.cwd() / ".env"
    if cwd_env not in files:
        files.append(cwd_env)
    return tuple(files)


class DatabaseConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")
    database_url: str = Field(default="postgresql+psycopg://seo:seo@localhost:5432/seo", alias="DATABASE_URL")


class RedisConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")


class SecurityConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")
    jwt_secret: str = Field(default="change-me-in-production-min-32-chars", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=60, alias="JWT_EXPIRE_MINUTES")


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=_env_files(), env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="SEO Intelligence Platform", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")
    cors_origins: str = Field(default="http://localhost:5173,http://localhost:5174,http://localhost:1420", alias="CORS_ORIGINS")

    database_url: str = Field(default="postgresql+psycopg://seo:seo@localhost:5432/seo", alias="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    jwt_secret: str = Field(default="change-me-in-production-min-32-chars", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=60, alias="JWT_EXPIRE_MINUTES")

    celery_broker_url: str = Field(default="redis://localhost:6379/0", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://localhost:6379/1", alias="CELERY_RESULT_BACKEND")

    google_client_id: str | None = Field(default=None, alias="GOOGLE_CLIENT_ID")
    google_client_secret: str | None = Field(default=None, alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str | None = Field(default=None, alias="GOOGLE_REDIRECT_URI")

    export_dir: str = Field(default="/tmp/seo-exports", alias="EXPORT_DIR")

    # Presentation mode and crawler settings
    presentation_mode: bool = Field(default=True, alias="PRESENTATION_MODE")
    audit_concurrency: int = Field(default=12, alias="AUDIT_CONCURRENCY")
    audit_max_runtime: int = Field(default=180, alias="AUDIT_MAX_RUNTIME")
    audit_timeout_total: float = Field(default=20.0, alias="AUDIT_TIMEOUT_TOTAL")
    audit_timeout_connect: float = Field(default=5.0, alias="AUDIT_TIMEOUT_CONNECT")
    audit_timeout_read: float = Field(default=15.0, alias="AUDIT_TIMEOUT_READ")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> AppConfig:
    return AppConfig()

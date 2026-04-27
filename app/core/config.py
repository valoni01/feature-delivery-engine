import os
from functools import lru_cache
from typing import Self
from urllib.parse import quote_plus

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _database_url_from_split_postgres_environ() -> str | None:
    """Build a URL from libpq-style env vars (Railway/Render inject these for linked Postgres)."""
    host = os.getenv("PGHOST") or os.getenv("POSTGRES_HOST")
    if not host or not host.strip():
        return None
    user = os.getenv("PGUSER") or os.getenv("POSTGRES_USER") or "postgres"
    password = os.getenv("PGPASSWORD") or os.getenv("POSTGRES_PASSWORD") or ""
    port = os.getenv("PGPORT") or os.getenv("POSTGRES_PORT") or "5432"
    database = os.getenv("PGDATABASE") or os.getenv("POSTGRES_DB") or "postgres"
    user_q = quote_plus(user)
    password_q = quote_plus(password) if password else ""
    auth = f"{user_q}:{password_q}@" if password else f"{user_q}@"
    return f"postgresql+psycopg://{auth}{host.strip()}:{port.strip()}/{database.strip()}"


class Settings(BaseSettings):
    app_name: str = "Feature Delivery Copilot API"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/feature_delivery"

    openai_api_key: str = ""
    default_model: str = "gpt-4o"

    github_token: str = ""
    repo_workspace_dir: str = "/tmp/fde-workspaces"

    # Observability
    otel_exporter_otlp_endpoint: str = ""
    otel_exporter_otlp_headers: str = ""
    sentry_dsn: str = ""
    otel_service_name: str = "fde-backend"

    @field_validator("database_url", mode="before")
    @classmethod
    def _strip_database_url(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @model_validator(mode="after")
    def _resolve_database_url_from_railway_pg_vars(self) -> Self:
        """If DATABASE_URL is missing/empty but PG* vars exist, use them (linked Postgres on Railway)."""
        explicit = os.environ.get("DATABASE_URL", "").strip()
        if explicit:
            return self
        built = _database_url_from_split_postgres_environ()
        if built:
            self.database_url = built
        return self

    @property
    def sync_database_url(self) -> str:
        """Normalized sync URL suitable for Alembic / plain SQLAlchemy.

        Accepts `postgres://`, `postgresql://`, and `postgresql+psycopg://` from the environment.
        """
        url = self.database_url.strip()
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        elif url.startswith("postgresql://") and "+psycopg" not in url:
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url

    @property
    def async_database_url(self) -> str:
        url = self.sync_database_url
        return url.replace("+psycopg", "+psycopg_async", 1)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Treat DATABASE_URL= as unset (otherwise it overrides the default with '').
        env_ignore_empty=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

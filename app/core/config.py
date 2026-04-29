import os
from functools import lru_cache
from typing import Self
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/feature_delivery"


def _database_url_from_split_postgres_environ() -> str | None:
    """Build a URL from libpq-style env vars (Railway injects these when Postgres is linked)."""
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


def _host_is_loopback(url: str) -> bool:
    try:
        from sqlalchemy.engine.url import make_url

        u = make_url(url)
        h = (u.host or "").lower()
        return h in ("localhost", "127.0.0.1", "::1")
    except Exception:
        s = url.lower()
        return "localhost" in s or "127.0.0.1" in s


def _is_probably_cloud_runtime() -> bool:
    return (
        os.path.exists("/.dockerenv")
        or bool(os.getenv("KUBERNETES_SERVICE_HOST"))
        or bool(os.getenv("RAILWAY_ENVIRONMENT"))
        or bool(os.getenv("RAILWAY_PROJECT_ID"))
        or bool(os.getenv("COOLIFY_FQDN"))
        or bool(os.getenv("COOLIFY_CONTAINER_NAME"))
        or bool(os.getenv("RENDER_SERVICE_ID"))
        or os.getenv("ENVIRONMENT", "").lower() in ("production", "prod", "staging")
    )


class Settings(BaseSettings):
    app_name: str = "Feature Delivery Copilot API"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = Field(
        default=_DEFAULT_DATABASE_URL,
        validation_alias=AliasChoices(
            "DATABASE_URL",
            "POSTGRES_URL",
            "POSTGRESQL_URL",
        ),
    )

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
    def _merge_split_pg_environ_into_database_url(self) -> Self:
        """If no full URL in env but PGHOST-style vars exist, build the DSN (linked DB on PaaS)."""
        explicit = (
            os.environ.get("DATABASE_URL", "").strip()
            or os.environ.get("POSTGRES_URL", "").strip()
            or os.environ.get("POSTGRESQL_URL", "").strip()
        )
        if explicit:
            return self
        built = _database_url_from_split_postgres_environ()
        if built:
            self.database_url = built
        return self

    @model_validator(mode="after")
    def _reject_loopback_database_in_cloud(self) -> Self:
        """Fail fast with a clear message instead of 'connection refused' to localhost."""
        if os.getenv("ALLOW_LOOPBACK_DB") == "1":
            return self
        if not _is_probably_cloud_runtime():
            return self
        if not _host_is_loopback(self.sync_database_url):
            return self
        raise ValueError(
            "Database URL still points to localhost, but this process is running in a container "
            "or cloud (e.g. Railway). On Railway: add a Postgres service, open your web service → "
            "Variables → set DATABASE_URL using a variable reference to the Postgres plugin’s "
            "connection string (or connect the services so PGHOST/PGUSER/PGPASSWORD/PGDATABASE are "
            "injected). POSTGRES_URL is also accepted. "
            "https://docs.railway.com/databases/postgresql"
        )

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

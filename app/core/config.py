from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
            v = v.strip()
            if v == "":
                raise ValueError(
                    "DATABASE_URL is set but empty. In Railway, link a Postgres add-on or set "
                    "DATABASE_URL in Variables to a non-empty connection string."
                )
        return v

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
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

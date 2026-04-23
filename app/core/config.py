from functools import lru_cache

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

    @property
    def async_database_url(self) -> str:
        return self.database_url.replace("+psycopg", "+psycopg_async", 1)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

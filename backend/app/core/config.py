from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SAE CDMX API"
    api_prefix: str = "/api"
    database_url: str = "postgresql+psycopg://postgres:postgres@db:5432/sae_cdmx"
    cors_origins: str = "http://localhost,http://localhost:8080"
    model_path: str = "/app/models/model.joblib"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

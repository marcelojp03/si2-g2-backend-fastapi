from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = ""
    openai_api_key: str = ""
    jwt_secret: str = ""
    backend_spring_url: str = "http://localhost:2026"
    environment: str = "development"
    port: int = 8001

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

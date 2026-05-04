from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    # Bootstrap (only used on first startup; see auth module)
    bootstrap_password: str = ""

    # CORS — comma-separated string; split into a list at the point of use.
    # pydantic-settings tries to JSON-decode list[str] fields before validators
    # run, which breaks comma-separated values, so we keep this as a plain str.
    allowed_origins: str = "http://localhost:3000"

    # App
    environment: str = "development"
    log_level: str = "info"
    host: str = "0.0.0.0"
    port: int = 8000


settings = Settings()

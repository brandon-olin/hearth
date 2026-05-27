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
    bootstrap_email: str = "admin@localhost"
    bootstrap_display_name: str = "Admin"

    # CORS — comma-separated string; split into a list at the point of use.
    # pydantic-settings tries to JSON-decode list[str] fields before validators
    # run, which breaks comma-separated values, so we keep this as a plain str.
    #
    # Tauri builds inject: "tauri://localhost,http://localhost,http://localhost:1430"
    # The Tauri WebView uses tauri://localhost as its origin; http://localhost is
    # included for Tauri dev builds and the macOS WebKit fallback.
    allowed_origins: str = "http://localhost:1337"

    # AI — system-level key used when a user has no BYOK key configured.
    # Set ANTHROPIC_API_KEY in .env. Leave blank to disable AI until a key is provided.
    anthropic_api_key: str = ""

    # Teller bank sync — BYOK: each install supplies its own Teller app credentials.
    # Teller uses mutual TLS; cert and key are the files downloaded from the Teller
    # dashboard. Leave blank to disable bank sync until credentials are provided.
    teller_app_id: str = ""
    teller_cert_path: str = ""        # absolute path to certificate.pem
    teller_key_path: str = ""         # absolute path to private_key.pem
    teller_signing_secret: str = ""   # webhook payload verification secret
    teller_environment: str = "sandbox"  # sandbox | development | production

    # File uploads — local storage path inside the container
    upload_dir: str = "/data/uploads"
    max_upload_size_mb: int = 10

    # Mailgun — transactional email (verification codes, etc.)
    # Sign up at https://mailgun.com and create a sending domain.
    # API key is found under Settings → API Keys (use the "Private API key").
    mailgun_api_key: str = ""
    mailgun_domain: str = ""   # e.g. "mail.yourdomain.com"
    mailgun_from_email: str = ""  # e.g. "Hearth <noreply@mail.yourdomain.com>"

    # Field-level encryption
    # Generate a key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Comma-separate multiple keys for rotation (first key encrypts; all keys decrypt).
    # Leave blank in local dev — values will be stored as plaintext with a warning.
    field_encryption_key: str = ""

    # App
    environment: str = "development"
    log_level: str = "info"
    host: str = "0.0.0.0"
    port: int = 1338


settings = Settings()

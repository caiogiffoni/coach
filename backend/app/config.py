from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    secret_key: str = "dev-secret-change-me-before-using-in-production"
    database_url: str = f"sqlite:///{DATA_DIR / 'coach.db'}"
    token_expire_hours: int = 24 * 7

    # LLM provider. Default: Kimi K2 via its OpenAI-compatible endpoint;
    # set LLM_PROVIDER=claude (plus LLM_API_KEY/LLM_MODEL) for Claude.
    llm_provider: str = "kimi"  # kimi | claude
    llm_base_url: str = "https://api.moonshot.ai/v1"
    llm_api_key: str = ""
    llm_model: str = "kimi-k2-0905-preview"
    llm_timeout_seconds: float = 60.0

    # Manual uploads (GDPR zip / FIT files).
    upload_dir: str = str(DATA_DIR / "uploads")
    upload_max_file_size_bytes: int = 100 * 1024 * 1024  # 100 MiB per file
    upload_max_files_count: int = 10  # max files in a single /upload request
    upload_max_zip_uncompressed_bytes: int = 500 * 1024 * 1024  # 500 MiB total
    upload_max_zip_uncompressed_ratio: int = 100  # guard against zip bombs

    # Garmin Connect (unofficial API). Optional until push/sync is used.
    garmin_email: str = ""
    garmin_password: str = ""
    garmin_token_store: str = str(DATA_DIR / "garmin_tokens")


settings = Settings()
Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)

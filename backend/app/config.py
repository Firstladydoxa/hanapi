"""Runtime configuration. All values come from HAN_* environment variables."""
from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULT_SECRET = "dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HAN_", env_file=".env", extra="ignore")

    env: str = "development"  # development | test | production
    secret_key: str = INSECURE_DEFAULT_SECRET
    database_url: str = "postgresql+psycopg://han:han@localhost:5432/han"
    redis_url: str = "redis://localhost:6379/0"
    jobs_eager: bool = False  # run jobs inline in the request (tests)
    jobs_background: bool = False  # run jobs in a background thread of the API process (single-instance dev/pilot without Redis)

    # Sessions / cookies
    session_ttl_minutes: int = 480
    cookie_secure: Optional[bool] = None  # None -> derived from env (True in production)
    cookie_name: str = "han_session"

    # Email authentication (Brevo)
    smtp_host: str = "smtp-relay.brevo.com"
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    mail_from_address: Optional[str] = None
    mail_from_name: str = "TNI HAN"
    public_app_url: str = "http://localhost:3000"
    email_code_ttl_minutes: int = 15
    email_code_max_attempts: int = 5
    email_code_resend_cooldown_seconds: int = 60
    registration_reminder_delay_minutes: int = 30
    email_auth_pepper: Optional[str] = None
    cors_origins: str = ""  # comma separated; empty = CORS closed
    trust_proxy: bool = False

    # Limits
    max_body_bytes: int = 1_000_000
    max_text_chars: int = 10_000
    max_job_chars: int = 200_000
    max_job_segments: int = 500
    max_context_chars: int = 5_000
    rate_limit_auth_per_min: int = 10
    rate_limit_translate_per_min: int = 30
    tm_min_match: int = 70

    # Logging
    log_level: str = "INFO"
    log_json: bool = True
    content_logging: bool = False  # NEVER enable in production without a data-protection review

    # Providers
    enable_mock_provider: bool = False
    google_api_key: Optional[str] = None
    google_base_url: str = "https://translation.googleapis.com/language/translate/v2"
    madlad_url: Optional[str] = None
    afrinllb_url: Optional[str] = None
    nllb_url: Optional[str] = None
    inference_token: Optional[str] = None
    provider_timeout_s: float = 20.0
    provider_retries: int = 1
    provider_retry_backoff_s: float = 0.2
    health_window_minutes: int = 10
    health_min_attempts: int = 5
    health_max_error_rate: float = 0.5

    # Optional semantic TM hook (off by default; see memory/embeddings.py)
    semantic_tm: bool = False

    # Assistant service (chat model + embeddings). Unset = HAN falls back to deterministic answers.
    assistant_url: Optional[str] = None
    assistant_timeout_s: float = 90.0
    chat_max_tokens: int = 380
    chat_temperature: float = 0.4
    chat_context_chars: int = 7000  # budget for conversation history in a prompt (about 1,750 tokens)
    chat_recent_messages: int = 10
    conversation_summary_threshold: int = 16  # messages in a conversation before older ones are summarised
    conversation_retention_days: int = 30  # soft-deleted conversations are purged after this many days

    # Knowledge base
    knowledge_max_upload_bytes: int = 5_000_000

    # Rhapsody source uploads are stored outside the web root.
    rhapsody_storage_dir: str = "./var/rhapsody"
    rhapsody_max_upload_bytes: int = 25_000_000
    rhapsody_font_storage_dir: str = "./var/rhapsody-fonts"
    rhapsody_max_font_bytes: int = 15_000_000
    knowledge_chunk_chars: int = 900
    knowledge_top_k: int = 4
    knowledge_min_similarity: float = 0.78  # cosine similarity floor for semantic hits (multilingual-e5 scores cluster high)

    @field_validator("env")
    @classmethod
    def _env(cls, v: str) -> str:
        v = v.lower()
        if v not in {"development", "test", "production"}:
            raise ValueError("HAN_ENV must be development, test or production")
        return v

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def effective_cookie_secure(self) -> bool:
        return self.is_production if self.cookie_secure is None else self.cookie_secure

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def mock_provider_allowed(self) -> bool:
        return (not self.is_production) and self.enable_mock_provider

    def validate_for_startup(self) -> None:
        if self.is_production:
            if self.secret_key == INSECURE_DEFAULT_SECRET or len(self.secret_key) < 32:
                raise RuntimeError(
                    "HAN_SECRET_KEY must be set to a random value of at least 32 characters in production"
                )
            if self.content_logging:
                raise RuntimeError("HAN_CONTENT_LOGGING must not be enabled in production")
            if not (self.smtp_username and self.smtp_password and self.mail_from_address):
                raise RuntimeError("HAN_SMTP_USERNAME, HAN_SMTP_PASSWORD and HAN_MAIL_FROM_ADDRESS are required in production")
            if not self.email_auth_pepper or len(self.email_auth_pepper) < 32:
                raise RuntimeError("HAN_EMAIL_AUTH_PEPPER must be a random secret of at least 32 characters in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()

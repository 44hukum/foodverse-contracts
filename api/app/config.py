"""Application settings.

Every value comes from the environment (``.env.example`` lists them all with
safe placeholders). The ``.env`` file itself is not read here: the shell
sources it (``set -a; source .env; set +a``), exactly as ``scripts/check.sh``
and CI do, so there is a single way values reach the process.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_JWT_SECRET_BYTES = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    # --- general ---
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    api_port: int = 8000
    web_port: int = 5173
    api_base_url: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:5173"
    cors_allowed_origins: str = "http://localhost:5173"
    org_display_name: str = "Foodverse"
    display_timezone: str = "Asia/Kathmandu"

    # --- database ---
    database_url: str = (
        "postgresql+asyncpg://foodverse:foodverse@localhost:5432/foodverse_contracts"
    )
    test_database_url: str = (
        "postgresql+asyncpg://foodverse:foodverse@localhost:5432/foodverse_contracts_test"
    )
    retention_database_url: str = (
        "postgresql+asyncpg://foodverse_retention:foodverse@localhost:5432/foodverse_contracts"
    )

    # --- storage ---
    storage_backend: Literal["local", "s3"] = "local"
    local_storage_dir: str = "./.local-storage"
    s3_endpoint_url: str = ""
    s3_region: str = "us-east-1"
    s3_bucket: str = "foodverse-contracts"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_force_path_style: bool = False

    # --- admin auth ---
    jwt_secret: str = Field(default="", repr=False)
    jwt_issuer: str = "foodverse-contracts"
    admin_jwt_ttl_minutes: int = 480
    admin_login_rate_limit_per_ip_per_minute: int = 10
    admin_password_min_length: int = 12

    # --- signing ---
    signing_link_ttl_days: int = 14
    download_url_ttl_seconds: int = 300
    max_pdf_bytes: int = 20 * 1024 * 1024
    max_signature_png_bytes: int = 512_000
    public_rate_limit_per_ip_per_minute: int = 60
    public_sign_attempts_per_token: int = 10
    consent_text_version: str = "v0-draft"
    certificate_text_version: str = "v0-draft"

    # --- retention ---
    retention_signed_years_after_term: int = 7
    retention_unsigned_anonymize_after_days: int = 90

    # --- email ---
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str = ""
    smtp_password: str = Field(default="", repr=False)
    smtp_use_tls: bool = False
    email_from: str = "Foodverse Contracts <contracts@foodverse.example>"
    email_max_attachment_bytes: int = 10 * 1024 * 1024
    email_download_link_ttl_hours: int = 72
    email_send_attempts: int = 3
    smtp_timeout_seconds: float = 15.0

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_long_enough(cls, value: str) -> str:
        if len(value.encode()) < MIN_JWT_SECRET_BYTES:
            raise ValueError(f"JWT_SECRET must be at least {MIN_JWT_SECRET_BYTES} bytes")
        return value

    @field_validator("admin_password_min_length")
    @classmethod
    def _password_floor(cls, value: int) -> int:
        # SPEC.md §7: minimum 12. Configuration may raise it, never lower it.
        return max(value, 12)

    @field_validator("signing_link_ttl_days")
    @classmethod
    def _link_ttl_in_bounds(cls, value: int) -> int:
        # SPEC.md §7: links live 1..30 days; the default must be a legal per-send value.
        if not 1 <= value <= 30:
            raise ValueError("SIGNING_LINK_TTL_DAYS must be between 1 and 30")
        return value

    @field_validator("email_send_attempts")
    @classmethod
    def _at_least_one_attempt(cls, value: int) -> int:
        if value < 1:
            raise ValueError("EMAIL_SEND_ATTEMPTS must be at least 1")
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

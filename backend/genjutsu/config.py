from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GENJUTSU_", env_file=".env", extra="ignore"
    )
    secret_key: str = Field(min_length=32, repr=False)
    database_url: str = Field(
        default="postgresql+psycopg://genjutsu@localhost:5432/genjutsu", repr=False
    )
    data_dir: Path = Path("data")
    public_url: str = "http://localhost:8000"
    secure_cookies: bool = True
    admin_email: str = "admin@example.com"
    admin_password: str = Field(min_length=12, repr=False)
    session_hours: int = Field(default=24, ge=1, le=168)
    max_upload_mb: int = Field(default=128, ge=1, le=512)
    max_video_seconds: int = Field(default=30, ge=1, le=120)
    user_storage_mb: int = Field(default=2048, ge=128)
    max_active_jobs: int = Field(default=2, ge=1, le=10)
    max_nodes_per_job: int = Field(default=20, ge=1, le=100)
    max_paid_steps: int = Field(default=4, ge=1, le=20)
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "genjutsu-v1"
    temporal_tls: bool = False
    temporal_api_key: str = ""
    temporal_enabled: bool = True
    job_timeout_seconds: int = Field(default=7200, ge=60, le=86400)
    provider_base_urls: dict[str, str] = Field(
        default_factory=lambda: {
            "openrouter": "https://openrouter.ai/api/v1",
            "fal": "https://queue.fal.run",
            "replicate": "https://api.replicate.com/v1",
        }
    )
    custom_api_urls: list[str] = Field(default_factory=list)
    download_hosts: list[str] = Field(
        default_factory=lambda: ["fal.media", "fal.run", "replicate.delivery"]
    )
    static_dir: Path = Path("dist")
    testing: bool = False

    @model_validator(mode="after")
    def validate_runtime(self):
        from urllib.parse import urlsplit

        parsed = urlsplit(self.public_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("public_url must be an HTTP(S) origin")
        if not self.testing and not self.database_url.startswith("postgresql"):
            raise ValueError("PostgreSQL is required outside tests")
        if not self.testing and not self.temporal_enabled:
            raise ValueError("Temporal is required outside tests")
        if self.secure_cookies and parsed.scheme != "https":
            raise ValueError(
                "HTTPS public_url required with secure cookies; disable only for local development"
            )
        return self


@lru_cache
def get_settings():
    return Settings()

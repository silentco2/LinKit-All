"""App settings from `LINKIT_*` environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from platformdirs import user_data_dir
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["codex_cli", "claude_cli", "litellm"]

# The trimmed LibreOffice bundle (scripts/bundle_libreoffice.py), Windows x64 only, hosted as a
# release asset (152,201,685 bytes, unpacks to about 439 MB). The hash is checked before unpacking.
LO_BUNDLE_URL = "https://github.com/silentco2/LinKit-All/releases/download/libreoffice-26.2.6-win-x64/libreoffice-minimal-26.2.6-win-x64.zip"
LO_BUNDLE_SHA256 = "9f5e05e456393c91108f3c48cca4f74c095867a5ef806714102c86a7706cfb28"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LINKIT_")

    data_dir: Path = Path(user_data_dir("linkit-all", appauthor=False))
    log_level: str = "INFO"
    dev_origins: list[str] = []  # e.g. ["http://localhost:4200"] while running `ng serve`

    provider: ProviderName = "codex_cli"
    model: str | None = None  # None = the CLI's own default; required for litellm
    api_key: SecretStr | None = None  # litellm; falls back to provider env vars
    api_base: str | None = None  # OpenAI-compatible local server (Ollama, LM Studio)
    llm_concurrency: int = Field(1, ge=1, le=3)
    llm_timeout_s: float = 300

    tailor_max_growth: float = Field(0.10, ge=0, le=1)  # per segment, in characters
    tailor_max_word_change: float = Field(0.15, ge=0, le=1)  # whole CV
    tailor_min_ssim: float = Field(0.85, ge=0, le=1)  # per page vs original PDF

    # Multilingual (Arabic + English), 220 MB, downloaded once into data_dir/models.
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    lo_bundle_url: str = LO_BUNDLE_URL  # LINKIT_LO_BUNDLE_URL
    lo_bundle_sha256: str = LO_BUNDLE_SHA256  # LINKIT_LO_BUNDLE_SHA256: hex digest of the zip

    @property
    def db_path(self) -> Path:
        return self.data_dir / "linkit.db"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"


@lru_cache
def get_settings() -> Settings:
    return Settings()

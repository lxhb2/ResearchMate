"""Application configuration loaded from environment variables."""
import os
import secrets
import sys
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_files() -> list[str]:
    """Locate .env files.

    Priority:
      1. A .env sitting next to the packaged exe (PyInstaller single-file mode),
         so the portable pack works even if launched directly (no shell env vars).
      2. A .env in the current working directory (dev / server mode).
    Environment variables themselves always take priority over any .env file
    in pydantic-settings.
    """
    files: list[str] = []
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        if exe_dir:
            files.append(os.path.join(exe_dir, ".env"))
    files.append(".env")
    return files


DEFAULT_SECRET_KEY = "change-me-in-production-please-use-a-long-random-string"


def _load_or_create_secret_key(storage_dir: str) -> str:
    """首启生成随机密钥并持久化，避免固定默认密钥。"""
    path = os.path.join(storage_dir, "secret_key")
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                key = f.read().strip()
            if key:
                return key
        except OSError:
            pass
    key = secrets.token_urlsafe(48)
    try:
        os.makedirs(storage_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(key + "\n")
    except OSError:
        pass
    return key


class Settings(BaseSettings):
    # App
    APP_NAME: str = "ResearchMate"
    APP_VERSION: str = "0.3.2"
    GITHUB_REPO: str = "lxhb2/ResearchMate"
    API_V1_PREFIX: str = "/api/v1"
    SECRET_KEY: str = DEFAULT_SECRET_KEY
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Single-user auto-login (skip the login screen in local deployment)
    AUTO_LOGIN: bool = True
    AUTO_LOGIN_USERNAME: str = "researcher"
    AUTO_LOGIN_PASSWORD: str = "researchmate"

    # Database — 本地 SQLite 单文件，零服务、零配置
    DATABASE_URL: str = "sqlite:///./researchmate.db"

    # File storage
    STORAGE_DIR: str = "storage"
    PDF_DIR: str = "storage/pdfs"

    # Frontend static hosting (green-pack / production single-port mode)
    # When set to an existing directory, the backend also serves the built frontend.
    FRONTEND_DIST: str = ""

    # LLM (OpenAI-compatible)
    LLM_API_KEY: str = "sk-xxx"
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-4o"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 1536

    # Translation (optional DeepL fallback)
    DEEPL_API_KEY: str = ""

    # Web search providers (AnySearch anonymous by default, SearXNG optional)
    ANYSEARCH_ENABLED: bool = True
    ANYSEARCH_API_KEY: str = ""
    ANYSEARCH_BASE_URL: str = "https://api.anysearch.com"
    SEARXNG_URL: str = ""

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    model_config = SettingsConfigDict(env_file=_env_files(), case_sensitive=True, extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    def model_post_init(self, __context) -> None:
        """未显式配置 SECRET_KEY 时，自动生成本地持久化随机密钥。"""
        if self.SECRET_KEY == DEFAULT_SECRET_KEY:
            object.__setattr__(self, "SECRET_KEY", _load_or_create_secret_key(self.STORAGE_DIR))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

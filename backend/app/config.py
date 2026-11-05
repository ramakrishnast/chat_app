import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent

CsvList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    """Validated settings, read from the environment and the repo-level .env."""

    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- the graph -------------------------------------------------------------------------
    # "module.path:attribute". The attribute may be a StateGraph builder, a compiled graph,
    # or a zero-argument (optionally async) factory returning either.
    graph: str = "agents.example.graph:builder"
    # Extra directories put on sys.path before importing GRAPH (e.g. your own agents repo).
    graph_pythonpath: CsvList = []

    # --- storage ---------------------------------------------------------------------------
    # Postgres URL. Empty: threads and checkpoints live in memory and are lost on restart.
    database_url: str = ""

    # --- models ----------------------------------------------------------------------------
    # Model ids are "<provider>:<name>", e.g. "ollama:qwen3:0.6b", "anthropic:claude-sonnet-5-5".
    default_model: str = ""
    ollama_base_url: str = "http://localhost:11434"
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_models: CsvList = ["gpt-5-mini", "gpt-5"]
    anthropic_api_key: str = ""
    anthropic_models: CsvList = ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"]
    # Offer the offline `fake:echo` model (UI work without Ollama or an API key).
    enable_fake_model: bool = False
    # Token budget for Anthropic extended thinking when the Think toggle is on.
    anthropic_thinking_budget: int = Field(default=4096, ge=1024)
    # Seconds allowed between streamed tokens (large local models load slowly).
    model_timeout: float = Field(default=300.0, gt=0)

    # --- server ----------------------------------------------------------------------------
    cors_origins: CsvList = ["http://localhost:5173", "http://127.0.0.1:5173"]
    log_level: str = "INFO"
    # Built UI (`npm run build`). When it exists, the API serves it at "/" so the whole app
    # runs as one uvicorn process; in development Vite serves the UI instead.
    frontend_dist: Path = REPO_DIR / "frontend" / "dist"

    @field_validator(
        "graph_pythonpath", "openai_models", "anthropic_models", "cors_origins", mode="before"
    )
    @classmethod
    def _split(cls, value: object) -> object:
        """Accept `a,b,c` or a JSON list."""
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return json.loads(text)
            return [item.strip() for item in text.split(",") if item.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def _psycopg_url(cls, value: str) -> str:
        value = value.strip()
        # Accept SQLAlchemy-style URLs too; psycopg wants the plain scheme.
        for prefix in ("postgresql+psycopg://", "postgresql+asyncpg://", "postgres://"):
            if value.startswith(prefix):
                value = "postgresql://" + value[len(prefix) :]
        if value and not value.startswith("postgresql://"):
            raise ValueError("DATABASE_URL must be a postgresql:// URL, or empty for in-memory")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()

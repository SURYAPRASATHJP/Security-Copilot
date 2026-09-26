from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

MISSING_KEY_MESSAGE = (
    "GROQ_API_KEY is not set. Copy .env.example to .env in the repository root and paste "
    "your key from console.groq.com after GROQ_API_KEY=."
)


class MissingGroqKeyError(RuntimeError):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    groq_api_key: str = ""
    hf_token: str = ""
    nvd_api_key: str = ""

    groq_base_url: str = "https://api.groq.com/openai/v1"
    model_name: str = "openai/gpt-oss-120b"
    guard_model_name: str = "meta-llama/llama-prompt-guard-2-86m"
    embedding_model_name: str = "BAAI/bge-small-en-v1.5"
    reranker_model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    input_usd_per_million_tokens: float = 0.15
    output_usd_per_million_tokens: float = 0.60

    api_base_url: str = "http://127.0.0.1:8000"
    request_timeout_seconds: float = 60.0
    max_attempts: int = 5

    data_dir: Path = REPO_ROOT / "data"
    cache_dir: Path = REPO_ROOT / ".cache"

    @property
    def chroma_dir(self) -> Path:
        return REPO_ROOT / ".chroma"

    @property
    def llm_call_log(self) -> Path:
        return self.data_dir / "llm_calls.jsonl"

    @property
    def llm_response_cache(self) -> Path:
        return self.cache_dir / "llm_responses"

    def has_groq_key(self) -> bool:
        return bool(self.groq_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


def require_groq_key(settings: Settings | None = None) -> Settings:
    """Return settings, or stop with instructions when the Groq key is missing."""
    settings = settings or get_settings()
    if not settings.has_groq_key():
        raise MissingGroqKeyError(MISSING_KEY_MESSAGE)
    return settings

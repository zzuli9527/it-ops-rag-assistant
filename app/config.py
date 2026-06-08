from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = Field(default="IT Ops RAG Assistant", alias="APP_NAME")
    app_env: str = Field(default="local", alias="APP_ENV")
    data_dir: Path = Field(default=Path("data"), alias="DATA_DIR")
    upload_dir: Path = Field(default=Path("data/uploads"), alias="UPLOAD_DIR")
    db_path: Path = Field(default=Path("data/app.db"), alias="DB_PATH")
    sample_docs_dir_override: Path | None = Field(default=None, alias="SAMPLE_DOCS_DIR")
    sample_eval_dir_override: Path | None = Field(default=None, alias="SAMPLE_EVAL_DIR")
    knowledge_docs_dir_override: Path | None = Field(default=None, alias="KNOWLEDGE_DOCS_DIR")
    retrieval_top_k: int = Field(default=5, alias="RETRIEVAL_TOP_K")
    retrieval_candidates: int = Field(default=12, alias="RETRIEVAL_CANDIDATES")
    answer_min_score: float = Field(default=0.08, alias="ANSWER_MIN_SCORE")
    max_context_chars: int = Field(default=7000, alias="MAX_CONTEXT_CHARS")
    llm_mode: str = Field(default="local", alias="LLM_MODE")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    llm_base_url: str = Field(default="", alias="LLM_BASE_URL")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    embedding_mode: str = Field(default="local", alias="EMBEDDING_MODE")
    embedding_model: str = Field(default="text-embedding-3-small", alias="EMBEDDING_MODEL")

    @property
    def root_dir(self) -> Path:
        return Path(__file__).resolve().parents[1]

    @property
    def sample_docs_dir(self) -> Path:
        if self.sample_docs_dir_override is not None:
            return self.sample_docs_dir_override
        return self.root_dir / "data" / "sample_docs"

    @property
    def sample_eval_dir(self) -> Path:
        if self.sample_eval_dir_override is not None:
            return self.sample_eval_dir_override
        return self.root_dir / "data" / "sample_eval"

    @property
    def knowledge_docs_dir(self) -> Path:
        if self.knowledge_docs_dir_override is not None:
            return self.knowledge_docs_dir_override
        return self.root_dir / "local_docs"

    def ensure_dirs(self) -> None:
        data_dir = self.data_dir if self.data_dir.is_absolute() else self.root_dir / self.data_dir
        upload_dir = self.upload_dir if self.upload_dir.is_absolute() else self.root_dir / self.upload_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        upload_dir.mkdir(parents=True, exist_ok=True)
        self.sample_docs_dir.mkdir(parents=True, exist_ok=True)
        self.sample_eval_dir.mkdir(parents=True, exist_ok=True)
        self.knowledge_docs_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


@dataclass(slots=True)
class ParsedBlock:
    title: str
    content: str
    page: int | None = None
    section_path: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DocumentRecord:
    id: str
    filename: str
    title: str
    source_type: str
    file_path: str
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    checksum: str = ""
    chunk_count: int = 0


@dataclass(slots=True)
class ChunkRecord:
    id: str
    document_id: str
    index: int
    content: str
    title: str
    page: int | None = None
    section_path: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    token_count: int = 0
    checksum: str = ""


@dataclass(slots=True)
class SessionContext:
    service_name: str | None = None
    error_code: str | None = None
    environment: str | None = None
    component: str | None = None
    suspected_issue: str | None = None
    last_document_id: str | None = None
    last_question: str | None = None


@dataclass(slots=True)
class RetrievalHit:
    chunk_id: str
    document_id: str
    score: float
    vector_score: float
    keyword_score: float
    title: str
    content: str
    page: int | None
    section_path: list[str]
    metadata: dict[str, Any]


@dataclass(slots=True)
class AskResult:
    session_id: str
    answer: str
    action: str
    question: str
    rewritten_query: str
    sources: list[RetrievalHit]
    context: SessionContext
    debug: dict[str, Any]
    timings_ms: dict[str, float] = field(default_factory=dict)


class UploadResult(BaseModel):
    document_id: str
    filename: str
    title: str
    chunk_count: int


class ChatRequest(BaseModel):
    session_id: str | None = None
    question: str = Field(min_length=1)
    document_scope: list[str] | None = None


class ChatSessionCreate(BaseModel):
    title: str | None = None


class RetrievalDebugRequest(BaseModel):
    question: str = Field(min_length=1)
    session_id: str | None = None
    document_scope: list[str] | None = None


class EvalRunRequest(BaseModel):
    dataset: str | None = None


class EvalResult(BaseModel):
    run_id: str
    total: int
    retrieval_hit_rate_at_k: float
    source_precision: float
    answer_completeness: float
    clarification_trigger_rate: float
    reports: list[dict[str, Any]]
    timings_ms: dict[str, Any] = Field(default_factory=dict)

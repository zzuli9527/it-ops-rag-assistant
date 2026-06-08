from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator

from .models import ChunkRecord, DocumentRecord, SessionContext, utc_now


class SQLiteStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    idx INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    title TEXT NOT NULL,
                    page INTEGER,
                    section_path TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    token_count INTEGER NOT NULL,
                    checksum TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    context TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS eval_runs (
                    id TEXT PRIMARY KEY,
                    dataset TEXT,
                    created_at TEXT NOT NULL,
                    report TEXT NOT NULL
                );
                """
            )

    def upsert_document(self, document: DocumentRecord) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO documents (id, filename, title, source_type, file_path, created_at, updated_at, checksum, chunk_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    filename=excluded.filename,
                    title=excluded.title,
                    source_type=excluded.source_type,
                    file_path=excluded.file_path,
                    updated_at=excluded.updated_at,
                    checksum=excluded.checksum,
                    chunk_count=excluded.chunk_count
                """,
                (
                    document.id,
                    document.filename,
                    document.title,
                    document.source_type,
                    document.file_path,
                    document.created_at,
                    document.updated_at,
                    document.checksum,
                    document.chunk_count,
                ),
            )

    def delete_chunks_for_document(self, document_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))

    def insert_chunks(self, chunks: list[ChunkRecord]) -> None:
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO chunks (id, document_id, idx, content, title, page, section_path, metadata, token_count, checksum)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.id,
                        chunk.document_id,
                        chunk.index,
                        chunk.content,
                        chunk.title,
                        chunk.page,
                        json.dumps(chunk.section_path, ensure_ascii=False),
                        json.dumps(chunk.metadata, ensure_ascii=False),
                        chunk.token_count,
                        chunk.checksum,
                    )
                    for chunk in chunks
                ],
            )

    def list_documents(self) -> list[DocumentRecord]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM documents ORDER BY updated_at DESC").fetchall()
        return [self._row_to_document(row) for row in rows]

    def get_document(self, document_id: str) -> DocumentRecord | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        return self._row_to_document(row) if row else None

    def get_document_by_filename(self, filename: str) -> DocumentRecord | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE filename = ?", (filename,)).fetchone()
        return self._row_to_document(row) if row else None

    def list_chunks(self, document_id: str | None = None) -> list[ChunkRecord]:
        query = "SELECT * FROM chunks"
        params: tuple[Any, ...] = ()
        if document_id is not None:
            query += " WHERE document_id = ?"
            params = (document_id,)
        query += " ORDER BY document_id, idx"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_chunk(row) for row in rows]

    def get_chunk(self, chunk_id: str) -> ChunkRecord | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
        return self._row_to_chunk(row) if row else None

    def count_documents(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM documents").fetchone()
        return int(row["c"]) if row else 0

    def save_session(self, session_id: str, title: str | None, context: SessionContext) -> None:
        payload = json.dumps(asdict(context), ensure_ascii=False)
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, title, created_at, updated_at, context)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=COALESCE(excluded.title, sessions.title),
                    updated_at=excluded.updated_at,
                    context=excluded.context
                """,
                (session_id, title, now, now, payload),
            )

    def load_session_context(self, session_id: str) -> SessionContext:
        with self.connect() as conn:
            row = conn.execute("SELECT context FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            return SessionContext()
        raw = json.loads(row["context"] or "{}")
        return SessionContext(**raw)

    def list_sessions(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC").fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "context": json.loads(row["context"] or "{}"),
                }
            )
        return result

    def append_message(self, session_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO messages (session_id, role, content, created_at, metadata)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, role, content, utc_now(), json.dumps(metadata or {}, ensure_ascii=False)),
            )

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT role, content, created_at, metadata FROM messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        return [
            {
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"],
                "metadata": json.loads(row["metadata"] or "{}"),
            }
            for row in rows
        ]

    def save_eval_run(self, run_id: str, dataset: str | None, report: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO eval_runs (id, dataset, created_at, report)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET report=excluded.report
                """,
                (run_id, dataset, utc_now(), json.dumps(report, ensure_ascii=False)),
            )

    def get_eval_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM eval_runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "dataset": row["dataset"],
            "created_at": row["created_at"],
            "report": json.loads(row["report"] or "{}"),
        }

    @staticmethod
    def _row_to_document(row: sqlite3.Row | None) -> DocumentRecord:
        if row is None:
            raise ValueError("row is required")
        return DocumentRecord(
            id=row["id"],
            filename=row["filename"],
            title=row["title"],
            source_type=row["source_type"],
            file_path=row["file_path"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            checksum=row["checksum"],
            chunk_count=int(row["chunk_count"]),
        )

    @staticmethod
    def _row_to_chunk(row: sqlite3.Row | None) -> ChunkRecord:
        if row is None:
            raise ValueError("row is required")
        return ChunkRecord(
            id=row["id"],
            document_id=row["document_id"],
            index=int(row["idx"]),
            content=row["content"],
            title=row["title"],
            page=row["page"],
            section_path=json.loads(row["section_path"] or "[]"),
            metadata=json.loads(row["metadata"] or "{}"),
            token_count=int(row["token_count"]),
            checksum=row["checksum"],
        )

# Architecture

## Core pipeline

1. Upload or bootstrap documents into local storage.
2. Parse source files into structured blocks with title, page, and section metadata.
3. Chunk blocks into retrieval-sized units with overlap.
4. Build a hybrid index with TF-IDF vector similarity and BM25 keyword scoring.
5. Rewrite multi-turn questions with session context.
6. Retrieve, rerank, answer, and emit citations.
7. Run offline evaluation against the sample dataset.

## Storage

- SQLite stores documents, chunks, sessions, messages, and eval runs.
- Indexes are rebuilt in-process from chunk text after ingest.

## Public project boundary

- No internal APIs or real production data.
- Only synthetic IT troubleshooting documents and evaluation cases.


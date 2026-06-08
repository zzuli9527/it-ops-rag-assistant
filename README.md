# IT Ops RAG Assistant

An IT operations document QA project for local demo, evaluation, and GitHub presentation.

## What it does

- Parses `PDF / DOCX / Markdown / HTML / TXT`
- Builds structured chunks with section metadata
- Uses hybrid retrieval with TF-IDF style vector recall plus BM25
- Supports multi-turn QA, clarification, citations, and offline evaluation
- Exposes FastAPI APIs and a lightweight web UI

## Project boundary

This repository is prepared for public upload:

- Public sample knowledge lives in `data/sample_docs/`
- Local private knowledge should live in `local_docs/`
- `.env`, `local_docs/`, uploaded files, and local databases are ignored by Git

Do not upload internal company documents, screenshots, secrets, or API credentials.

## Quick start

```bash
pip install -e ".[dev]"
copy .env.example .env
python .\app\main.py
```

Open `http://127.0.0.1:8011`.

## Run evaluation

```bash
python .\scripts\run_eval.py
```

The evaluation output includes:

- `retrieval_hit_rate_at_k`
- `source_precision`
- `answer_completeness`
- `clarification_trigger_rate`
- stage timings with `avg / p50 / p95 / max`

## Key directories

- `app/`: service, retrieval, parsing, prompts, API
- `data/sample_docs/`: public demo documents
- `data/sample_eval/`: public evaluation cases
- `docs/`: project documentation only
- `local_docs/`: local private knowledge, excluded from Git
- `tests/`: unit and integration tests

## Current public demo status

- 5 public sample troubleshooting documents
- 17 automated tests
- offline evaluation and request timing breakdown

See [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) for a fuller summary.

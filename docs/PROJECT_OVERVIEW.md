# Project Overview

## Positioning

`IT Ops RAG Assistant` is a local-deployable IT and DevOps document QA project built as a public engineering demo.

The project was shaped as a resume-ready practice project with these goals:

- runnable locally
- safe to publish on GitHub
- easy to demo in interviews
- measurable through offline evaluation

## Functional scope

- multi-format document ingestion
- structured chunking with section metadata
- hybrid retrieval
- multi-turn QA
- clarification for underspecified questions
- citations and retrieval debug output
- offline evaluation with timing breakdown

## Tech stack

- Python 3.11
- FastAPI
- SQLite
- Jinja2
- PyMuPDF
- python-docx
- BM25 + TF-IDF style vector retrieval
- pytest

## Public repository boundary

Safe to publish:

- source code
- public sample docs in `data/sample_docs/`
- public eval cases in `data/sample_eval/`
- README and architecture docs

Do not publish:

- `.env`
- API keys
- local uploaded files
- internal PDFs or DOCX files
- company screenshots, real work orders, or internal identifiers

Private local knowledge should be placed in `local_docs/`, which is ignored by Git.

## Current demo metrics

Based on the current public sample evaluation set:

- automated tests: `17`
- retrieval hit rate: `83.3%`
- source precision: `83.3%`
- answer completeness: `77.8%`
- clarification trigger rate: `100%`

These metrics are suitable for a practice project and interview demo, not for production claims.

## GitHub upload checklist

Before pushing:

1. Confirm `.env` is not staged.
2. Confirm `local_docs/` is not staged.
3. Confirm `data/app.db` and `data/uploads/` are not staged.
4. Keep only public sample documents in the repository.
5. Re-run:
   - `pytest -q`
   - `python .\scripts\run_eval.py`

## Demo flow

1. Start the app locally.
2. Show uploaded public sample docs.
3. Ask sample troubleshooting questions.
4. Show citations and retrieval debug output.
5. Show the offline evaluation result page or CLI report.

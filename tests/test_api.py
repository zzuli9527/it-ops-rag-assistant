from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_api_smoke(temp_settings: Settings) -> None:
    client = TestClient(create_app(temp_settings))

    documents = client.get("/api/documents")
    assert documents.status_code == 200
    assert len(documents.json()) >= 1

    sync = client.post("/api/documents/sync")
    assert sync.status_code == 200
    assert "imported" in sync.json()

    session = client.post("/api/chat/sessions", json={"title": "smoke"})
    assert session.status_code == 200
    session_id = session.json()["id"]

    answer = client.post(
        "/api/chat/ask",
        json={
            "session_id": session_id,
            "question": "错误码 502 一般先查什么？",
            "document_scope": ["nginx-502-runbook"],
        },
    )
    assert answer.status_code == 200
    payload = answer.json()
    assert payload["action"] == "answer"
    assert payload["sources"]
    assert "timings_ms" in payload
    assert all(item["document_id"] == "nginx-502-runbook" for item in payload["sources"])

    debug = client.post(
        "/api/retrieval/debug",
        json={"question": "Redis 认证失败通常怎么排查？", "document_scope": ["redis-auth-troubleshooting"]},
    )
    assert debug.status_code == 200
    assert "rewritten_query" in debug.json()

    report = client.post("/api/eval/run", json={})
    assert report.status_code == 200
    assert report.json()["total"] == 3
    assert "timings_ms" in report.json()

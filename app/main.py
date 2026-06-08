from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

if __package__ in (None, ""):
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from app.config import Settings, get_settings
    from app.models import ChatRequest, ChatSessionCreate, EvalRunRequest, RetrievalDebugRequest
    from app.service import RagService
else:
    from .config import Settings, get_settings
    from .models import ChatRequest, ChatSessionCreate, EvalRunRequest, RetrievalDebugRequest
    from .service import RagService


def create_app(app_settings: Settings | None = None) -> FastAPI:
    settings = app_settings or get_settings()
    templates = Jinja2Templates(directory=str(settings.root_dir / "templates"))
    app = FastAPI(title=settings.app_name)
    app.mount("/static", StaticFiles(directory=str(settings.root_dir / "static")), name="static")
    service = RagService(settings)
    service.bootstrap()
    app.state.service = service

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        svc: RagService = request.app.state.service
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "documents": svc.list_documents(),
                "sessions": svc.list_sessions(),
                "sample_questions": [
                    "错误码 502 一般先查什么？",
                    "支付服务启动失败后，数据库要看哪些指标？",
                    "Redis 认证失败通常怎么排查？",
                ],
            },
        )

    @app.get("/ui/documents/{document_id}", response_class=HTMLResponse)
    async def document_page(request: Request, document_id: str) -> HTMLResponse:
        svc: RagService = request.app.state.service
        detail = svc.get_document_detail(document_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="document not found")
        return templates.TemplateResponse(request, "document.html", detail)

    @app.post("/ui/documents/{document_id}/reindex")
    async def reindex_from_page(document_id: str) -> RedirectResponse:
        try:
            service.reindex_document(document_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="document not found") from exc
        return RedirectResponse(f"/ui/documents/{document_id}", status_code=303)

    @app.get("/ui/sessions/{session_id}", response_class=HTMLResponse)
    async def session_page(request: Request, session_id: str) -> HTMLResponse:
        svc: RagService = request.app.state.service
        detail = svc.get_session_detail(session_id)
        return templates.TemplateResponse(request, "session.html", detail)

    @app.get("/ui/evals/{run_id}", response_class=HTMLResponse)
    async def eval_page(request: Request, run_id: str) -> HTMLResponse:
        svc: RagService = request.app.state.service
        detail = svc.get_eval_run(run_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="eval run not found")
        return templates.TemplateResponse(request, "eval.html", detail)

    @app.post("/ui/upload")
    async def upload_from_page(file: UploadFile = File(...)) -> RedirectResponse:
        data = await file.read()
        service.ingest_upload(file.filename, data)
        return RedirectResponse("/", status_code=303)

    @app.post("/ui/chat")
    async def chat_from_page(question: str = Form(...), session_id: str | None = Form(default=None)) -> RedirectResponse:
        result = service.ask(question, session_id=session_id or None)
        return RedirectResponse(f"/ui/sessions/{result.session_id}", status_code=303)

    @app.post("/ui/eval")
    async def eval_from_page(dataset: str = Form(default="cases.jsonl")) -> RedirectResponse:
        result = service.run_evaluation(dataset)
        return RedirectResponse(f"/ui/evals/{result.run_id}", status_code=303)

    @app.post("/ui/documents/sync")
    async def sync_from_page() -> RedirectResponse:
        service.sync_knowledge_sources()
        return RedirectResponse("/", status_code=303)

    @app.get("/api/documents")
    async def list_documents() -> list[dict]:
        return service.list_documents()

    @app.post("/api/documents/upload")
    async def upload_document(file: UploadFile = File(...)) -> dict:
        data = await file.read()
        return service.ingest_upload(file.filename, data).model_dump()

    @app.post("/api/documents/sync")
    async def sync_documents() -> dict:
        return service.sync_knowledge_sources()

    @app.get("/api/documents/{document_id}")
    async def document_detail(document_id: str) -> dict:
        detail = service.get_document_detail(document_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="document not found")
        return detail

    @app.post("/api/documents/{document_id}/reindex")
    async def reindex_document(document_id: str) -> dict:
        try:
            return service.reindex_document(document_id).model_dump()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="document not found") from exc

    @app.post("/api/chat/sessions")
    async def create_session(payload: ChatSessionCreate) -> dict:
        return service.create_session(payload.title)

    @app.get("/api/chat/sessions/{session_id}")
    async def get_session(session_id: str) -> dict:
        return service.get_session_detail(session_id)

    @app.post("/api/chat/ask")
    async def ask(payload: ChatRequest) -> dict:
        result = service.ask_with_scope(
            question=payload.question,
            session_id=payload.session_id,
            document_scope=payload.document_scope,
        )
        return {
            "session_id": result.session_id,
            "action": result.action,
            "question": result.question,
            "rewritten_query": result.rewritten_query,
            "answer": result.answer,
            "sources": [service._source_payload(hit) for hit in result.sources],
            "context": asdict(result.context),
            "timings_ms": result.timings_ms,
            "debug": result.debug,
        }

    @app.post("/api/retrieval/debug")
    async def retrieval_debug(payload: RetrievalDebugRequest) -> dict:
        return service.debug_retrieval(payload.question, payload.session_id, payload.document_scope)

    @app.post("/api/eval/run")
    async def run_eval(payload: EvalRunRequest) -> dict:
        return service.run_evaluation(payload.dataset).model_dump()

    @app.get("/api/eval/{run_id}")
    async def get_eval(run_id: str) -> dict:
        detail = service.get_eval_run(run_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="eval run not found")
        return detail

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8011, reload=False)


if __name__ == "__main__":
    main()

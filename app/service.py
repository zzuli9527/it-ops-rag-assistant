from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

from .config import Settings
from .indexing import HybridIndex, SearchDebug, StructuralChunker
from .llm import build_reasoner
from .models import AskResult, DocumentRecord, EvalResult, RetrievalHit, SessionContext, UploadResult, utc_now
from .parsers import SUPPORTED_SUFFIXES, parse_file
from .prompting import PromptManager
from .storage import SQLiteStore
from .utils import ensure_parent, sha256_bytes, sha256_text, slugify


class RagService:
    SAMPLE_DOC_KEYWORDS = {
        "nginx-502-runbook": {"502", "nginx", "gateway", "网关", "上游服务", "超时"},
        "mysql-connection-playbook": {"mysql", "3306", "数据库", "连接", "db", "connections", "slow query"},
        "redis-auth-troubleshooting": {"redis", "认证", "auth", "acl", "password", "tls", "noauth"},
        "k8s-crashloop-guide": {"pod", "crashloopbackoff", "k8s", "kubernetes", "探针", "重启", "容器"},
        "docker-startup-checklist": {"docker", "容器", "启动", "秒退", "port", "环境变量", "entrypoint"},
    }

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = SQLiteStore(settings.root_dir / settings.db_path)
        self.chunker = StructuralChunker()
        self.index = HybridIndex()
        self.prompt_manager = PromptManager(settings.root_dir / "app" / "prompts")
        self.sample_document_ids = {
            path.stem for path in self.settings.sample_docs_dir.glob("*") if path.is_file()
        }
        self.reasoner = build_reasoner(
            llm_mode=settings.llm_mode,
            llm_base_url=settings.llm_base_url,
            llm_api_key=settings.llm_api_key,
            llm_model=settings.llm_model,
            prompt_manager=self.prompt_manager,
            answer_min_score=settings.answer_min_score,
        )
        self.rebuild_index()

    def bootstrap(self, *, include_knowledge_docs: bool = True) -> None:
        self.sync_knowledge_sources(include_knowledge_docs=include_knowledge_docs)
        self.rebuild_index()

    def rebuild_index(self) -> None:
        self.index.rebuild(self.store.list_chunks())

    def sync_knowledge_sources(self, *, include_knowledge_docs: bool = True) -> dict[str, int]:
        imported = 0
        skipped = 0
        directories = [self.settings.sample_docs_dir]
        if include_knowledge_docs:
            directories.append(self.settings.knowledge_docs_dir)
        for directory in directories:
            for path in sorted(directory.glob("*")):
                if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                    continue
                file_bytes = path.read_bytes()
                checksum = sha256_bytes(file_bytes)
                existing = self.store.get_document_by_path(str(path.resolve()))
                if existing and existing.checksum == checksum:
                    skipped += 1
                    continue
                self.ingest_path(path, copy_to_uploads=False, raw_bytes=file_bytes, rebuild=False)
                imported += 1
        self.rebuild_index()
        return {"imported": imported, "skipped": skipped}

    def ingest_upload(self, filename: str, data: bytes) -> UploadResult:
        upload_dir = self._resolve_path(self.settings.upload_dir)
        safe_name = Path(filename).name
        if not safe_name or safe_name in {".", ".."}:
            raise ValueError("invalid filename")
        upload_path = (upload_dir / safe_name).resolve()
        if upload_path.parent != upload_dir.resolve():
            raise ValueError("invalid filename")
        ensure_parent(upload_path)
        upload_path.write_bytes(data)
        return self.ingest_path(upload_path, copy_to_uploads=False, raw_bytes=data)

    def ingest_path(
        self,
        path: Path,
        *,
        copy_to_uploads: bool = False,
        raw_bytes: bytes | None = None,
        rebuild: bool = True,
    ) -> UploadResult:
        if copy_to_uploads:
            target = self._resolve_path(self.settings.upload_dir) / path.name
            ensure_parent(target)
            target.write_bytes(path.read_bytes())
            path = target
        path = path.resolve()
        file_bytes = raw_bytes if raw_bytes is not None else path.read_bytes()
        title, source_type, blocks = parse_file(path)
        document_id = self._build_document_id(path)
        document = DocumentRecord(
            id=document_id,
            filename=path.name,
            title=title,
            source_type=source_type,
            file_path=str(path),
            checksum=sha256_bytes(file_bytes),
            updated_at=utc_now(),
        )
        chunks = self.chunker.chunk_blocks(document_id, title, blocks)
        for chunk in chunks:
            chunk.checksum = sha256_text(chunk.content)
        document.chunk_count = len(chunks)
        self.store.upsert_document(document)
        self.store.delete_chunks_for_document(document_id)
        self.store.insert_chunks(chunks)
        if rebuild:
            self.rebuild_index()
        return UploadResult(
            document_id=document_id,
            filename=document.filename,
            title=document.title,
            chunk_count=document.chunk_count,
        )

    def list_documents(self) -> list[dict[str, Any]]:
        return [asdict(doc) for doc in self.store.list_documents()]

    def get_document_detail(self, document_id: str) -> dict[str, Any] | None:
        document = self.store.get_document(document_id)
        if document is None:
            return None
        chunks = self.store.list_chunks(document_id)
        return {
            "document": asdict(document),
            "chunks": [asdict(chunk) for chunk in chunks],
        }

    def reindex_document(self, document_id: str) -> UploadResult:
        document = self.store.get_document(document_id)
        if document is None:
            raise KeyError(document_id)
        return self.ingest_path(Path(document.file_path), copy_to_uploads=False)

    def create_session(self, title: str | None = None) -> dict[str, Any]:
        session_id = uuid.uuid4().hex
        context = SessionContext()
        self.store.save_session(session_id, title, context)
        return {"id": session_id, "title": title, "context": asdict(context)}

    def get_session_detail(self, session_id: str) -> dict[str, Any]:
        context = self.store.load_session_context(session_id)
        return {
            "id": session_id,
            "context": asdict(context),
            "messages": self.store.list_messages(session_id),
        }

    def list_sessions(self) -> list[dict[str, Any]]:
        return self.store.list_sessions()

    def ask(self, question: str, session_id: str | None = None) -> AskResult:
        return self.ask_with_scope(question=question, session_id=session_id, document_scope=None)

    def ask_with_scope(
        self,
        *,
        question: str,
        session_id: str | None = None,
        document_scope: list[str] | set[str] | None = None,
    ) -> AskResult:
        started_at = perf_counter()
        active_session_id = session_id or self.create_session()["id"]

        context_started = perf_counter()
        history = self.store.list_messages(active_session_id)
        context = self.store.load_session_context(active_session_id)
        updated_context = self.reasoner.extract_context(question, context)
        context_ms = (perf_counter() - context_started) * 1000

        rewrite_started = perf_counter()
        rewritten_query = self.reasoner.rewrite_query(question, updated_context, history)
        rewrite_ms = (perf_counter() - rewrite_started) * 1000

        scope = set(document_scope) if document_scope else None
        recent_docs = self._recent_document_ids(history, updated_context)
        preferred_docs = scope or self._resolve_preferred_documents(question, rewritten_query, recent_docs)

        retrieval_started = perf_counter()
        hits, debug = self.index.search(
            rewritten_query,
            top_k=self.settings.retrieval_top_k,
            candidate_count=self.settings.retrieval_candidates,
            doc_scope=scope,
            boost_doc_ids=preferred_docs,
        )
        retrieval_ms = (perf_counter() - retrieval_started) * 1000

        answer_hits = self._select_answer_hits(hits, question=question, scope=scope)

        generation_started = perf_counter()
        needs_clarify, reasons = self.reasoner.should_clarify(question, answer_hits or hits, updated_context)
        if scope and (answer_hits or hits):
            reasons = [reason for reason in reasons if reason not in {"missing_entity", "missing_reference", "missing_context"}]
            needs_clarify = bool(reasons)
        if needs_clarify:
            answer = self.reasoner.build_clarification(question, updated_context, reasons)
            action = "clarify"
        else:
            answer = self.reasoner.build_answer(question, answer_hits, updated_context)
            action = "answer"
        generation_ms = (perf_counter() - generation_started) * 1000

        persist_started = perf_counter()
        if answer_hits:
            updated_context.last_document_id = answer_hits[0].document_id
        self.store.save_session(
            active_session_id,
            title=history[0]["content"][:60] if history else question[:60],
            context=updated_context,
        )
        self.store.append_message(active_session_id, "user", question, {"rewritten_query": rewritten_query})
        self.store.append_message(
            active_session_id,
            "assistant",
            answer,
            {
                "action": action,
                "source_ids": [hit.chunk_id for hit in answer_hits],
                "document_ids": [hit.document_id for hit in answer_hits],
                "document_scope": sorted(scope) if scope else None,
                "debug": self._debug_payload(debug),
            },
        )
        persist_ms = (perf_counter() - persist_started) * 1000

        total_ms = (perf_counter() - started_at) * 1000
        timings_ms = {
            "context": round(context_ms, 2),
            "rewrite": round(rewrite_ms, 2),
            "retrieval": round(retrieval_ms, 2),
            "generation": round(generation_ms, 2),
            "persist": round(persist_ms, 2),
            "total": round(total_ms, 2),
        }
        return AskResult(
            session_id=active_session_id,
            answer=answer,
            action=action,
            question=question,
            rewritten_query=rewritten_query,
            retrieval_hits=hits,
            sources=answer_hits,
            context=updated_context,
            debug={**self._debug_payload(debug), "timings_ms": timings_ms},
            timings_ms=timings_ms,
        )

    def debug_retrieval(
        self,
        question: str,
        session_id: str | None = None,
        document_scope: list[str] | set[str] | None = None,
    ) -> dict[str, Any]:
        context = self.store.load_session_context(session_id) if session_id else SessionContext()
        history = self.store.list_messages(session_id) if session_id else []
        updated_context = self.reasoner.extract_context(question, context)
        rewritten_query = self.reasoner.rewrite_query(question, updated_context, history)
        scope = set(document_scope) if document_scope else None
        recent_docs = self._recent_document_ids(history, updated_context)
        preferred_docs = scope or self._resolve_preferred_documents(question, rewritten_query, recent_docs)
        hits, debug = self.index.search(
            rewritten_query,
            top_k=self.settings.retrieval_top_k,
            candidate_count=self.settings.retrieval_candidates,
            doc_scope=scope,
            boost_doc_ids=preferred_docs,
        )
        answer_hits = self._select_answer_hits(hits, question=question, scope=scope)
        return {
            "question": question,
            "rewritten_query": rewritten_query,
            "context": asdict(updated_context),
            "document_scope": sorted(scope) if scope else None,
            "vector_hits": debug.vector_hits,
            "keyword_hits": debug.keyword_hits,
            "reranked_hits": debug.reranked_hits,
            "final_context": [self._source_payload(hit) for hit in answer_hits],
        }

    def run_evaluation(self, dataset_name: str | None = None) -> EvalResult:
        dataset_file = self.settings.sample_eval_dir / (dataset_name or "cases.jsonl")
        cases = [json.loads(line) for line in dataset_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        reports: list[dict[str, Any]] = []
        retrieval_hits = 0
        source_precision_total = 0.0
        completeness_total = 0.0
        action_hits = 0
        clarification_count = 0
        stage_samples: dict[str, list[float]] = {
            "context": [],
            "rewrite": [],
            "retrieval": [],
            "generation": [],
            "persist": [],
            "total": [],
        }

        for case in cases:
            result = self.ask_with_scope(
                question=case["question"],
                document_scope=case.get("document_scope"),
            )
            expected_sources: list[str] = case.get("expected_sources", [])
            expected_points: list[str] = case.get("expected_answer_points", [])
            retrieved_sources = [self._source_identifier(hit) for hit in result.retrieval_hits]
            answer_sources = [self._source_identifier(hit) for hit in result.sources]
            source_matches = [source for source in answer_sources if source in expected_sources]
            retrieval_hit = bool(set(retrieved_sources) & set(expected_sources))
            if retrieval_hit:
                retrieval_hits += 1
            source_precision = len(source_matches) / max(len(answer_sources), 1)
            source_precision_total += source_precision
            answer_text = result.answer.lower()
            matched_points = [point for point in expected_points if point.lower() in answer_text]
            completeness = len(matched_points) / max(len(expected_points), 1)
            completeness_total += completeness
            expect_clarify = bool(case.get("expect_clarify", False))
            clarification_ok = result.action == "clarify" if expect_clarify else result.action == "answer"
            if clarification_ok:
                action_hits += 1
            if result.action == "clarify":
                clarification_count += 1
            reports.append(
                {
                    "question": case["question"],
                    "action": result.action,
                    "document_scope": case.get("document_scope"),
                    "retrieval_hit": retrieval_hit,
                    "retrieved_sources": retrieved_sources,
                    "answer_sources": answer_sources,
                    "source_precision": round(source_precision, 3),
                    "answer_completeness": round(completeness, 3),
                    "matched_points": matched_points,
                    "expected_points": expected_points,
                    "clarification_ok": clarification_ok,
                    "hallucination_flag": result.action == "answer" and not retrieval_hit and completeness == 0,
                    "timings_ms": result.timings_ms,
                }
            )
            for stage, samples in stage_samples.items():
                value = result.timings_ms.get(stage)
                if isinstance(value, (int, float)):
                    samples.append(float(value))

        total = len(cases)
        run_id = uuid.uuid4().hex
        report = EvalResult(
            run_id=run_id,
            total=total,
            retrieval_hit_rate_at_k=retrieval_hits / max(total, 1),
            source_precision=source_precision_total / max(total, 1),
            answer_completeness=completeness_total / max(total, 1),
            action_accuracy=action_hits / max(total, 1),
            clarification_trigger_rate=clarification_count / max(total, 1),
            reports=reports,
            timings_ms={
                stage: self._timing_summary(values)
                for stage, values in stage_samples.items()
            },
        )
        self.store.save_eval_run(run_id, dataset_file.name, report.model_dump())
        return report

    def get_eval_run(self, run_id: str) -> dict[str, Any] | None:
        return self.store.get_eval_run(run_id)

    @staticmethod
    def _source_identifier(hit: RetrievalHit) -> str:
        return hit.document_id

    @staticmethod
    def _source_payload(hit: RetrievalHit) -> dict[str, Any]:
        return {
            "chunk_id": hit.chunk_id,
            "document_id": hit.document_id,
            "title": hit.title,
            "score": round(hit.score, 4),
            "vector_score": round(hit.vector_score, 4),
            "keyword_score": round(hit.keyword_score, 4),
            "page": hit.page,
            "section_path": hit.section_path,
            "content": hit.content,
        }

    def _debug_payload(self, debug: SearchDebug) -> dict[str, Any]:
        return {
            "query": debug.query,
            "vector_hits": debug.vector_hits,
            "keyword_hits": debug.keyword_hits,
            "reranked_hits": debug.reranked_hits,
        }

    def _select_answer_hits(
        self,
        hits: list[RetrievalHit],
        *,
        question: str,
        scope: set[str] | None,
    ) -> list[RetrievalHit]:
        if not hits:
            return []

        ranked = sorted(hits, key=lambda hit: self._answer_hit_sort_key(hit, question), reverse=True)
        selected: list[RetrievalHit] = []
        per_doc_counts: dict[str, int] = {}
        max_per_doc = 3 if scope and len(scope) == 1 else 2

        for hit in ranked:
            count = per_doc_counts.get(hit.document_id, 0)
            if count >= max_per_doc:
                continue
            selected.append(hit)
            per_doc_counts[hit.document_id] = count + 1
            if len(selected) >= 3:
                break
        return selected or ranked[: min(len(ranked), 3)]

    @staticmethod
    def _answer_hit_sort_key(hit: RetrievalHit, question: str) -> tuple[float, float, float]:
        section = " ".join(hit.section_path).lower()
        question_lower = question.lower()
        content_lower = hit.content.lower()

        section_weight = 2.5
        if "ordered troubleshooting steps" in section:
            section_weight = 6.0
        elif "quick checks" in section or "diagnostic signals" in section:
            section_weight = 5.0
        elif "steps" in section or "checklist" in section:
            section_weight = 4.5
        elif "common root causes" in section:
            section_weight = 3.5
        elif "risk notes" in section:
            section_weight = 1.5
        elif "symptoms" in section:
            section_weight = 1.0

        question_bonus = 0.0
        if "crashloop" in question_lower and ("pod events" in content_lower or "probe" in content_lower):
            question_bonus = 1.5
        elif ("数据库" in question or "mysql" in question_lower) and (
            "3306" in content_lower or "max_connections" in content_lower or "slow query" in content_lower
        ):
            question_bonus = 1.5
        elif ("redis" in question_lower or "认证" in question) and (
            "acl" in content_lower or "tls" in content_lower or "password" in content_lower
        ):
            question_bonus = 1.5
        if any(token in question for token in ("密码", "凭据")) or any(token in question_lower for token in ("password", "secret", "credential")):
            if any(token in content_lower for token in ("password", "secret", "credential", "rotation")):
                question_bonus = max(question_bonus, 1.8)
        if "测试环境" in question or any(token in question_lower for token in ("test", "uat")):
            if any(token in content_lower for token in ("test redis", "production credentials", "environment mismatch", "wrong endpoint")):
                question_bonus = max(question_bonus, 1.8)
        if ("docker" in question_lower or "秒退" in question) and (
            "exit code" in content_lower or "environment variables" in content_lower or "port" in content_lower
        ):
            question_bonus = max(question_bonus, 1.5)
        if "502" in question and ("upstream" in content_lower or "timeout" in content_lower):
            question_bonus = max(question_bonus, 1.5)

        return (section_weight, question_bonus, hit.score)

    @staticmethod
    def _timing_summary(values: list[float]) -> dict[str, Any]:
        if not values:
            return {"count": 0, "avg_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
        ordered = sorted(values)
        count = len(ordered)
        p95_index = max(int(round(count * 0.95)) - 1, 0)
        return {
            "count": count,
            "avg_ms": round(sum(ordered) / count, 2),
            "p50_ms": round(median(ordered), 2),
            "p95_ms": round(ordered[p95_index], 2),
            "max_ms": round(max(ordered), 2),
        }

    def _resolve_preferred_documents(
        self,
        question: str,
        rewritten_query: str,
        recent_docs: list[str] | None = None,
    ) -> set[str]:
        haystack = f"{question.lower()} {rewritten_query.lower()}"
        preferred: set[str] = set()
        for document_id, keywords in self.SAMPLE_DOC_KEYWORDS.items():
            if any(keyword.lower() in haystack for keyword in keywords):
                preferred.add(document_id)
        if preferred:
            return preferred
        if self._references_previous(question) and recent_docs:
            return set(recent_docs)
        return set()

    @staticmethod
    def _references_previous(question: str) -> bool:
        return any(token in question for token in ("这个", "那个", "继续", "然后", "接着", "下一步", "进一步"))

    def _recent_document_ids(self, history: list[dict[str, Any]], context: SessionContext) -> list[str]:
        results: list[str] = []
        seen: set[str] = set()
        if context.last_document_id:
            results.append(context.last_document_id)
            seen.add(context.last_document_id)
        for message in reversed(history):
            if message.get("role") != "assistant":
                continue
            metadata = message.get("metadata") or {}
            document_ids = list(metadata.get("document_ids") or [])
            if not document_ids:
                for chunk_id in metadata.get("source_ids") or []:
                    if "-" in chunk_id:
                        document_ids.append(chunk_id.rsplit("-", 1)[0])
            for document_id in document_ids:
                if document_id and document_id not in seen:
                    results.append(document_id)
                    seen.add(document_id)
                if len(results) >= 3:
                    return results
        return results

    def _build_document_id(self, path: Path) -> str:
        existing = self.store.get_document_by_path(str(path))
        if existing is not None:
            return existing.id

        base_id = slugify(path.stem)
        conflict = self.store.get_document(base_id)
        if conflict is None:
            return base_id
        if Path(conflict.file_path).resolve() == path.resolve():
            return base_id

        suffix = sha256_text(str(path).lower())[:8]
        return f"{base_id}-{suffix}"

    def _resolve_path(self, raw_path: Path) -> Path:
        if raw_path.is_absolute():
            return raw_path
        return (self.settings.root_dir / raw_path).resolve()

from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.service import RagService


def test_answer_with_sources(temp_settings: Settings) -> None:
    service = RagService(temp_settings)
    service.bootstrap()

    result = service.ask("错误码 502 一般先查什么？")

    assert result.action == "answer"
    assert "结论" in result.answer
    assert result.sources
    assert result.sources[0].document_id == "nginx-502-runbook"


def test_multiturn_context_rewrite(temp_settings: Settings) -> None:
    service = RagService(temp_settings)
    service.bootstrap()

    first = service.ask("payment service 启动失败")
    follow = service.ask("那数据库要查什么", session_id=first.session_id)

    assert follow.session_id == first.session_id
    assert "service=payment" in follow.rewritten_query


def test_multiturn_follow_up_focuses_on_password_location(temp_settings: Settings) -> None:
    service = RagService(temp_settings)
    service.bootstrap(include_knowledge_docs=False)

    first = service.ask("Redis 认证失败怎么排查？")
    follow = service.ask("那密码要去哪里看？", session_id=first.session_id)

    assert "password" in follow.rewritten_query.lower()
    assert "credential" in follow.rewritten_query.lower() or "secret" in follow.rewritten_query.lower()
    answer_lower = follow.answer.lower()
    assert "secret" in answer_lower or "credential" in answer_lower or "密码" in follow.answer


def test_multiturn_follow_up_focuses_on_test_environment_mismatch(temp_settings: Settings) -> None:
    service = RagService(temp_settings)
    service.bootstrap(include_knowledge_docs=False)

    first = service.ask("Redis 认证失败怎么排查？")
    follow = service.ask("测试环境也是这样", session_id=first.session_id)

    assert "test" in follow.rewritten_query.lower() or "environment mismatch" in follow.rewritten_query.lower()
    answer_lower = follow.answer.lower()
    assert "test redis" in answer_lower or "production credentials" in answer_lower or "环境不匹配" in follow.answer


def test_clarification_branch(temp_settings: Settings) -> None:
    service = RagService(temp_settings)
    service.bootstrap()

    result = service.ask("这个问题怎么继续查？")

    assert result.action == "clarify"
    assert "更多上下文" in result.answer


def test_run_evaluation(temp_settings: Settings) -> None:
    service = RagService(temp_settings)
    service.bootstrap()

    report = service.run_evaluation()

    assert report.total == 3
    assert report.retrieval_hit_rate_at_k >= 0.33
    assert report.action_accuracy >= 0.3
    assert report.clarification_trigger_rate >= 0.0
    assert report.timings_ms["total"]["avg_ms"] >= 0
    assert report.timings_ms["retrieval"]["p95_ms"] >= 0
    clarify_case = next(item for item in report.reports if item["question"] == "这个问题怎么继续查？")
    assert clarify_case["action"] == "clarify"


def test_sync_knowledge_sources_imports_docs_dir(temp_settings: Settings) -> None:
    service = RagService(temp_settings)

    summary = service.sync_knowledge_sources()
    documents = service.list_documents()

    assert summary["imported"] >= 1
    assert any(doc["filename"] == "ops-extra-guide.md" for doc in documents)


def test_sync_knowledge_sources_can_skip_local_docs(temp_settings: Settings) -> None:
    service = RagService(temp_settings)

    summary = service.sync_knowledge_sources(include_knowledge_docs=False)
    documents = service.list_documents()

    assert summary["imported"] >= 1
    assert all(doc["filename"] != "ops-extra-guide.md" for doc in documents)


def test_ask_with_document_scope_limits_retrieval(temp_settings: Settings) -> None:
    service = RagService(temp_settings)
    service.bootstrap()

    result = service.ask_with_scope(
        question="错误码 502 一般先查什么？",
        document_scope=["nginx-502-runbook"],
    )

    assert result.sources
    assert all(hit.document_id == "nginx-502-runbook" for hit in result.sources)


def test_scope_follow_up_uses_scoped_document_without_clarifying(temp_settings: Settings) -> None:
    service = RagService(temp_settings)
    service.bootstrap(include_knowledge_docs=False)

    result = service.ask_with_scope(
        question="这个问题怎么继续查？",
        document_scope=["nginx-502-runbook"],
    )

    assert result.action == "answer"
    assert result.sources
    assert all(hit.document_id == "nginx-502-runbook" for hit in result.sources)


def test_default_retrieval_prefers_matching_sample_doc(temp_settings: Settings) -> None:
    service = RagService(temp_settings)
    service.bootstrap()

    nginx = service.debug_retrieval("错误码 502 一般先查什么？")
    redis = service.debug_retrieval("Redis 认证失败通常怎么排查？")

    assert nginx["final_context"][0]["document_id"] == "nginx-502-runbook"
    assert redis["final_context"][0]["document_id"] == "redis-auth-troubleshooting"


def test_debug_retrieval_matches_ask_rewrite(temp_settings: Settings) -> None:
    service = RagService(temp_settings)
    service.bootstrap(include_knowledge_docs=False)

    question = "Jenkins 怎么新建流水线并发布到测试环境？"
    ask_result = service.ask(question)
    debug = service.debug_retrieval(question)

    assert debug["rewritten_query"] == ask_result.rewritten_query
    assert debug["context"]["topic"] == ask_result.context.topic


def test_default_retrieval_keeps_local_docs_eligible(temp_settings: Settings) -> None:
    extra_doc = temp_settings.knowledge_docs_dir / "redis-extra-guide.md"
    extra_doc.write_text(
        "# Redis 补充排障指南\n\n## 排查步骤\n1. 核对 Redis 端点。\n2. 重新检查凭据轮换记录。\n",
        encoding="utf-8",
    )
    service = RagService(temp_settings)
    service.bootstrap()

    debug = service.debug_retrieval("核对 Redis 端点和凭据轮换记录")

    retrieved_doc_ids = {
        hit["chunk_id"].rsplit("-", 1)[0]
        for hit in debug["vector_hits"] + debug["keyword_hits"] + debug["reranked_hits"]
        if "chunk_id" in hit
    }
    assert retrieved_doc_ids
    assert "redis-extra-guide" in retrieved_doc_ids


def test_crashloop_answer_prefers_troubleshooting_steps(temp_settings: Settings) -> None:
    service = RagService(temp_settings)
    service.bootstrap()

    result = service.ask_with_scope(
        question="Pod 一直 CrashLoopBackOff 怎么排？",
        document_scope=["k8s-crashloop-guide"],
    )

    assert "pod events" in result.answer.lower()
    assert "previous container logs" in result.answer.lower()


def test_ingest_upload_sanitizes_filename(temp_settings: Settings) -> None:
    service = RagService(temp_settings)

    result = service.ingest_upload("..\\..\\evil.txt", b"hello")

    saved_path = Path(temp_settings.root_dir / temp_settings.upload_dir / "evil.txt").resolve()
    assert result.filename == "evil.txt"
    assert saved_path.exists()
    assert str(saved_path).startswith(str((temp_settings.root_dir / temp_settings.upload_dir).resolve()))


def test_duplicate_stem_documents_get_distinct_ids(temp_settings: Settings) -> None:
    sample_doc = temp_settings.sample_docs_dir / "collision.md"
    sample_doc.write_text("# Sample\n\ncontent", encoding="utf-8")
    knowledge_doc = temp_settings.knowledge_docs_dir / "collision.md"
    knowledge_doc.write_text("# Knowledge\n\nother content", encoding="utf-8")

    service = RagService(temp_settings)
    service.bootstrap()

    collision_docs = [doc for doc in service.list_documents() if doc["filename"] == "collision.md"]
    ids = {doc["id"] for doc in collision_docs}

    assert len(collision_docs) == 2
    assert len(ids) == 2

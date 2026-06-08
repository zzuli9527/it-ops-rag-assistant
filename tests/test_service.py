from __future__ import annotations

from app.service import RagService


def test_answer_with_sources(temp_settings) -> None:
    service = RagService(temp_settings)
    service.bootstrap()

    result = service.ask("错误码 502 一般先查什么？")

    assert result.action == "answer"
    assert "结论" in result.answer
    assert result.sources
    assert result.sources[0].document_id == "nginx-502-runbook"


def test_multiturn_context_rewrite(temp_settings) -> None:
    service = RagService(temp_settings)
    service.bootstrap()

    first = service.ask("payment service 启动失败")
    follow = service.ask("那数据库要查什么", session_id=first.session_id)

    assert follow.session_id == first.session_id
    assert "service=payment" in follow.rewritten_query


def test_clarification_branch(temp_settings) -> None:
    service = RagService(temp_settings)
    service.bootstrap()

    result = service.ask("这个问题怎么继续查？")

    assert result.action == "clarify"
    assert "更多上下文" in result.answer


def test_run_evaluation(temp_settings) -> None:
    service = RagService(temp_settings)
    service.bootstrap()

    report = service.run_evaluation()

    assert report.total == 3
    assert report.retrieval_hit_rate_at_k >= 0.33
    assert report.clarification_trigger_rate >= 0.3
    assert report.timings_ms["total"]["avg_ms"] >= 0
    assert report.timings_ms["retrieval"]["p95_ms"] >= 0
    clarify_case = next(item for item in report.reports if item["question"] == "这个问题怎么继续查？")
    assert clarify_case["action"] == "clarify"


def test_sync_knowledge_sources_imports_docs_dir(temp_settings) -> None:
    service = RagService(temp_settings)

    summary = service.sync_knowledge_sources()
    documents = service.list_documents()

    assert summary["imported"] >= 1
    assert any(doc["filename"] == "ops-extra-guide.md" for doc in documents)


def test_ask_with_document_scope_limits_retrieval(temp_settings) -> None:
    service = RagService(temp_settings)
    service.bootstrap()

    result = service.ask_with_scope(
        question="错误码 502 一般先查什么？",
        document_scope=["nginx-502-runbook"],
    )

    assert result.sources
    assert all(hit.document_id == "nginx-502-runbook" for hit in result.sources)


def test_default_retrieval_prefers_matching_sample_doc(temp_settings) -> None:
    service = RagService(temp_settings)
    service.bootstrap()

    nginx = service.debug_retrieval("错误码 502 一般先查什么？")
    redis = service.debug_retrieval("Redis 认证失败通常怎么排查？")

    assert nginx["final_context"][0]["document_id"] == "nginx-502-runbook"
    assert redis["final_context"][0]["document_id"] == "redis-auth-troubleshooting"


def test_answer_sources_prefer_sample_docs_only(temp_settings) -> None:
    service = RagService(temp_settings)
    service.bootstrap()

    result = service.ask("Redis 认证失败通常怎么排查？")

    assert result.sources
    assert all(hit.document_id in service.sample_document_ids for hit in result.sources)
    assert result.sources[0].document_id == "redis-auth-troubleshooting"


def test_crashloop_answer_prefers_troubleshooting_steps(temp_settings) -> None:
    service = RagService(temp_settings)
    service.bootstrap()

    result = service.ask_with_scope(
        question="Pod 一直 CrashLoopBackOff 怎么排？",
        document_scope=["k8s-crashloop-guide"],
    )

    assert "pod events" in result.answer.lower()
    assert "previous container logs" in result.answer.lower()

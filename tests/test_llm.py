from __future__ import annotations

from app.config import Settings
from app.llm import LocalReasoner, OpenAICompatibleReasoner, build_reasoner
from app.models import RetrievalHit, SessionContext
from app.prompting import PromptManager
from app.service import RagService


class StubClient:
    def __init__(self, response: str) -> None:
        self.response = response

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        del system_prompt, user_prompt
        return self.response


def _make_hit(title: str, content: str, section_path: list[str]) -> RetrievalHit:
    return RetrievalHit(
        chunk_id="chunk-1",
        document_id="doc-1",
        score=0.9,
        vector_score=0.9,
        keyword_score=0.8,
        title=title,
        content=content,
        page=None,
        section_path=section_path,
        metadata={},
    )


def test_build_reasoner_returns_local_without_credentials(temp_settings: Settings) -> None:
    prompt_manager = PromptManager(temp_settings.root_dir / "app" / "prompts")

    reasoner = build_reasoner(
        llm_mode="openai_compatible",
        llm_base_url="https://example.invalid",
        llm_api_key="",
        llm_model="placeholder-model",
        prompt_manager=prompt_manager,
        answer_min_score=0.08,
    )

    assert isinstance(reasoner, LocalReasoner)


def test_service_uses_local_reasoner_in_tests(temp_settings: Settings) -> None:
    service = RagService(temp_settings)

    assert isinstance(service.reasoner, LocalReasoner)


def test_extract_display_text_prefers_missing_context_field() -> None:
    raw = '{"missing_context":"请提供你正在排查的具体服务名称、组件名称或上一条故障现象，以便我给出下一步的排查方向。"}'

    text = OpenAICompatibleReasoner._extract_display_text(raw)

    assert text == "请提供你正在排查的具体服务名称、组件名称或上一条故障现象，以便我给出下一步的排查方向。"


def test_extract_display_text_keeps_plain_text() -> None:
    raw = "请补充服务名、错误码和关键日志。"

    text = OpenAICompatibleReasoner._extract_display_text(raw)

    assert text == raw


def test_grounding_check_rejects_unseen_technology() -> None:
    hits = [
        _make_hit(
            title="Nginx 502 排障手册",
            content="检查上游服务健康状态和网关超时配置。",
            section_path=["快速检查"],
        )
    ]

    grounded = OpenAICompatibleReasoner._is_grounded_answer(
        "结论：先检查 Redis 服务状态和网关超时配置。",
        "错误码 502 一般先查什么？",
        hits,
    )

    assert grounded is False


def test_grounding_check_accepts_generic_upstream_answer() -> None:
    hits = [
        _make_hit(
            title="Nginx 502 排障手册",
            content="检查上游服务健康状态和网关超时配置。",
            section_path=["快速检查"],
        )
    ]

    grounded = OpenAICompatibleReasoner._is_grounded_answer(
        "结论：先检查上游服务健康状态和网关超时配置。",
        "错误码 502 一般先查什么？",
        hits,
    )

    assert grounded is True


def test_openai_reasoner_extract_context_merges_llm_fields(temp_settings: Settings) -> None:
    prompt_manager = PromptManager(temp_settings.root_dir / "app" / "prompts")
    fallback = LocalReasoner(prompt_manager, answer_min_score=0.08)
    reasoner = OpenAICompatibleReasoner(
        client=StubClient(
            '{"topic":"payment","task":"troubleshoot","service_name":"payment","component":"database","need_clarification":false}'
        ),
        prompt_manager=prompt_manager,
        fallback=fallback,
    )

    context = reasoner.extract_context("支付服务启动失败后，数据库要看什么？", SessionContext())

    assert context.topic == "payment"
    assert context.task == "troubleshoot"
    assert context.service_name == "payment"
    assert context.component == "database"
    assert context.need_clarification is False
    assert context.last_question == "支付服务启动失败后，数据库要看什么？"


def test_openai_reasoner_normalizes_llm_fields(temp_settings: Settings) -> None:
    prompt_manager = PromptManager(temp_settings.root_dir / "app" / "prompts")
    fallback = LocalReasoner(prompt_manager, answer_min_score=0.08)
    reasoner = OpenAICompatibleReasoner(
        client=StubClient(
            '{"topic":"Redis","task":"Deploy","environment":"PROD","service_name":"Redis","component":"Database","suspected_issue":"Auth"}'
        ),
        prompt_manager=prompt_manager,
        fallback=fallback,
    )

    context = reasoner.extract_context("Redis 发布失败了", SessionContext())

    assert context.topic == "redis"
    assert context.task == "deploy"
    assert context.environment == "prod"
    assert context.service_name == "redis"
    assert context.component == "database"
    assert context.suspected_issue == "authentication"


def test_local_reasoner_extracts_general_usage_context(temp_settings: Settings) -> None:
    prompt_manager = PromptManager(temp_settings.root_dir / "app" / "prompts")
    reasoner = LocalReasoner(prompt_manager, answer_min_score=0.08)

    context = reasoner.extract_context("Jenkins 怎么新建流水线并发布到测试环境？", SessionContext())

    assert context.topic == "jenkins"
    assert context.task == "create_pipeline"
    assert context.environment == "test"


def test_local_reasoner_resets_issue_fields_on_new_topic(temp_settings: Settings) -> None:
    prompt_manager = PromptManager(temp_settings.root_dir / "app" / "prompts")
    reasoner = LocalReasoner(prompt_manager, answer_min_score=0.08)
    previous = SessionContext(
        topic="redis",
        task="troubleshoot",
        service_name="redis",
        component="database",
        suspected_issue="authentication",
        error_code="NOAUTH",
    )

    context = reasoner.extract_context("Jenkins 怎么新建流水线？", previous)

    assert context.topic == "jenkins"
    assert context.task == "create_pipeline"
    assert context.service_name == "jenkins"
    assert context.component is None
    assert context.suspected_issue is None
    assert context.error_code is None


def test_local_reasoner_prefers_troubleshoot_for_mixed_intent(temp_settings: Settings) -> None:
    prompt_manager = PromptManager(temp_settings.root_dir / "app" / "prompts")
    reasoner = LocalReasoner(prompt_manager, answer_min_score=0.08)

    configure_failure = reasoner.extract_context("发布系统配置失败怎么排查？", SessionContext())
    usage_error = reasoner.extract_context("Redis 使用报错怎么排查？", SessionContext())

    assert configure_failure.task == "troubleshoot"
    assert usage_error.task == "troubleshoot"


def test_local_reasoner_starts_fresh_for_generic_independent_question(temp_settings: Settings) -> None:
    prompt_manager = PromptManager(temp_settings.root_dir / "app" / "prompts")
    reasoner = LocalReasoner(prompt_manager, answer_min_score=0.08)
    previous = SessionContext(
        topic="redis",
        task="troubleshoot",
        service_name="redis",
        environment="prod",
        component="database",
        suspected_issue="authentication",
    )

    context = reasoner.extract_context("怎么登录？", previous)
    rewritten = reasoner.rewrite_query("怎么登录？", context, [])

    assert context.topic is None
    assert context.service_name is None
    assert context.environment is None
    assert context.component is None
    assert context.suspected_issue is None
    assert "redis" not in rewritten.lower()
    assert "database" not in rewritten.lower()

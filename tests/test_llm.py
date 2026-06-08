from __future__ import annotations

from app.llm import LocalReasoner, OpenAICompatibleReasoner, build_reasoner
from app.prompting import PromptManager
from app.service import RagService


def test_build_reasoner_returns_local_without_credentials(temp_settings) -> None:
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


def test_service_uses_local_reasoner_in_tests(temp_settings) -> None:
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
        type(
            "Hit",
            (),
            {
                "title": "Nginx 502 Troubleshooting Runbook",
                "content": "Check upstream service health and gateway timeout settings.",
                "section_path": ["Quick Checks"],
            },
        )()
    ]

    grounded = OpenAICompatibleReasoner._is_grounded_answer(
        "结论：先检查 Redis 服务状态和网关超时配置。",
        "错误码 502 一般先查什么？",
        hits,  # type: ignore[arg-type]
    )

    assert grounded is False


def test_grounding_check_accepts_generic_upstream_answer() -> None:
    hits = [
        type(
            "Hit",
            (),
            {
                "title": "Nginx 502 Troubleshooting Runbook",
                "content": "Check upstream service health and gateway timeout settings.",
                "section_path": ["Quick Checks"],
            },
        )()
    ]

    grounded = OpenAICompatibleReasoner._is_grounded_answer(
        "结论：先检查上游服务健康状态和网关超时配置。",
        "错误码 502 一般先查什么？",
        hits,  # type: ignore[arg-type]
    )

    assert grounded is True

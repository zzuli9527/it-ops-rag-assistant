from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any, Protocol, cast

import httpx

from .models import RetrievalHit, SessionContext
from .prompting import PromptManager
from .utils import mixed_tokenize, normalize_whitespace


class Reasoner(Protocol):
    def rewrite_query(self, question: str, context: SessionContext, history: list[dict[str, Any]]) -> str: ...

    def extract_context(self, question: str, context: SessionContext) -> SessionContext: ...

    def should_clarify(
        self,
        question: str,
        hits: list[RetrievalHit],
        context: SessionContext,
    ) -> tuple[bool, list[str]]: ...

    def build_clarification(self, question: str, context: SessionContext, reasons: list[str]) -> str: ...

    def build_answer(self, question: str, hits: list[RetrievalHit], context: SessionContext) -> str: ...


class ChatClient(Protocol):
    def chat(self, system_prompt: str, user_prompt: str) -> str: ...


class LocalReasoner:
    FOLLOW_UP_RE = re.compile(r"(这个|那个|继续|然后|接着|下一步|进一步|怎么继续|还要|还需要)")
    SERVICE_RE = re.compile(r"\b(mysql|redis|nginx|docker|kubernetes|k8s|gateway|payment|api)\b", re.I)
    EXPLICIT_ENTITY_RE = re.compile(
        r"(mysql|redis|nginx|docker|kubernetes|k8s|pod|数据库|缓存|网关|容器|探针|日志|502|auth|认证)",
        re.I,
    )
    TOPIC_PATTERNS = (
        (re.compile(r"\b(jenkins|redis|mysql|nginx|docker|kubernetes|k8s|gateway|payment|api)\b", re.I), None),
        (re.compile(r"(发布系统|构建平台|发布平台|流水线平台)"), "release-platform"),
        (re.compile(r"([A-Za-z][A-Za-z0-9_-]+)\s*(?:service|服务)\b", re.I), "__group__"),
        (re.compile(r"([A-Za-z0-9_\-\u4e00-\u9fa5]+)\s*(?:系统|平台)"), "__group__"),
    )
    TASK_PATTERNS = (
        ("新建流水线", "create_pipeline"),
        ("创建流水线", "create_pipeline"),
        ("查看日志", "view_logs"),
        ("查日志", "view_logs"),
        ("回滚", "rollback"),
        ("发布", "deploy"),
        ("上线", "deploy"),
        ("登录", "login"),
        ("配置", "configure"),
        ("设置", "configure"),
        ("怎么用", "usage"),
        ("如何使用", "usage"),
        ("使用", "usage"),
    )
    TROUBLESHOOT_PATTERNS = ("排查", "故障", "报错", "失败", "异常", "error", "issue", "problem")
    TOPIC_ALIASES = {
        "k8s": "kubernetes",
        "发布系统": "release-platform",
        "发布平台": "release-platform",
        "构建平台": "release-platform",
        "流水线平台": "release-platform",
    }
    TASK_ALIASES = {
        "create_pipeline": "create_pipeline",
        "create-pipeline": "create_pipeline",
        "deploy": "deploy",
        "release": "deploy",
        "rollback": "rollback",
        "login": "login",
        "configure": "configure",
        "config": "configure",
        "view_logs": "view_logs",
        "view-logs": "view_logs",
        "usage": "usage",
        "troubleshoot": "troubleshoot",
    }
    ENV_ALIASES = {
        "prod": "prod",
        "production": "prod",
        "prd": "prod",
        "test": "test",
        "uat": "test",
        "dev": "dev",
        "staging": "staging",
        "pre": "staging",
        "preprod": "staging",
    }
    COMPONENT_ALIASES = {
        "database": "database",
        "db": "database",
        "connection_pool": "connection_pool",
        "connection-pool": "connection_pool",
        "container": "container",
        "gateway": "gateway",
        "logging": "logging",
        "logs": "logging",
        "k8s": "kubernetes",
        "kubernetes": "kubernetes",
        "docker": "docker",
        "probe": "probe",
        "pod": "pod",
    }
    ISSUE_ALIASES = {
        "bad_gateway": "bad_gateway",
        "bad-gateway": "bad_gateway",
        "timeout": "timeout",
        "connection_refused": "connection_refused",
        "connection-refused": "connection_refused",
        "crash_loop": "crash_loop",
        "crash-loop": "crash_loop",
        "authentication": "authentication",
        "auth": "authentication",
        "instant_exit": "instant_exit",
        "instant-exit": "instant_exit",
    }
    GENERIC_INDEPENDENT_TASKS = {"login", "usage", "create_pipeline", "configure", "view_logs"}
    FOLLOW_UP_FOCUS_RULES = (
        (("密码", "凭据", "secret", "credential"), ("password", "credential", "secret", "rotation record")),
        (("acl", "用户"), ("acl", "user permissions")),
        (("tls", "证书"), ("tls", "certificate", "bootstrap mode")),
        (("端点", "endpoint"), ("endpoint", "port", "cluster name")),
        (("测试环境", "test", "uat"), ("test environment", "environment mismatch", "test redis", "credentials")),
        (("生产环境", "prod", "production"), ("production environment", "environment mismatch", "production credentials")),
    )
    VERSION_RE = re.compile(r"\b(v?\d+\.\d+(?:\.\d+)?|release[-_ ]?\d+|build[-_ ]?\d+|[A-Za-z0-9._-]+:\d+\.\d+(?:\.\d+)?)\b", re.I)

    def __init__(self, prompt_manager: PromptManager, answer_min_score: float) -> None:
        self.prompt_manager = prompt_manager
        self.answer_min_score = answer_min_score

    def rewrite_query(self, question: str, context: SessionContext, history: list[dict[str, Any]]) -> str:
        pieces: list[str] = [question.strip()]
        question_lower = question.lower()
        follow_up = self._references_previous(question)

        if context.topic and context.topic.lower() not in question_lower:
            pieces.append(f"topic={context.topic}")
        if context.task and context.task.lower() not in question_lower:
            pieces.append(f"task={context.task}")
        if context.version and context.version.lower() not in question_lower:
            pieces.append(f"version={context.version}")
        if context.service_name and context.service_name.lower() not in question_lower:
            if follow_up or "服务" not in question:
                pieces.append(f"service={context.service_name}")
        if context.error_code and context.error_code.lower() not in question_lower:
            pieces.append(f"error_code={context.error_code}")
        if context.environment and context.environment not in question_lower:
            pieces.append(f"env={context.environment}")
        if context.component and context.component not in question_lower:
            pieces.append(context.component)
        if context.suspected_issue and context.suspected_issue not in question_lower:
            pieces.append(context.suspected_issue)
        if follow_up and context.last_document_id:
            pieces.append(f"document={context.last_document_id}")

        if follow_up and history:
            last_user_messages = [msg["content"] for msg in history if msg["role"] == "user"][-2:]
            pieces.extend(last_user_messages[-1:])

        pieces.extend(self._follow_up_focus_terms(question))
        pieces.extend(self._query_expansions(question, context))
        return normalize_whitespace(" ".join(dict.fromkeys(piece for piece in pieces if piece)))

    def extract_context(self, question: str, context: SessionContext) -> SessionContext:
        merged = SessionContext(**asdict(context))
        merged.last_question = question

        topic = self._extract_topic(question)
        service_name = self._extract_service_name(question, topic)
        task = self._extract_task(question)
        topic_changed = self._topic_changed(context, topic, service_name)
        if topic_changed:
            self._reset_topic_specific_fields(merged)
        elif self._should_start_fresh_context(question, topic, service_name, task):
            self._reset_full_context(merged)

        error_code = re.search(r"\b([45]\d{2}|[A-Z]{1,4}\d{3,5})\b", question)
        if error_code:
            merged.error_code = error_code.group(1)
        version = self.VERSION_RE.search(question)
        if version:
            merged.version = version.group(1)

        if topic:
            merged.topic = topic

        if service_name:
            merged.service_name = service_name
        elif merged.topic and re.fullmatch(r"[a-z0-9_-]+", merged.topic):
            merged.service_name = merged.topic

        if task:
            merged.task = task

        env_patterns = {
            "prod": "prod",
            "生产": "prod",
            "staging": "staging",
            "test": "test",
            "测试": "test",
            "dev": "dev",
        }
        for raw, label in env_patterns.items():
            if raw.lower() in question.lower():
                merged.environment = label
                break

        component_patterns = {
            "数据库": "database",
            "db": "database",
            "连接池": "connection_pool",
            "容器": "container",
            "网关": "gateway",
            "日志": "logging",
            "k8s": "kubernetes",
            "docker": "docker",
            "探针": "probe",
            "pod": "pod",
        }
        for raw, label in component_patterns.items():
            if raw.lower() in question.lower():
                merged.component = label
                break

        issue_patterns = {
            "502": "bad_gateway",
            "超时": "timeout",
            "connection refused": "connection_refused",
            "拒绝连接": "connection_refused",
            "crashloop": "crash_loop",
            "认证": "authentication",
            "auth": "authentication",
            "秒退": "instant_exit",
        }
        for raw, label in issue_patterns.items():
            if raw.lower() in question.lower():
                merged.suspected_issue = label
                break

        merged.need_clarification = self._should_mark_missing_context(question, merged)

        return merged

    def should_clarify(
        self,
        question: str,
        hits: list[RetrievalHit],
        context: SessionContext,
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        top_score = hits[0].score if hits else 0.0
        if top_score < self.answer_min_score:
            reasons.append("knowledge_low_confidence")
        if self._references_previous(question) and not any(
            [
                context.topic,
                context.task,
                context.service_name,
                context.error_code,
                context.component,
                context.suspected_issue,
                context.last_document_id,
            ]
        ):
            reasons.append("missing_reference")
        if len(question.strip()) < 6 and not self.EXPLICIT_ENTITY_RE.search(question):
            reasons.append("missing_entity")
        if context.need_clarification and "knowledge_low_confidence" not in reasons:
            reasons.append("missing_context")
        if self._references_previous(question) and hits and any([context.topic, context.service_name, context.last_document_id]):
            if self._follow_up_focus_terms(question) or context.environment:
                reasons = [reason for reason in reasons if reason not in {"missing_reference", "missing_entity", "missing_context"}]
        return bool(reasons), reasons

    def build_clarification(self, question: str, context: SessionContext, reasons: list[str]) -> str:
        del question
        pieces = ["我需要更多上下文后再给出可靠结论。"]
        if "missing_reference" in reasons:
            pieces.append("请补充你指的是哪个服务、组件，或者上一条故障现象。")
        elif "missing_entity" in reasons:
            pieces.append("请至少提供服务名、错误码、环境或关键日志中的一项。")
        else:
            pieces.append("请提供服务名、错误码、环境、关键日志中的任意两项。")
        if context.topic:
            pieces.append(f"当前已识别主题：{context.topic}")
        elif context.service_name:
            pieces.append(f"当前已识别服务：{context.service_name}")
        if context.error_code:
            pieces.append(f"当前已识别错误码：{context.error_code}")
        return " ".join(pieces)

    def build_answer(self, question: str, hits: list[RetrievalHit], context: SessionContext) -> str:
        if not hits:
            return "没有检索到足够可信的知识片段，请补充更具体的问题描述。"

        ranked_hits = sorted(hits, key=self._answer_hit_sort_key, reverse=True)
        conclusion = self._build_conclusion(question, ranked_hits, context)
        steps = self._collect_steps(ranked_hits, limit=4)
        risks = self._build_risk_hint(context, ranked_hits)

        source_lines: list[str] = []
        seen_chunks: set[str] = set()
        for hit in ranked_hits:
            if hit.chunk_id in seen_chunks:
                continue
            seen_chunks.add(hit.chunk_id)
            source_lines.append(f"- {self._source_label(hit)}")
            if len(source_lines) >= 3:
                break

        return "\n".join(
            [
                f"结论：{conclusion}",
                "",
                "排查步骤：",
                *[f"{idx + 1}. {step}" for idx, step in enumerate(steps)],
                "",
                f"风险提示：{risks}",
                "",
                "引用来源：",
                *source_lines,
            ]
        )

    @classmethod
    def _references_previous(cls, question: str) -> bool:
        return bool(cls.FOLLOW_UP_RE.search(question))

    @staticmethod
    def _answer_hit_sort_key(hit: RetrievalHit) -> tuple[float, float]:
        return (LocalReasoner._section_priority(hit), hit.score)

    @staticmethod
    def _section_priority(hit: RetrievalHit) -> float:
        section = " ".join(hit.section_path).lower()
        if "ordered troubleshooting steps" in section:
            return 6.0
        if "quick checks" in section or "diagnostic signals" in section:
            return 5.0
        if "steps" in section or "checklist" in section:
            return 4.5
        if "common root causes" in section:
            return 3.5
        if "risk notes" in section or "risk" in section:
            return 1.5
        if "symptoms" in section:
            return 1.0
        return 2.5

    def _query_expansions(self, question: str, context: SessionContext) -> list[str]:
        question_lower = question.lower()
        expansions: list[str] = []
        if "502" in question or context.suspected_issue == "bad_gateway":
            expansions.extend(["gateway", "upstream service", "timeout", "readiness probes"])
        if "redis" in question_lower or context.topic == "redis" or context.service_name == "redis" or context.suspected_issue == "authentication":
            expansions.extend(["redis", "password", "acl", "tls", "endpoint"])
        if "mysql" in question_lower or context.topic == "mysql" or "数据库" in question or context.component == "database":
            expansions.extend(["mysql", "port 3306", "max_connections", "slow query logs"])
        if "crashloop" in question_lower or context.suspected_issue == "crash_loop":
            expansions.extend(["kubernetes", "pod events", "previous container logs", "probe"])
        if "docker" in question_lower or "秒退" in question or context.suspected_issue == "instant_exit":
            expansions.extend(["docker", "exit code", "port", "environment variables"])
        if context.task == "create_pipeline":
            expansions.extend(["pipeline", "job configuration", "parameters"])
        elif context.task == "deploy":
            expansions.extend(["deployment steps", "release", "environment variables"])
        elif context.task == "rollback":
            expansions.extend(["rollback", "version selection", "release history"])
        elif context.task == "usage":
            expansions.extend(["user guide", "steps", "configuration"])
        return expansions

    def _build_conclusion(self, question: str, hits: list[RetrievalHit], context: SessionContext) -> str:
        question_lower = question.lower()
        evidence = " ".join(
            " ".join(hit.section_path) + " " + hit.content
            for hit in hits
        ).lower()

        if any(token in question_lower for token in ("password", "secret", "credential")) or any(token in question for token in ("密码", "凭据")):
            return "先核对应用侧实际加载的密码或 secret，再对照最近一次凭据轮换记录，确认是否仍在使用旧凭据。"
        if "测试环境" in question or "test" in question_lower or context.environment == "test":
            return "优先排查环境不匹配，确认应用是否连到了测试 Redis，却使用了生产凭据或错误的集群端点。"

        if "502" in question or context.suspected_issue == "bad_gateway":
            return "先检查上游服务健康状态、超时设置，以及网关转发配置是否发生变化。"
        if "crashloop" in question_lower or context.suspected_issue == "crash_loop":
            return "优先看 Pod events、previous container logs、探针配置和依赖可达性，先判断是启动失败、探针误判还是依赖未就绪。"
        if "redis" in question_lower or "redis" in evidence:
            return "优先确认密码、ACL 用户、TLS 配置和目标 Redis 实例是否匹配，再核对最近一次凭据变更。"
        if "mysql" in question_lower or "数据库" in question or "max_connections" in evidence:
            return "先确认 3306 连通性，再检查 max_connections、慢查询和连接池配置。"
        if "docker" in question_lower or "exit code" in evidence:
            return "优先查看容器 exit code、端口占用、环境变量和依赖服务可用性。"
        lead = hits[0]
        return f"优先按 {lead.title} 对应的检查项排查。"

    @staticmethod
    def _collect_steps(hits: list[RetrievalHit], limit: int) -> list[str]:
        results: list[str] = []
        seen: set[str] = set()
        for hit in hits:
            for raw_line in hit.content.splitlines():
                cleaned = re.sub(r"^\s*(?:[-*]|\d+\.)\s*", "", raw_line).strip()
                cleaned = normalize_whitespace(cleaned)
                if len(cleaned) < 10:
                    continue
                if cleaned.lower() in seen:
                    continue
                seen.add(cleaned.lower())
                results.append(cleaned)
                if len(results) >= limit:
                    return results
        return results or [
            "查看最新错误日志，并对照最近一次发布或配置变更。",
            "确认服务健康状态、网络连通性和依赖系统状态。",
        ]

    @staticmethod
    def _build_risk_hint(context: SessionContext, hits: list[RetrievalHit]) -> str:
        evidence = " ".join(hit.content.lower() for hit in hits)
        if context.environment == "prod":
            return "生产环境先确认影响范围，再做重启、扩容或配置回滚。"
        if "mysql" in evidence or "database" in evidence:
            return "涉及数据库时避免直接清理连接池或强杀会话，先确认慢查询和事务影响。"
        return "执行操作前先固定问题现场，保留日志、告警时间线和最近一次变更记录。"

    @classmethod
    def _follow_up_focus_terms(cls, question: str) -> list[str]:
        lowered = question.lower()
        results: list[str] = []
        for patterns, expansions in cls.FOLLOW_UP_FOCUS_RULES:
            if any(pattern.lower() in lowered or pattern in question for pattern in patterns):
                results.extend(expansions)
        return results

    @classmethod
    def _extract_topic(cls, question: str) -> str | None:
        for pattern, replacement in cls.TOPIC_PATTERNS:
            match = pattern.search(question)
            if not match:
                continue
            if replacement == "__group__":
                return cls.normalize_topic(match.group(1))
            if replacement:
                return cls.normalize_topic(replacement)
            return cls.normalize_topic(match.group(1))
        return None

    @classmethod
    def _extract_task(cls, question: str) -> str | None:
        lowered = question.lower()
        if any(phrase.lower() in lowered for phrase in cls.TROUBLESHOOT_PATTERNS):
            return "troubleshoot"
        for phrase, label in cls.TASK_PATTERNS:
            if phrase.lower() in lowered:
                return cls.normalize_task(label)
        return None

    @classmethod
    def _extract_service_name(cls, question: str, topic: str | None) -> str | None:
        generic_service = re.search(r"\b([A-Za-z][A-Za-z0-9_-]+)\s+service\b", question, re.I)
        chinese_service = re.search(r"([A-Za-z][A-Za-z0-9_-]+)\s*服务", question, re.I)
        named_service = cls.SERVICE_RE.search(question)
        if generic_service:
            return generic_service.group(1).lower()
        if chinese_service:
            return chinese_service.group(1).lower()
        if named_service:
            return named_service.group(1).lower()
        if topic and re.fullmatch(r"[a-z0-9_-]+", topic):
            return topic
        return None

    @staticmethod
    def _topic_changed(context: SessionContext, topic: str | None, service_name: str | None) -> bool:
        current_subject = context.topic or context.service_name
        next_subject = topic or service_name
        if not current_subject or not next_subject:
            return False
        return current_subject.lower() != next_subject.lower()

    @staticmethod
    def _reset_topic_specific_fields(context: SessionContext) -> None:
        context.task = None
        context.version = None
        context.error_code = None
        context.component = None
        context.suspected_issue = None
        context.need_clarification = None

    @classmethod
    def _should_start_fresh_context(
        cls,
        question: str,
        topic: str | None,
        service_name: str | None,
        task: str | None,
    ) -> bool:
        if cls._references_previous(question):
            return False
        if topic or service_name:
            return False
        return task in cls.GENERIC_INDEPENDENT_TASKS

    @staticmethod
    def _reset_full_context(context: SessionContext) -> None:
        context.topic = None
        context.task = None
        context.version = None
        context.need_clarification = None
        context.service_name = None
        context.error_code = None
        context.environment = None
        context.component = None
        context.suspected_issue = None
        context.last_document_id = None

    @classmethod
    def normalize_topic(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_whitespace(value).lower()
        if not normalized:
            return None
        return cls.TOPIC_ALIASES.get(normalized, normalized)

    @classmethod
    def normalize_task(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_whitespace(value).lower().replace(" ", "_")
        return cls.TASK_ALIASES.get(normalized, normalized or None)

    @classmethod
    def normalize_environment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_whitespace(value).lower().replace(" ", "")
        return cls.ENV_ALIASES.get(normalized, normalized or None)

    @classmethod
    def normalize_component(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_whitespace(value).lower().replace(" ", "_")
        return cls.COMPONENT_ALIASES.get(normalized, normalized or None)

    @classmethod
    def normalize_issue(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_whitespace(value).lower().replace(" ", "_")
        return cls.ISSUE_ALIASES.get(normalized, normalized or None)

    @classmethod
    def _should_mark_missing_context(cls, question: str, context: SessionContext) -> bool:
        if not cls._references_previous(question):
            return False
        return not any([context.topic, context.service_name, context.error_code, context.component, context.last_document_id])

    @staticmethod
    def _source_label(hit: RetrievalHit) -> str:
        section = " / ".join(hit.section_path) if hit.section_path else hit.title
        page = f" page={hit.page}" if hit.page else ""
        return f"{hit.document_id}: {section}{page}"


class OpenAICompatibleChatClient:
    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=45.0,
        )
        response.raise_for_status()
        data = response.json()
        return str(data["choices"][0]["message"]["content"])


class OpenAICompatibleReasoner:
    GROUNDING_KEYWORDS = (
        "redis",
        "mysql",
        "docker",
        "kubernetes",
        "k8s",
        "nginx",
        "gateway",
        "api",
        "database",
        "pod",
        "容器",
        "数据库",
        "网关",
        "上游服务",
        "认证",
        "tls",
        "acl",
        "upstream service",
    )
    GROUNDING_ALIASES = {
        "upstream service": ("上游服务",),
        "上游服务": ("upstream service",),
        "gateway": ("网关",),
        "网关": ("gateway",),
        "database": ("数据库", "mysql"),
        "pod": ("容器", "kubernetes", "k8s"),
        "认证": ("authentication", "auth"),
    }

    def __init__(
        self,
        client: ChatClient,
        prompt_manager: PromptManager,
        fallback: LocalReasoner,
    ) -> None:
        self.client = client
        self.prompt_manager = prompt_manager
        self.fallback = fallback

    def rewrite_query(self, question: str, context: SessionContext, history: list[dict[str, Any]]) -> str:
        fallback_query = self.fallback.rewrite_query(question, context, history)
        system_prompt = (
            self.prompt_manager.load("query_rewrite")
            or "Rewrite the question into one retrieval query. Keep key entities and stay concise."
        )
        payload = {
            "question": question,
            "session_context": asdict(context),
            "recent_history": history[-4:],
            "fallback_query": fallback_query,
        }
        try:
            response = self.client.chat(system_prompt, json.dumps(payload, ensure_ascii=False))
            rewritten = normalize_whitespace(response.splitlines()[0].strip())
            if not self._rewrite_is_usable(question, rewritten, fallback_query):
                return fallback_query
            return rewritten
        except Exception:
            return fallback_query

    def extract_context(self, question: str, context: SessionContext) -> SessionContext:
        fallback_context = self.fallback.extract_context(question, context)
        system_prompt = (
            self.prompt_manager.load("context_extraction")
            or (
                "Extract JSON with topic, task, environment, version, error_code, component, "
                "suspected_issue, need_clarification, service_name."
            )
        )
        payload = {
            "question": question,
            "current_context": asdict(context),
            "schema": {
                "topic": "string|null",
                "task": "string|null",
                "environment": "string|null",
                "version": "string|null",
                "service_name": "string|null",
                "error_code": "string|null",
                "component": "string|null",
                "suspected_issue": "string|null",
                "need_clarification": "boolean|null",
            },
        }
        try:
            raw = self.client.chat(system_prompt, json.dumps(payload, ensure_ascii=False))
            parsed = self._extract_json(raw)
            merged = asdict(fallback_context)
            normalizers = {
                "topic": self.fallback.normalize_topic,
                "task": self.fallback.normalize_task,
                "environment": self.fallback.normalize_environment,
                "version": lambda value: normalize_whitespace(value) if value else None,
                "service_name": lambda value: normalize_whitespace(value).lower() if value else None,
                "error_code": lambda value: normalize_whitespace(value) if value else None,
                "component": self.fallback.normalize_component,
                "suspected_issue": self.fallback.normalize_issue,
            }
            for key, normalizer in normalizers.items():
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    normalized = normalizer(value.strip())
                    if normalized:
                        merged[key] = normalized
            if not merged.get("topic") and merged.get("service_name"):
                merged["topic"] = merged["service_name"]
            merged["last_question"] = question
            return SessionContext(**merged)
        except Exception:
            return fallback_context

    def should_clarify(
        self,
        question: str,
        hits: list[RetrievalHit],
        context: SessionContext,
    ) -> tuple[bool, list[str]]:
        return self.fallback.should_clarify(question, hits, context)

    def build_clarification(self, question: str, context: SessionContext, reasons: list[str]) -> str:
        fallback = self.fallback.build_clarification(question, context, reasons)
        system_prompt = (
            self.prompt_manager.load("clarification")
            or "Ask one concise clarification question before answering."
        )
        payload = {
            "question": question,
            "context": asdict(context),
            "reasons": reasons,
            "fallback": fallback,
        }
        try:
            response = self.client.chat(system_prompt, json.dumps(payload, ensure_ascii=False))
            extracted = self._extract_display_text(response)
            return extracted or fallback
        except Exception:
            return fallback

    def build_answer(self, question: str, hits: list[RetrievalHit], context: SessionContext) -> str:
        fallback = self.fallback.build_answer(question, hits, context)
        if not hits:
            return fallback
        system_prompt = (
            self.prompt_manager.load("answer_generation")
            or (
                "Answer using only the provided evidence. "
                "Prioritize troubleshooting steps, quick checks, and diagnostic signals over symptom descriptions. "
                "Do not introduce technologies, services, or root causes that do not explicitly appear in the evidence. "
                "Return conclusion, steps, risk, and citations."
            )
        )
        payload = {
            "question": question,
            "context": asdict(context),
            "evidence": [
                {
                    "source": self.fallback._source_label(hit),
                    "title": hit.title,
                    "section_path": hit.section_path,
                    "score": round(hit.score, 4),
                    "content": hit.content,
                }
                for hit in hits
            ],
            "required_sections": ["结论", "排查步骤", "风险提示", "引用来源"],
            "grounding_rules": [
                "Only use technologies, services, and causes that explicitly appear in the evidence.",
                "Prioritize troubleshooting steps, quick checks, and diagnostic signals over symptom descriptions.",
                "If the evidence says upstream service, keep it generic and do not guess a concrete dependency type.",
            ],
            "fallback_answer": fallback,
        }
        try:
            response = self.client.chat(system_prompt, json.dumps(payload, ensure_ascii=False))
            extracted = self._extract_display_text(response)
            if extracted and self._has_answer_shape(extracted) and self._is_grounded_answer(extracted, question, hits):
                return extracted
            return fallback
        except Exception:
            return fallback

    @staticmethod
    def _extract_json(raw: str) -> dict[str, Any]:
        try:
            parsed = json.loads(raw)
            return cast(dict[str, Any], parsed) if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, flags=re.S)
            if not match:
                return {}
            try:
                parsed = json.loads(match.group(0))
                return cast(dict[str, Any], parsed) if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}

    @classmethod
    def _extract_display_text(cls, raw: str) -> str:
        normalized = normalize_whitespace(raw)
        parsed = cls._extract_json(raw)
        if parsed:
            for key in ("missing_context", "clarification", "answer", "message", "text"):
                value = parsed.get(key)
                if isinstance(value, str):
                    cleaned = normalize_whitespace(value)
                    if cleaned:
                        return cleaned
        return normalized

    @staticmethod
    def _rewrite_is_usable(question: str, rewritten: str, fallback_query: str) -> bool:
        normalized = rewritten.strip().lower()
        if not normalized:
            return False
        if normalized in {"unknown query", "unknown", "n/a"}:
            return False
        rewritten_tokens = set(mixed_tokenize(normalized))
        fallback_tokens = set(mixed_tokenize(fallback_query.lower()))
        if rewritten_tokens and fallback_tokens and rewritten_tokens & fallback_tokens:
            if OpenAICompatibleReasoner._preserves_follow_up_focus(question, normalized, fallback_query.lower()):
                return True
        return len(normalized) >= max(8, len(fallback_query) // 3) and OpenAICompatibleReasoner._preserves_follow_up_focus(
            question,
            normalized,
            fallback_query.lower(),
        )

    @staticmethod
    def _preserves_follow_up_focus(question: str, rewritten: str, fallback_query: str) -> bool:
        focus_terms = LocalReasoner._follow_up_focus_terms(question)
        if not focus_terms:
            return True
        rewritten_lower = rewritten.lower()
        fallback_lower = fallback_query.lower()
        for term in focus_terms:
            term_lower = term.lower()
            if term_lower in fallback_lower and term_lower not in rewritten_lower:
                return False
        return True

    @staticmethod
    def _has_answer_shape(answer: str) -> bool:
        required = ("结论", "排查步骤", "风险提示", "引用来源")
        return all(marker in answer for marker in required)

    @classmethod
    def _is_grounded_answer(cls, answer: str, question: str, hits: list[RetrievalHit]) -> bool:
        evidence_text = " ".join(
            [
                question,
                *[hit.title for hit in hits],
                *[hit.content for hit in hits],
                *[" ".join(hit.section_path) for hit in hits],
            ]
        ).lower()
        answer_text = answer.lower()
        for keyword in cls.GROUNDING_KEYWORDS:
            lowered = keyword.lower()
            if lowered not in answer_text:
                continue
            if lowered in evidence_text:
                continue
            aliases = tuple(alias.lower() for alias in cls.GROUNDING_ALIASES.get(keyword, ()))
            if any(alias in evidence_text for alias in aliases):
                continue
            return False
        return True


def build_reasoner(
    *,
    llm_mode: str,
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    prompt_manager: PromptManager,
    answer_min_score: float,
) -> Reasoner:
    fallback = LocalReasoner(prompt_manager, answer_min_score)
    if llm_mode.lower() != "local" and llm_base_url and llm_api_key:
        client = OpenAICompatibleChatClient(
            base_url=llm_base_url,
            api_key=llm_api_key,
            model=llm_model,
        )
        return OpenAICompatibleReasoner(client=client, prompt_manager=prompt_manager, fallback=fallback)
    return fallback

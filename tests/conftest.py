from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture()
def temp_settings(tmp_path: Path) -> Settings:
    sample_docs = tmp_path / "sample_docs"
    sample_eval = tmp_path / "sample_eval"
    knowledge_docs = tmp_path / "docs"
    _write_text(
        sample_docs / "nginx-502-runbook.md",
        """# Nginx 502 Runbook

## Quick Checks
- Check upstream service health.
- Review timeout settings and gateway config.
- Compare application logs with the first 502 timestamp.
""",
    )
    _write_text(
        sample_docs / "mysql-connection-playbook.md",
        """# MySQL Connection Playbook

## Diagnostics
- Confirm port 3306 is reachable.
- Check max_connections and slow query logs.
- Validate username, password, and TLS settings.
""",
    )
    _write_text(
        sample_docs / "redis-auth-troubleshooting.md",
        """# Redis Auth Troubleshooting

## Steps
- Validate password and ACL user.
- Check TLS requirements and endpoint mapping.
""",
    )
    _write_text(
        sample_docs / "k8s-crashloop-guide.md",
        """# Kubernetes CrashLoopBackOff Guide

## Ordered Troubleshooting Steps
1. Inspect pod events, restart reason, and the previous container logs.
2. Compare environment variables, mounted configs, and image tag with the last healthy version.
3. Review probe thresholds and dependency reachability.
""",
    )
    _write_text(
        sample_docs / "docker-startup-checklist.md",
        """# Docker Service Startup Checklist

## Ordered Troubleshooting Steps
1. Inspect container logs and exit code.
2. Verify port usage on the host and compare with the compose mapping.
3. Check mounted files, environment variables, and secrets.
""",
    )
    _write_text(
        knowledge_docs / "ops-extra-guide.md",
        """# Ops Extra Guide

## Startup Recovery
- Review recent deployment changes.
- Check service logs and dependency health.
""",
    )
    _write_text(
        sample_eval / "cases.jsonl",
        "\n".join(
            [
                '{"question":"错误码 502 一般先查什么？","expected_answer_points":["upstream","timeout"],"expected_sources":["nginx-502-runbook"]}',
                '{"question":"数据库连不上应该先看哪些指标？","expected_answer_points":["3306","max_connections"],"expected_sources":["mysql-connection-playbook"]}',
                '{"question":"这个问题怎么继续查？","expected_answer_points":[],"expected_sources":[],"expect_clarify":true}',
            ]
        ),
    )
    settings = Settings(
        data_dir=tmp_path / "data",
        upload_dir=tmp_path / "data" / "uploads",
        db_path=tmp_path / "data" / "app.db",
        sample_docs_dir_override=sample_docs,
        sample_eval_dir_override=sample_eval,
        knowledge_docs_dir_override=knowledge_docs,
        llm_mode="local",
        llm_base_url="",
        llm_api_key="",
    )
    settings.ensure_dirs()
    return settings

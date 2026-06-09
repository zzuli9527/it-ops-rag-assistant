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
        """# Nginx 502 排障手册

## 快速检查
- 检查上游服务健康状态。
- 回看超时设置和网关配置。
- 将应用日志与首次出现 502 的时间点对齐。
""",
    )
    _write_text(
        sample_docs / "mysql-connection-playbook.md",
        """# MySQL 连接排障手册

## 诊断信号
- 确认 3306 端口可达。
- 查看 max_connections 和慢查询日志。
- 核对用户名、密码和 TLS 设置。
""",
    )
    _write_text(
        sample_docs / "redis-auth-troubleshooting.md",
        """# Redis 认证排障手册

## 排查步骤
- 核对密码和 ACL 用户。
- 检查 TLS 要求和端点映射。
""",
    )
    _write_text(
        sample_docs / "k8s-crashloop-guide.md",
        """# Kubernetes CrashLoopBackOff 排障指南

## 排查步骤
1. 查看 Pod events、重启原因和 previous container logs。
2. 对比环境变量、挂载配置和镜像 tag 与最近健康版本的差异。
3. 检查探针阈值和依赖可达性。
""",
    )
    _write_text(
        sample_docs / "docker-startup-checklist.md",
        """# Docker 服务启动检查清单

## 排查步骤
1. 查看容器日志和 exit code。
2. 检查宿主机端口占用并对照 compose 映射。
3. 核对挂载文件、环境变量和 secret。
""",
    )
    _write_text(
        knowledge_docs / "ops-extra-guide.md",
        """# 运维补充指南

## 启动恢复
- 回看最近的部署变更。
- 检查服务日志和依赖健康状态。
""",
    )
    _write_text(
        sample_eval / "cases.jsonl",
        "\n".join(
            [
                '{"question":"错误码 502 一般先查什么？","expected_answer_points":["上游服务","超时"],"expected_sources":["nginx-502-runbook"]}',
                '{"question":"数据库连不上应该先看哪些指标？","expected_answer_points":["3306","max_connections"],"expected_sources":["mysql-connection-playbook"]}',
                '{"question":"这个问题怎么继续查？","expected_answer_points":[],"expected_sources":[],"expect_clarify":true}',
            ]
        ),
    )
    settings = Settings.model_validate(
        {
            "data_dir": tmp_path / "data",
            "upload_dir": tmp_path / "data" / "uploads",
            "db_path": tmp_path / "data" / "app.db",
            "sample_docs_dir_override": sample_docs,
            "sample_eval_dir_override": sample_eval,
            "knowledge_docs_dir_override": knowledge_docs,
            "llm_mode": "local",
            "llm_base_url": "",
            "llm_api_key": "",
        }
    )
    settings.ensure_dirs()
    return settings

# IT Ops RAG Assistant

面向 IT 运维与 DevOps 文档场景的本地可部署问答项目，支持多格式文档入库、混合检索、多轮问答、引用溯源与离线评测。

## 项目定位

这个项目用于演示一个公开可复现的 RAG 工程化原型，重点展示：

- 文档解析与知识库构建
- 混合检索与问答链路
- 多轮追问与澄清分支
- 引用来源返回
- 离线评测与耗时分析

## 主要能力

- 支持 `PDF / DOCX / Markdown / HTML / TXT` 共 5 类文档解析
- 基于标题层级和段落结构进行切分，并保留章节元数据
- 使用 `BM25 + 向量式召回` 的混合检索策略
- 支持多轮问答、上下文补全和信息不足时的澄清追问
- 支持返回引用来源与检索调试信息
- 支持离线评测和请求级耗时拆解

## 项目边界

本仓库已按公开发布方式整理：

- 公开样例文档放在 `data/sample_docs/`
- 本地私有知识库放在 `local_docs/`
- `.env`、`local_docs/`、上传文件和本地数据库均已加入 `.gitignore`

请不要上传：

- 公司内部文档
- 私有 PDF / DOCX
- 真实工单、截图、配置文件
- API Key、账号密码等敏感信息

## 快速启动

```bash
pip install -e ".[dev]"
copy .env.example .env
python .\app\main.py
```

启动后访问：

```text
http://127.0.0.1:8011
```

## 离线评测

```bash
python .\scripts\run_eval.py
```

评测结果会输出：

- `retrieval_hit_rate_at_k`
- `source_precision`
- `answer_completeness`
- `clarification_trigger_rate`
- 各阶段耗时的 `avg / p50 / p95 / max`

## 目录说明

- `app/`：后端服务、检索、解析、Prompt、存储逻辑
- `data/sample_docs/`：公开样例文档
- `data/sample_eval/`：公开评测集
- `docs/`：项目说明文档
- `local_docs/`：本地私有知识库，不上传 GitHub
- `tests/`：单元测试与集成测试

## 当前公开演示状态

- 5 份公开样例故障文档
- 17 项自动化测试
- 支持问答、引用来源、检索调试与离线评测

更多项目说明见：

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md)

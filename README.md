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

## 技术路线

这个项目的实现不是简单把文档塞给模型，而是把整个问答链路拆成了可调试的几个阶段：

1. **文档解析与统一建模**  
   使用 `PyMuPDF / python-docx / BeautifulSoup` 等解析不同格式文档，统一转换为结构化文本块。  
   每个文本块都会保留：
   - 文档 ID
   - 标题
   - 页码
   - 章节路径
   - 原始元数据  
   这样后续回答时可以稳定返回引用来源，而不是只给一段不可追溯的文本。

2. **结构化切分与知识库构建**  
   文档不会整篇暴力切块，而是优先按标题、章节、自然段切分，再对过长文本做二次窗口拆分。  
   每个 chunk 会进入本地索引，并保存：
   - `document_id`
   - `chunk_id`
   - `section_path`
   - `token_count`
   - `checksum`  
   这一步的目标是兼顾两件事：检索命中率和引用可回溯性。

3. **会话上下文理解**  
   对当前问题和最近几轮消息做轻量上下文抽取，识别：
   - `topic`
   - `task`
   - `environment`
   - `version`
   - 必要时补充 `error_code / component / suspected_issue`  
   实现上采用“轻量模型抽取 + 本地规则兜底”的方式，既保留泛化能力，又避免完全依赖自由文本摘要。

4. **Query Rewrite**  
   在检索前先把原问题改写成更适合搜索的查询语句。  
   改写时会补充：
   - 当前主题
   - 追问焦点
   - 环境信息
   - 上一轮文档上下文  
   比如用户问“那密码要去哪里看”，系统不会直接拿这句话去检索，而是会补成带 `Redis / password / credential / rotation` 的查询。

5. **Hybrid Retrieval + Rerank**  
   检索阶段同时走两条路：
   - 关键词召回：`BM25`
   - 语义召回：本地向量化检索  
   两路结果合并后，再按问题特征和章节优先级做重排。  
   例如“排查步骤”“快速检查”类片段会比“现象描述”获得更高优先级。

6. **引用式回答生成**  
   最终回答不是让模型自由发挥，而是要求它基于候选证据输出固定结构：
   - 结论
   - 排查步骤
   - 风险提示
   - 引用来源  
   如果检索置信度不足，或者当前问题明显缺关键上下文，则进入澄清分支，而不是硬答。

7. **评测与回归验证**  
   项目内置离线评测脚本，对固定样例集统计：
   - 原始检索命中率
   - 引用精度
   - 回答完整度
   - 澄清分支准确性
   - 各阶段耗时分布  
   这样每次调整 prompt、检索策略或上下文逻辑后，都能快速回归验证。

一句话概括这条技术路线：

`文档解析 -> 结构化切分 -> 上下文抽取 -> 查询改写 -> 混合检索 -> 重排 -> 引用式回答 -> 离线评测`

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
python -m app.main
```

启动后访问：

```text
http://127.0.0.1:8011
```

## 离线评测

```bash
python .\scripts\run_eval.py
```

如需把本地 `local_docs/` 一并纳入评测：

```bash
python .\scripts\run_eval.py --include-local-docs
```

默认评测会使用隔离的临时数据库，只加载公开样例文档，避免被本地私有知识库污染。结果会输出：

- `retrieval_hit_rate_at_k`：原始检索命中率，按召回结果是否覆盖目标文档计算
- `source_precision`：最终回答里引用来源的精度
- `answer_completeness`：回答覆盖关键排查点的完整度
- `action_accuracy`：该问答是否正确进入回答或澄清分支
- `clarification_trigger_rate`：实际触发澄清分支的占比
- 各阶段耗时的 `avg / p50 / p95 / max`

## 目录说明

- `app/`：后端服务、检索、解析、Prompt、存储逻辑
- `data/sample_docs/`：公开样例文档
- `data/sample_eval/`：公开评测集
- `docs/`：项目说明文档
- `local_docs/`：本地私有知识库，不上传 GitHub
- `tests/`：单元测试与集成测试

## 自动化测试覆盖

当前项目共包含 `30` 个自动化测试用例，可通过 `pytest -q` 直接执行，主要覆盖 4 类场景：

- `tests/test_service.py`：`16` 个，覆盖问答主链路、多轮追问、澄清分支、文档范围检索、评测执行、上传安全与文档去重
- `tests/test_llm.py`：`12` 个，覆盖本地/远程 reasoner 切换、上下文字段抽取、结果归一化、答案 grounding 校验与上下文重置逻辑
- `tests/test_parsers.py`：`1` 个，覆盖 `PDF / DOCX / Markdown / HTML / TXT` 五类文档解析
- `tests/test_api.py`：`1` 个，覆盖 API 冒烟调用

执行方式：

```bash
pytest -q
```

预期结果：

```text
30 passed
```

## 当前公开演示状态

- 5 份公开样例故障文档
- 30 项自动化测试
- 支持问答、引用来源、检索调试与离线评测

基于当前公开样例集的一次离线评测结果：

- `retrieval_hit_rate_at_k`: `83.3%`
- `source_precision`: `83.3%`
- `answer_completeness`: `83.3%`
- `action_accuracy`: `100%`
- `clarification_trigger_rate`: `16.7%`
- `avg total latency`: `21.54s`
- `p95 total latency`: `29.68s`

更多项目说明见：

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md)

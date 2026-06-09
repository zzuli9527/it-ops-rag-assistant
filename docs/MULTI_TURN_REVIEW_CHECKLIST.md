# 多轮会话审查清单

这份清单用于回归验证多轮问答链路，重点检查：

- 会话上下文是否稳定
- 跳题时是否串题
- 文档限定场景是否误澄清
- `rewrite_query` 是否和真实问题一致
- 引用来源是否符合预期

## 审查方式

建议优先使用两个接口：

- `POST /api/chat/ask`
- `POST /api/retrieval/debug`

重点观察这 4 个输出字段：

- `context`
- `rewritten_query`
- `action`
- `sources`

---

## 场景 1：同主题连续追问

### 输入

1. `Redis 认证失败怎么排查？`
2. `那密码要去哪里看？`
3. `测试环境也是这样`

### 预期

- `topic` 保持为 `redis`
- 第二问、第三问的 `rewritten_query` 会补全 Redis 上下文
- 不应无意义重复澄清
- 回答来源应持续命中 `redis-auth-troubleshooting`

### 检查点

- 第二问 `context.topic == redis`
- 第二问 `rewritten_query` 包含 `redis` 或认证相关补充词
- 第三问 `context.environment == test`
- `action` 仍以 `answer` 为主

---

## 场景 2：限定文档内追问

### 输入

1. `document_scope=["nginx-502-runbook"]`
2. 问：`这个问题怎么继续查？`

### 预期

- 不应因为上下文不足直接走 `clarify`
- 应优先在 `nginx-502-runbook` 内回答
- `sources` 应全部来自该文档

### 检查点

- `action == answer`
- `sources[*].document_id` 全部等于 `nginx-502-runbook`
- `rewritten_query` 可简短，但不能完全丢失 scope 限定

---

## 场景 3：跨主题切换

### 输入

1. `Redis 认证失败怎么排查？`
2. `Jenkins 怎么新建流水线？`

### 预期

- 第二问不应继承上一轮的 `redis / authentication / database`
- 新上下文应切到 `jenkins`
- `task` 应识别为 `create_pipeline`

### 检查点

- 第二问 `context.topic == jenkins`
- 第二问 `context.component`、`context.suspected_issue` 不应残留 Redis 故障信息
- 第二问 `rewritten_query` 不应包含 `redis`

---

## 场景 4：无主题泛化问题

### 输入

1. `Redis 认证失败怎么排查？`
2. `怎么登录？`

### 预期

- 第二问应被视为新的泛化问题
- 不应继续继承 Redis 故障标签
- 如果知识不足，可以澄清，但不能被带偏到 Redis

### 检查点

- 第二问 `context.topic` 应为空或重新识别，而不是保留 `redis`
- 第二问 `rewritten_query` 不应出现 `redis / authentication / database`
- 若 `action == clarify`，澄清内容应围绕“登录对象/系统”，不是 Redis 故障

---

## 场景 5：混合意图问题

### 输入

1. `发布系统配置失败怎么排查？`
2. `Redis 使用报错怎么排查？`

### 预期

- `task` 应优先识别为 `troubleshoot`
- 不能被 `deploy / configure / usage` 抢走主意图

### 检查点

- `context.task == troubleshoot`
- `rewritten_query` 以排查语义为主，而不是单纯使用说明

---

## 场景 6：调试链路一致性

### 输入

同一个问题分别调用：

- `POST /api/chat/ask`
- `POST /api/retrieval/debug`

推荐问题：

- `Jenkins 怎么新建流水线并发布到测试环境？`

### 预期

- `debug_retrieval` 的 `rewritten_query` 应和真实问答一致
- `debug_retrieval.context` 应与真实问答中的 `context` 基本一致

### 检查点

- `debug.rewritten_query == ask.rewritten_query`
- `debug.context.topic == ask.context.topic`
- `debug.context.task == ask.context.task`

---

## 场景 7：澄清分支有效性

### 输入

1. `这个问题怎么继续查？`

### 预期

- 在没有会话前文、没有文档限定时，应走澄清
- 澄清内容应索要主题、服务、环境、错误码等关键上下文

### 检查点

- `action == clarify`
- 返回内容不是泛泛废话，而是明确要求补充信息

---

## 通过标准

满足以下条件可认为多轮会话链路基本合格：

- 同主题追问能稳定继承上下文
- 跨主题切换不会串题
- 限定文档场景不乱澄清
- `debug_retrieval` 和真实问答链路一致
- 混合意图问题不会误判主任务
- 泛化问题不会被旧故障标签污染

## 建议记录方式

每次回归建议记录：

- 问题原文
- `context`
- `rewritten_query`
- `action`
- `sources`
- 是否符合预期

可以直接整理成一个表格，便于后续版本对比。

# Agent 后端实现说明 v1

## 设计目标

复用既有 `database_gateway.Repository`、FastAPI、数字人前端和 `/api/tts`，增加可实际执行业务工具的服务入口。先做虚构预约闭环，不引入真实挂号、诊断、发消息、付款或外部写操作。

## 请求链路

```text
原数字人输入、语音识别
    → agent-client.js（仅 ?agent=1 时使用新入口）
    → 会话鉴权 / 请求去重 / 会话租约
    → 有界模型工具循环（native 或 LangGraph StateGraph）
    → Pydantic 校验 + 工具白名单
    → 只读数据库查询或生成待确认单
    → 用户独立确认
    → 审批门禁（LangGraph 模式使用 interrupt / checkpoint）
    → 原 Repository.book() 事务与幂等令牌
    → 基于实际结果的 JSON 回复
    → 原快捷按钮、数字人动作和逐句 /api/tts
```

## 模块

| 模块 | 责任 |
|---|---|
| `config.py` | 复用服务端环境变量，选择编排引擎，限制远程密钥使用 HTTPS |
| `schemas.py` | HTTP 与工具参数模型；严格类型校验，拒绝额外字段 |
| `llm.py` | Chat Completions 工具请求、工具 ID 校验、超时/响应大小限制 |
| `graph.py` | 共享工具执行节点；可选 StateGraph 路由和 SqliteSaver 审批图 |
| `store.py` | SQLite 会话、历史、请求缓存、不可变待确认单、会话租约 |
| `tools.py` | 包装原 Repository，不暴露 SQL 与直接预约写入工具 |
| `policy.py` | 明确标注的本地规则演示、日期转换和安全边界 |
| `knowledge.py` | 小规模本地服务 Markdown 检索；不是向量 RAG |
| `service.py` | 请求边界、确认授权、结果组织、错误与状态恢复 |
| `api.py` | 独立 Agent 路由；同源检查和无缓存响应 |

## API

所有 Session ID 和 Request ID 是随机生成的 32 位十六进制字符串。除创建会话、读取服务状态外，调用必须携带 `Authorization: Bearer <access_token>`。请求中不接受任意用户 ID、SQL、客户端 context 或客户端“已授权”标记。

| 路由 | 用途 |
|---|---|
| `GET /api/agent/status` | 编排引擎、模型配置情况、数据库功能开关 |
| `POST /api/agent/sessions` | 创建虚构演示会话并返回会话凭据 |
| `GET /api/agent/sessions/{session_id}` | 恢复会话历史、最后回复和有效待确认单 |
| `POST /api/agent/sessions/{session_id}/chat` | 查询、工具调用、生成待确认单 |
| `POST /api/agent/sessions/{session_id}/confirm` | 校验具体待确认单的批准或拒绝 |

聊天请求示例：

```json
{"request_id":"11111111111111111111111111111111","text":"查询内科明天下午号源","new_task":false,"voice_gender":"auto"}
```

确认请求的 `proposal_id` 和 `confirmation_token` 必须来自该会话的待确认响应，不应自行填写预约日期或号源：

```json
{"request_id":"22222222222222222222222222222222","proposal_id":"服务端返回的32位ID","confirmation_token":"服务端返回的令牌","decision":"approve"}
```

以上确认 JSON 是字段示意，非可直接运行的有效实例。`decision` 只接受 `approve` / `reject`。

响应保持 `reply`、`action`、`quick_replies`、`context`、`voice_gender` 和 `segments`，所以可以复用现有渲染与 TTS。额外返回 `request_id`、`mode`、`engine`、`trace`、`sources`、`pending` 和 `requires_confirmation`。`trace` 只含工具名、状态和耗时，不输出模型隐式推理或密钥。

## 工具边界

提供七个模型可用工具：`get_departments`、`query_available_slots`、`get_appointments`、`get_health_records`、`get_health_alerts`、`search_knowledge`、`prepare_appointment`。

`prepare_appointment` 只能引用本会话最近一次查询中实际返回的号源 ID，并会重新核实开放状态与余号。它不调用 `Repository.book()`。真正的 `commit()` 方法没有暴露给模型，仅在确认接口审批后调用。

工具返回值使用参数化数据库查询与服务端校验。模型只能调度，最终业务结果文案由后端按照工具事实生成，模型自称“成功挂号”不会被当作业务完成的证据。读到文档中的指令也不能扩展工具白名单或越过写入门禁。关键词安全拦截是附加边界，不代表医疗安全认证。

## 状态与一致性

默认会话有效期 24 小时，对话历史最多保留 24 条消息；发送给模型的历史取最后 12 条并截断长度。状态表与业务表分离，不向原业务库追加 Agent 表。

每个 HTTP 操作使用 `request_id` 与请求指纹去重。相同 ID 不能复用于不同消息、不同参数或不同操作。每个会话使用 SQLite 原子租约避免同时修改流程；忙碌时返回 409，不盲目交错执行。请求缓存保留每会话最近 200 项。

待确认单保存服务端选定的科室、时段和固定预约令牌，默认十分钟过期。提交时调用原有数据库事务和余号重查。相同待确认单即使换一个 HTTP request_id 重试，也复用同一个 `booking_token`。

若数据库已经提交、但响应丢失，待确认单保留 `committing` 状态。系统不会谎称失败或允许把这个未知结果当作未提交取消；重试原确认将用同一令牌核实数据库记录。LangGraph 模式中，提交节点异常后从该节点恢复，而不是重新生成令牌。

会话库和业务库不是同一事务。本实现通过不可变预约令牌和重试核实处理这个窗口，不声称提供跨系统分布式事务，也不声称对任意新会话/新任务全局去重。

## LangGraph 与 native 的区别

两种模式使用相同的工具、参数校验、会话存储和业务确认边界。native 自己运行有界工具循环；有模型配置时仍能进行真实 Function Calling，没有模型时才用规则演示。

LangGraph 模式新增真正的 StateGraph 条件路由，以及独立审批图的 `interrupt()` / `Command(resume=...)` / `SqliteSaver`。检查点在默认 `output/agent/state-checkpoints.sqlite3`，会话与待确认单在 `output/agent/state.sqlite3`。这些运行文件不得提交 Git。停止服务且确认不再需要恢复任务后才能清理。

当前环境不能安装 LangGraph，因此该路径的四项集成测试已提供但未运行；不要把缺少依赖时的 skip 当作通过。

## 限制和后续任务

本版没有多 Agent、Embedding、ChromaDB、跨用户健康数据隔离、真实医院接入、通知发送、预约改签/撤销已提交记录或真实模型效果评测。知识功能是服务文档的词项检索与摘录，不是医学知识库。

模型对接仅支持兼容 Chat Completions 的非流式 tool_calls。没有适配 Anthropic 原生工具协议、Responses、各厂商的私有“思考模式”字段。不会记录或回显上游原始错误、密钥或推理正文；厂商兼容性仍需实测。

候选下一阶段是：先补真实服务商和 LangGraph 联调证据，再为服务知识库实现 Embedding / 向量检索 / 召回评测，最后根据需求做真实身份认证和用户数据隔离。不要在这些模块完成前把它们写成既有能力。

## 参考的官方协议文档

- LangGraph interrupts：https://docs.langchain.com/oss/python/langgraph/interrupts
- LangGraph persistence：https://docs.langchain.com/oss/python/langgraph/persistence
- Chat Completions 工具调用示例：https://api-docs.deepseek.com/guides/tool_calls/

实现使用基础 invoke / StateGraph / interrupt / Command 接口，不依赖文档中的新实验性事件流 API。

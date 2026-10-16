# myDigital 对话分流升级 conversation-1.0.0

## 安装前提

适用于已安装 Agent v1、运行诊断 1.1.0、超时配置 `gateway-30-60-v1` 的项目。保留现有 LangGraph/native 引擎、HTTP 网关例外、Key 和数据库设置。安装器不发送网络请求、不读取或修改 .env、不改写数据库，不替换模型资源。它要求旧文件与交付版本匹配，拒绝覆盖未合并的本地源码改动。

这次不需要安装新依赖。LangGraph 与 SQLite Checkpointer 沿用当前环境；无法导入时不会伪造框架运行结果。

## 安装

把 `upgrade_agent_conversation.py` 放到 `D:\myDigital`。先停止服务，再执行：

```bat
cd /d D:\myDigital
D:\anaconda\python.exe upgrade_agent_conversation.py --project D:\myDigital
D:\anaconda\python.exe upgrade_agent_conversation.py --project D:\myDigital --apply
```

第一条仅预览，第二条备份后应用。修改两处现有文件：`vrm_demo/agent/service.py`、`vrm_demo/static/js/agent-client.js`；新增分流、文本调用、输出校验、说明和测试文件。不会回退之前的超时/HTTP配置，不修改旧 `/api/chat` 入口。

验证新路径及原业务回归：

```bat
D:\anaconda\python.exe -B -m unittest discover -s tests -p "test_agent_conversation.py" -v
D:\anaconda\python.exe -B -m unittest discover -s tests -p "test_agent_backend.py" -v
node --test tests/test_agent_frontend.mjs tests/test_agent_conversation_frontend.mjs
```

Node测试需要本机安装Node.js；不是运行Python后端的新增必需依赖。请确认 `LangGraphConversationTests` 和原 `LangGraphIntegrationTests` 实际执行并通过，而不是被 skipped。当当前电脑没有框架时，跳过项不能记为通过。

启动：

```bat
D:\anaconda\python.exe -m uvicorn vrm_demo.vrm_server:app --host 127.0.0.1 --port 8890
```

状态地址：`http://127.0.0.1:8890/api/agent/status`。应包含：

```json
{
  "engine": "langgraph",
  "llm_configured": true,
  "conversation_version": "conversation-1.0.0",
  "conversation_routes": ["chat", "knowledge", "business"],
  "routing_policy": "guarded_rules_v1",
  "timeout_profile": "gateway-30-60-v1"
}
```

上例只展示部分字段，engine取决于你已有设置，不会被补丁强制改变。

打开 `http://127.0.0.1:8890/?agent=1` 并按 Ctrl+F5。没有待确认或提交结果未知的任务时，可新建会话。不要点击旧请求的“重新尝试”来验证新代码，因为同一请求ID可能返回之前缓存的结果。不要删除业务库或检查点库。

## 三条路径实际做什么

### 普通聊天

例如“今天有点累，陪我聊聊天”“我明天有考试，有点紧张”“聊聊你的名字”。直接向已有网关发出不带工具的文本生成请求，一轮即可；读取 `message.content`，不读取或显示 `reasoning_content`。检查输出长度、危险标记、明显的伪造操作结果等，再返回原有reply/segments/TTS链路。

成功标签为 `llm_chat`。该模式没有tool_calls是正常现象。模型超时、缺配置或回复未通过校验时显示 `chat_fallback`，不会改称工具调用成功。

每条路径分别保留最多12条消息，模型请求只取其当前路径最近最多10条历史。普通聊天不自动携带业务查询得到的预约/健康记录或确认令牌；用户本轮主动输入的内容仍会发送给已配置服务商。不是无限或永久记忆。

### 服务咨询

例如“怎么预约，确认流程是什么”“确认之后会真的挂号吗”“取消已经提交的预约有什么规则”。通过现有本地中文二元词TF-IDF模块检索，再由模型根据检索片段组织回答。新增JSON结构和引用校验：来源ID必须属于本轮检索结果，摘录必须是原文中的连续子串，数字不能无依据生成。

成功标签为 `llm_knowledge`，网页可展开“查看本轮资料依据”。只有原文摘录为 `knowledge_extract`；模型超时、引用错误或模型表示依据不足时为 `knowledge_fallback`；未找到相关资料为 `knowledge_no_evidence`。引用检测证明可追溯性，不保证所有自然语言推论都正确，需人工核对内容。当前不是向量/Embedding RAG，没有添加ChromaDB，也不读取真实医院指南。

### 业务办理

例如“查询科室”“查询内科明天下午号源”“我的预约”。仍复用原 `run_model_turn()`、Toolbox、ApprovalFlow、SQL事务、幂等与确认接口；依然丢弃模型自由业务文案，科室、余号和提交结果由服务端组织，避免把自由聊天当成操作成功。

业务已有完整模型链成功时仍为 `llm_tools`。用户选择时段不等于提交。真正确认只能经过原 `/confirm` 接口；普通聊天与服务咨询没有这个权限。有待确认任务时优先显示原确认卡，即使用户突然说“聊聊天”；请先确认或取消再切换话题。提交结果未知时只能核实原请求，不能重建预约。此前已提交的预约仍不能通过“取消本次操作”撤销。

## LangGraph 中的新图

```
START -> route_input
          | chat       -> chat_reply -> END
          | knowledge  -> retrieve_service -> grounded_reply -> END
          | business   -> business_workflow (原模型/工具图) -> END
          | capability -> capability_reply -> END
```

分流是明确优先级的本地规则节点，避免每句话额外消耗一次模型请求；不是LLM意图分类器，不能保证所有复合、省略、否定表达的路由正确。混合请求优先实际业务办理，不自动并行完成多个意图。业务路径内部仍由模型理解参数和调度工具。

此图的单次输入状态不单独加检查点，聊天历史仍由应用层SQLite保存；审批图在最外层对话图返回后，由应用层单独启动，继续使用已有interrupt/SqliteSaver，避免把审批中断传播到临时分流图。聊天历史、单轮图状态和审批检查点不是同一种状态。

## 隔离与观察

状态接口返回新版本；每轮响应增加 `route`、`routing.policy`、`routing.nodes`。沿用 `[AgentRuntime]` 脱敏日志，普通聊天/服务咨询记录生成阶段，业务模式保留原模型/工具诊断。无模型调用的等待确认显示 `pending_confirmation`，不虚报 `llm_tools`。

不提供天气、新闻、航班、短信等未实现工具。诊断与用药等请求由项目边界响应处理。模型输出过滤和路由规则都不是完备安全保障；这是本机虚构数据演示，不能直接公开部署或上传真实个人健康数据。HTTP网关风险仍在，优先使用学校支持的可信HTTPS接口；本补丁不修改你显式选择的HTTP例外。

## 回滚

安装结束会显示备份目录。停止服务后执行：

```bat
D:\anaconda\python.exe upgrade_agent_conversation.py --project D:\myDigital --rollback D:\myDigital\.agent-conversation-backups\实际时间戳 --apply
```

源码有后续人工改动时拒绝覆盖。回滚恢复旧源码并删除未被改动的新增源码/说明/测试文件，不撤销已提交的模拟预约、不删除运行数据库；新增历史键保留但旧代码忽略它们。

## 参考

- LangGraph Graph API: https://docs.langchain.com/oss/python/langgraph/graph-api
- LangGraph workflows and routing: https://docs.langchain.com/oss/python/langgraph/workflows-agents
- Human-in-the-loop: https://docs.langchain.com/oss/python/langgraph/interrupts
- HTTPX phase timeouts: https://www.python-httpx.org/advanced/timeouts/

实现和测试范围详见随包验证报告；本机实际模型回复需在你的网关上验收。

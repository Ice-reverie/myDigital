# 可选大模型对话

默认无需配置：`/api/chat` 继续使用现有规则回复。前端请求和响应结构不变，模型回复同样经过语音合成、口型分析，`action` 交给现有场景动作播放器；连续动作去重和“减少动态”仍由前端处理。

## 后端配置

本版支持 OpenAI 兼容的 Chat Completions JSON 协议及 Anthropic Messages 协议。协议参考：[请求格式](https://api-docs.deepseek.com/api/create-chat-completion/)、[JSON 输出](https://api-docs.deepseek.com/guides/json_mode/)。不包括 Responses 或任意请求模板；API Key 设置页面暂未加入。

安装依赖：`python -m pip install "httpx>=0.27,<1" "python-dotenv>=1,<2"`（也已列入 requirements.txt）。

直接编辑项目根目录 `.env`。如果没有该文件，复制 `.env.example` 并重命名为 `.env`，填写：

```dotenv
DIGITALHELPER_LLM_PROTOCOL=openai-compatible
DIGITALHELPER_LLM_API_KEY=你的APIKey
DIGITALHELPER_LLM_BASE_URL=https://你的服务地址/v1
DIGITALHELPER_LLM_MODEL=你的模型名
```

保存后停止已有后端，再运行 `run.cmd`。后端启动时自动读取根目录 `.env`，不依赖启动时所在目录；修改配置需要重启。文件缺失或配置为空时，继续使用本地规则。`.env` 已加入 Git 忽略，`.env.example` 仅保存空模板；不要把真实 Key 填进模板。

仍支持通过进程环境变量配置，**环境变量优先于 `.env`，包括显式设置为空的值**。若之前在终端配置过模型，请新开终端或清除对应变量后再启动，避免覆盖 `.env`。例如临时配置：

```powershell
$env:DIGITALHELPER_LLM_PROTOCOL = 'openai-compatible'
$env:DIGITALHELPER_LLM_BASE_URL = 'https://你的服务地址/v1'
$env:DIGITALHELPER_LLM_MODEL = '你的模型名'
$secret = Read-Host 'API Key' -AsSecureString
$env:DIGITALHELPER_LLM_API_KEY = [System.Net.NetworkCredential]::new('', $secret).Password
.\run.cmd
```

Base URL 填服务商文档要求的前缀，系统追加 `/chat/completions`；不要填完整接口路径。远程服务要求 HTTPS，本机 localhost/127.0.0.1/::1 支持 HTTP。配置只由服务端进程读取，不返回前端。要恢复规则模式，清空 `.env` 中的 Key，并确保没有同名进程环境变量，再重启后端。Key 包含空格或 `#` 时可使用单引号包裹；`${...}` 不会被变量插值替换。

`GET /api/health` 新增 `llm_configured`，仅表示配置完整且客户端可用，不表示网络或 Key 已验证。没有配置、配置缺项、不支持的协议或缺少 httpx 都使用规则模式。请求超时（总计15秒）、401/429/5xx、格式错误、拒答、无依据服务介绍及非法动作也回退规则；不在日志中记录 Key、用户原文或上游错误内容。

## 规则与动作边界

- 正在进行的预约、预警流程优先；模型不能更改 context、quick_replies，也不能执行操作。流程对应 booking/alert/confirm。
- 问候、感谢、眨眼继续使用固定回复及 greet/thanks/wink。
- 普通聊天可使用模型回复；服务介绍只能依据代码内 services/limits/controls 三项项目说明生成，并返回资料 ID，使用 explain 动作。
- 尚未引入审核过的医疗知识库。已有健康规则及医疗关键词匹配的问题继续走规则；模型提示词要求对医疗问题和缺乏依据的问题拒答。资料 ID 校验和关键词过滤不等于事实证明，也不能保证覆盖所有医疗表达或消除幻觉；本版不适合用作医疗诊断系统。
- 模型只可建议 explain 或 null；业务动作不能由模型触发。过长、额外流程字段、明显伪造操作结果或不合法的回复会被丢弃。

目前模型调用为单轮，只向所配置的模型服务发送本轮普通聊天文本；浏览器内的对话记录不会随请求上传。医疗与业务流程继续由本地规则处理。请勿在普通聊天中输入不希望发送给模型服务的个人信息。

## 验证

`python -B -m unittest discover -s tests -p test_model_gateway.py -v`

测试通过模拟 HTTP 验证路径、鉴权、正常回复、失败回退、业务优先、动作与语音衔接，不消耗真实模型费用。真实模型仍需配置后检查服务商兼容性与回复质量。

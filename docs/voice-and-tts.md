# 人物声音、TTS 与聊天模型配置

## 演示人员操作

打开「帮助与设置 → 演示人员设置」。声音选择针对**当前已加载人物**，不是尚未点击「切换形象」的下拉候选人物。

- 「跟随人物」：Harumasa、doctorBoy、schoolBoy 默认男声；AnbyDemara、AstraYao、Eula、Yidhari、schoolGirl、studentGirl 默认女声。未知人物默认女声。配置由后端 `tts_gateway.py` 的人物映射维护。
- 「男声／女声」：覆盖当前人物的声音，按人物 ID 保存到当前浏览器，刷新后保留。选择「跟随人物」恢复预设。
- 「试听」：只生成固定的试听句子，不进入聊天业务流程。切换人物、声音或开始另一段语音会取消旧播放；过期回复仍显示文字，但不会在新人物上播放旧音频或动作。
- 浏览器本地声音缺少对应男女音色时，只能使用现有中文声音；不会通过改变音高伪造性别。

默认人物及其偏好设置继续独立工作，系统默认仍是 AstraYao。

## 管理员配置 `.env`

改完后重启 `run.cmd`。已有聊天配置不变，TTS 与聊天使用独立 Key、地址和模型。不要把真实 Key 写入 `.env.example`，也不要将 `.env` 提交到 Git。

默认不需要外部 Key：

```dotenv
DIGITALHELPER_TTS_PROTOCOL=edge
DIGITALHELPER_TTS_EDGE_VOICE_MALE=zh-CN-YunxiNeural
DIGITALHELPER_TTS_EDGE_VOICE_FEMALE=zh-CN-XiaoxiaoNeural
```

对接 OpenAI 兼容语音服务：

```dotenv
DIGITALHELPER_TTS_PROTOCOL=openai-compatible
DIGITALHELPER_TTS_API_KEY=填写语音服务Key
DIGITALHELPER_TTS_BASE_URL=https://你的服务地址/v1
DIGITALHELPER_TTS_MODEL=填写TTS模型名
DIGITALHELPER_TTS_VOICE_MALE=填写服务商提供的男声音色ID
DIGITALHELPER_TTS_VOICE_FEMALE=填写服务商提供的女声音色ID
```

Base URL 包含服务要求的版本前缀（如 `/v1`），不包含 `/audio/speech`。两个音色 ID 均需填写，具体名称取决于服务商。通过 Bearer Key 鉴权，请求 MP3 音频；收到的音频使用 PyAV 验证可解码性，限制 10 MiB。远端地址要求 HTTPS，本地服务可用 localhost/127.0.0.1/::1 的 HTTP。

未配置完整、外部超时或音频无效时回退 Edge TTS；Edge 也失败时返回文字交给浏览器播报。每次上游合成最多 15 秒，外部和 Edge 各有一次机会。分句音频继续进入现有 Rhubarb 口型分析；分析失败时保留音频并使用音量驱动嘴型。

## 聊天协议

```dotenv
DIGITALHELPER_LLM_PROTOCOL=openai-compatible
# 或 anthropic
DIGITALHELPER_LLM_API_KEY=填写聊天服务Key
DIGITALHELPER_LLM_BASE_URL=https://你的聊天服务地址/v1
DIGITALHELPER_LLM_MODEL=填写聊天模型名
```

OpenAI 兼容模式追加 `/chat/completions`；Anthropic 模式追加 `/messages`，使用 `x-api-key`、`anthropic-version: 2023-06-01` 与独立 system 提示。两者共用规则优先、JSON 校验、动作映射和失败回退；协议变化不解除医疗和预约流程约束。Anthropic 只用于聊天，不用作 TTS 协议。

## 后端接口

`GET /api/avatars` 的每个人物增加 `voice_gender: male | female`。

`POST /api/tts` 示例：

```json
{"text":"您好，我在这里陪您。","avatar_id":"Harumasa","voice_gender":"auto"}
```

文本长度 1–500 字。人物 ID 可省略；声音可为 `auto`、`male`、`female`，省略时默认 auto。返回：

```json
{
  "voice_gender":"male",
  "tts_available":true,
  "segments":[{"text":"您好，我在这里陪您。","audio":"Base64音频","visemes":[],"visemeTimeline":[]}]
}
```

`POST /api/chat` 同样接受可选 `avatar_id`、`voice_gender`，保留原 reply/action/context/quick_replies 等字段。旧客户端不传时使用系统默认人物声音。网页端还传入 `include_audio: false`，先取得文字、动作和分句文本，再逐句请求 `/api/tts`；省略该字段的旧客户端继续收到包含语音的完整响应。聊天历史仅保留在浏览器中，不会发送给模型服务。

`GET /api/health` 增加 `tts_protocol`、`tts_configured`、`tts_edge_available`；这些只表示配置与依赖状态，不保证上游当前可用。不返回 Key、Base URL 或用户输入。

官方协议参考：[OpenAI Audio](https://developers.openai.com/api/reference/resources/audio)、[Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create)。

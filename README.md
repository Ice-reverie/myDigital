# 数字人交互系统 / Digital Human Interaction System

[中文](#中文) · [English](#english)

## 中文

> 拟人化三维数字人 + 自然语音交互系统（课程作业项目）

### 项目简介

本项目是一个基于 Web 的数字人交互系统：用户可以通过语音或文字完成健康查询、健康预警确认和服务预约演示。浏览器可按需加载 VRM 格式的三维虚拟人模型；3D 资源加载失败时，业务对话、语音输入与语音播报仍可独立使用。业务步骤由本地规则驱动；普通聊天可选配外部大模型。系统不连接医院或消息服务。

本项目拥有"对话 + 语音合成"的服务能力，展示层采用「Three.js + three-vrm 三维渲染」的方案，使数字人具备可更换的 3D 形象、口型同步与肢体动作能力。

### 功能特性

- **VRM 模型加载**：通过网页文件选择器加载本地 `.vrm` 三维模型，支持随时更换，鼠标旋转缩放查看。
- **内置人物切换**：「帮助与设置 → 演示人员设置」可选择当前 9 个模型，切换时自动调整全身视角，并适配待机、口型和标准骨骼动作；原始模型文件保持不变。
- **医院场景切换**：同一设置区可选择蓝白「门诊大厅」、浅绿木色「温馨候诊区」和青白「智慧导诊」三个实时 3D 空间，并记住本浏览器的选择。每个场景都保留原图对照。
- **自然语音交互**：浏览器语音识别或文字输入 → 规则式问答 → 语音播报。
- **完整演示流程**：健康查询、预警确认、分步预约均可在未加载模型时体验。
- **适老化界面**：大字号、大点击区域、高对比度、明确状态反馈与快捷选项。
- **口型同步**：优先结合 Rhubarb 时间轴和音频能量驱动嘴型；时间轴缺失时使用音量驱动的元音轮换，浏览器播报时使用近似口型动画。
- **拟人化表情**：自动眨眼、静默时头部微动、说话时轻微点头。
- **肢体动作**：问候回复可触发挥手；支持加载 `.vrma` 动作文件手动播放。
- **关键词触发动作**：对话命中预设关键词时，自动加载并播放对应 `.vrma` 动作（greet / booking / alert / confirm / thanks / explain）。
- **业务问答**：内置健康查询、预警确认、预约挂号、服务咨询、问候、致谢等意图。
- **可选演示数据库**：开启后读取虚构科室、号源、演示健康记录和预警；模拟预约与预警选择写入本地运行副本。默认关闭，MySQL 可通过相同接口接入。

### 技术栈

| 层次 | 技术 |
|------|------|
| 前端 | HTML5 / CSS3 / JavaScript (ES6+) |
| 3D 渲染 | Three.js 0.180.0（WebGL） |
| 模型加载 | @pixiv/three-vrm 3.5.5 |
| 动作加载 | @pixiv/three-vrm-animation + AnimationMixer |
| 语音输入 | Web Speech API（不支持时保留文字输入） |
| 音频处理 | Web Audio API（AnalyserNode） |
| 后端框架 | FastAPI + Uvicorn |
| 语音合成 | edge-tts（微软 Azure 神经网络语音） |

### 系统架构

前后端分离的 B/S 架构。服务端负责对话与语音合成，前端负责三维渲染、口型驱动与交互。

    浏览器（Three.js + three-vrm 渲染 VRM / 口型动画 / 交互）
        │  HTTP (JSON) + 静态资源
    服务端（FastAPI）
        ├── /static/*   静态页面与脚本托管
        ├── /api/chat   对话、流程与动作匹配
        └── /api/tts    逐句语音合成

### 环境要求

- 操作系统：Windows 10/11
- Python 3.12（推荐 Anaconda）
- 现代浏览器（支持 ES Module、WebGL2）
- 网络：在线语音或外部大模型需要网络；3D 依赖已打包在项目内。在线语音不可用时尝试浏览器语音播报

### 安装与运行

Windows 下双击根目录的 `run.cmd` 即可启动，也可在终端执行。脚本依次查找项目的 `.venv`、`venv`、`env`、`virtualenv`，随后检查已激活的虚拟环境；没有时使用全局 `python` 或 `py -3`。缺少依赖时会提示安装命令，不会自动安装。`run.cmd --check` 仅检查并显示所选 Python，不启动服务。

```bash
# 1. 安装依赖
pip install -r requirements-vrm.txt

# 2. 在项目根目录启动服务
python vrm_demo/vrm_server.py

# 3. 浏览器打开
# http://localhost:8890/
```

> 提示：若系统存在多个 Python 解释器，请使用实际安装依赖的解释器（例如 `D:\anaconda\python.exe`）。

### 使用说明

1. 打开页面后，可直接点击「开始说话」（不用按住），或在输入框中输入需求；顶部「放大文字」可切换大字号。
   - 示例：「我最近头晕」「查看健康预警」「帮我预约门诊」。
2. 使用回复下方的大按钮完成预警确认、选择科室、选择时间和最终确认；预约任意步骤都可选择或输入「取消预约」。
3. 页面默认加载校服男生 `models/characters/schoolBoy.vrm`（跟随人物时使用男声），按人物尺寸适配正面全身；鼠标左键拖动可旋转，Shift + 左键拖动可平移，滚轮可缩放；点「恢复全身」回到默认视角。若需更换形象，在「演示人员设置」中选择其他 `.vrm` 文件。
4. 默认待机已替换为医生接待式 `Idle_Doctor`（8 秒），讲解使用 `Explain_Gentle`（10 秒），以 10 帧过渡回到腹前叠手。旧讲解版本归档在 `models/animations/legacy/`，不参与随机播放。可继续选择本地 `.vrma` 动作，七个场景动作统一放在 `models/animations/`，使用 `场景_序号.vrma` 命名。每次回复从同场景版本中随机选择；有多个版本时避免连续播放同一版本。添加版本后刷新页面即可使用。
5. 若当前浏览器不支持语音识别，页面会明确提示，文字输入仍可正常使用。
6. 「问问健康」「查看提醒」「预约服务」无需打字即可使用；点击另一项常用服务会切换到该服务的新流程。
7. 在「帮助与设置 → 演示人员设置 → 场景与氛围」点击缩略图更换医院场景；切换保留当前对话、预约步骤和人物。背景加载失败时保留原场景，可再次点击重试。

三个医院场景均用 Three.js 构建真实空间，人物和建筑共享相机、地面与深度；各自包含建筑反射、人物投影和鞋底接触阴影。人物面部使用独立柔和灯光。在「帮助与设置 → 演示人员设置」点击「查看原图场景 / 查看3D场景」可比较同一场景；切换后会关闭设置窗口，方便查看画面。3D 模式限制旋转和缩放范围、不支持平移，以保持主构图。

- **门诊大厅**：蓝白前台、玻璃走廊和缓慢开合的自动门。
- **温馨候诊区**：浅绿座椅、木色前台、暖白灯光、缓慢开合的诊室门与轻微植物摆动。
- **智慧导诊**：青色弧面玻璃、环形顶灯、落地窗和缓慢移动的服务屏指示。

场景按需加载并复用；快速切换不会被旧加载结果覆盖，加载失败时显示对应原图并可重试。「减少动态」可暂停环境动效，后台标签页暂停更新。原图模式保留 2.5D 视差效果。实时材质、光照和细节并非原图的逐像素复刻；场景均为虚构演示医院，不代表真实医院布局或导诊信息。

系统默认人物为校服男生；浏览器中明确设置过的个人默认人物仍优先。可在「演示人员设置」点击「恢复系统默认」，刷新后使用校服男生。模型使用对应名称的资源地址，避免旧默认人物的浏览器缓存影响显示。

> 说明：预警、联系家人和预约均为本地模拟流程，不会真实发送消息或向医院提交数据。

#### 可选数据库演示

项目根目录的 `digitalhelper_demo.sqlite3` 只含虚构数据，可以提交到 GitHub。默认不开启数据库；在根目录 `.env` 中设置 `DIGITALHELPER_DB_ENABLED=true`、`DIGITALHELPER_DB_BACKEND=sqlite` 并重启服务后，系统会将种子库复制到忽略 Git 的 `output/digitalhelper_demo.sqlite3`。确认模拟预约会占用该运行副本的名额，确认预警也会保存状态。号源按需补充未来 14 天；“前方人数”表示同一科室、日期和时段内先前确认的模拟预约人数，不是医院现场叫号。关闭开关后恢复原有规则流程。

MySQL 连接、建表和测试库重置说明见 [数据库接入说明](docs/database-integration.md)。MySQL 需要单独安装可选连接依赖，并手动准备数据；不会自动创建或改写外部数据库。

文字回复先显示，语音再按句请求和播放；某句在线合成或播放失败时，使用浏览器语音补播该句。后端顺序合成句子，口型分析最多并行处理 3 句；每种在线语音服务单次请求最多等待 15 秒。口型时间轴需要额外安装 `av` 并使用仓库内的 Rhubarb 工具；缺少这些组件不影响文字对话和备用口型。

在线语音使用 `edge-tts>=7.2.8,<8`。针对 2026 年 10 月旧合成地址返回 403 的问题，服务端按 [上游修复 #491](https://github.com/rany2/edge-tts/pull/491) 将已知旧地址适配到 `api.msedgeservices.com`，保持原有声音、语速及 TLS 校验。此兼容处理随项目代码生效，无需手动修改 Python 安装目录；将来依赖改用新地址时不会覆盖它。合成失败日志仅记录错误类型与 HTTP 状态，不输出令牌或朗读文本。排查时以 `/api/tts` 是否返回实际音频为准，`/api/health` 的语音依赖状态不代表上游实时连通性。

### 开发验证与旧素材工具

```bash
python -B -m unittest discover -s tests -v
node --test tests/test_vrm_frontend.cjs tests/test_hospital_scenes.cjs tests/test_avatar_surface.cjs tests/test_hospital_rooms.cjs
npm ci && npm run build:vrm && npm run test:browser
```

素材处理测试需要 `numpy` 和 `opencv-python`。前端单元测试使用 Node 内置测试运行器及浏览器 API 替身；浏览器冒烟测试需要安装 npm 开发依赖及本机 Edge 或指定 `BROWSER_EXECUTABLE`。修改 3D 依赖后运行 `npm run build:vrm` 更新项目内的浏览器包。真实麦克风、在线 TTS 和各模型外观仍需人工实测。

旧视频素材入口为 `app.py`（需要 Gradio），命令行入口为 `python data_preparation_mini.py 输入视频 输出目录`。脚本输出 `data/processed.mp4` 和逐帧对齐的 `data/processed.pkl`，供 `data_preparation_web.py` 继续生成 Web 素材。它使用 FFmpeg、OpenCV、NumPy、PyTorch，以及 `checkpoint/scrfd_2.5g_kps.onnx` 和 `checkpoint/face_landmarker_256x256.pt`；后续 Web 素材生成另需 DINet 模型权重。可选 `--matting` 沿用 RVM，额外需要 RobustVideoMatting、相关依赖、CUDA 和 `checkpoint/rvm_resnet50.pth`。这些权重和环境依赖不随修复补入仓库。

素材脚本仅清理本次创建的临时帧目录，异常退出也会清理，不删除用户已有的 `frames` 目录。

#### 动作文件命名约定

| 文件名 | 触发关键词 |
|--------|-----------|
| `greet_1.vrma` | 你好 / 您好 / 嗨 / 在吗 / hello |
| `booking_1.vrma` | 预约 / 挂号 / 门诊 |
| `thanks_1.vrma` | 谢谢 / 感谢 / 辛苦 |
| `explain_1.vrma`（Explain_Gentle） | 健康 / 不舒服 / 症状 / 头晕 / 头疼 / 血压 / 血糖 / 失眠 |
| `alert_1.vrma` | 预警 / 异常 / 提醒 |
| `confirm_1.vrma` | 确认 / 知道了 / 联系家人 |

动作文件缺失不影响对话功能，仅不播放动作。

### 项目结构

    vrm_demo/
    ├── vrm_server.py           # FastAPI 服务端（对话 + TTS + 动作匹配 + 静态托管）
    └── static/
        ├── VRMCharacter.html   # 主页面
        └── js/
            └── VRMCharacter.js # 渲染、口型、表情、动作、交互逻辑
    models/
    ├── characters/             # VRM 人物
    └── animations/             # 场景_序号.vrma、待机及配套摆动数据
    docs/
    ├── 需求定义书.md            # 需求定义书
    └── 技术设计文档.md          # 技术设计文档

（本系统核心为 `vrm_demo/` 目录。）

### 相关文档

- [可选大模型配置与规则回退](docs/model-integration.md)
- [SQLite 测试库与 MySQL 接口](docs/database-integration.md)
- [需求定义书](docs/需求定义书.md)
- [技术设计文档](docs/技术设计文档.md)

数字人资源分类与 Blender 待机工程说明见 [models/README.md](models/README.md)。页面自动读取 Blender 导出的 8 秒待机动作，支持头发/衣服摆动、自然站姿、自动眨眼及鼠标/触摸视线跟随。

---

## English

> A 3D digital human with natural voice interaction, built as a course project.

### Overview

This web-based digital human demonstrates health inquiries, health-alert acknowledgment, and service booking through voice or text. The browser loads VRM characters on demand. If 3D assets fail to load, chat, voice input, and speech output remain available. Local rules handle the guided workflows; an external language model is optional for general conversation. The demo does not connect to a hospital or messaging service.

The FastAPI backend provides conversation and text-to-speech services. The browser uses Three.js and three-vrm to display interchangeable characters with lip sync and body animation.

### Features

- **VRM characters:** Load a local `.vrm` file through the browser, switch characters, and rotate or zoom the view.
- **Built-in character selection:** Choose among nine included characters under **帮助与设置 → 演示人员设置** (Help & Settings → Demo Character Settings). Switching adjusts the full-body camera, idle motion, lip sync, and standard bone animations without changing the source models.
- **Hospital environments:** Choose among three code-built 3D rooms: the outpatient hall, warm waiting area, and turquoise guidance center. Moving doors, subtle plant or display motion, architectural reflections and avatar ground contact provide depth. Each room has an original-image comparison. Orbit and zoom are constrained; these are realtime interpretations, not pixel-identical recreations.
- **Voice and text interaction:** Browser speech recognition or typed input feeds the rule-based dialogue; replies can be spoken aloud.
- **Guided demo workflows:** Health inquiries, alert acknowledgment, and step-by-step booking work even without a loaded model.
- **Accessible controls:** Large text and click targets, high contrast, clear status feedback, and quick replies.
- **Lip sync and expressions:** Rhubarb timelines and audio levels drive mouth shapes, with fallbacks when timeline data is unavailable. Characters also blink, move subtly while idle, and nod while speaking.
- **Actions:** Greetings can trigger a wave. Local `.vrma` animations can be played manually or selected automatically from dialogue keywords (`greet`, `booking`, `alert`, `confirm`, `thanks`, and `explain`).
- **Built-in intents:** Health inquiries, alerts, appointments, service questions, greetings, and thanks.
- **Optional demo database:** When enabled, answers use fictional department, appointment-slot, health-record, and alert data. Demo appointments and alert choices persist in a local runtime copy. SQLite and MySQL share one data-access interface.

### Technology

| Layer | Technology |
|-------|------------|
| Frontend | HTML5, CSS3, JavaScript (ES6+) |
| 3D rendering | Three.js 0.180.0 with WebGL |
| VRM loading | @pixiv/three-vrm 3.5.5 |
| Animation | @pixiv/three-vrm-animation and AnimationMixer |
| Speech input | Web Speech API; text input remains available when unsupported |
| Audio analysis | Web Audio API (AnalyserNode) |
| Backend | FastAPI and Uvicorn |
| Speech synthesis | edge-tts (Microsoft Azure neural voices) |

### Architecture

The backend handles dialogue and speech synthesis. The frontend handles rendering, lip sync, animations, and interaction.

```text
Browser (VRM rendering, lip sync, interaction)
    │  HTTP (JSON) and static assets
FastAPI server
    ├── /static/*   Page and scripts
    ├── /api/chat   Dialogue, guided workflows, and action matching
    └── /api/tts    Sentence-by-sentence speech synthesis
```

### Requirements

- Windows 10 or 11
- Python 3.12 (Anaconda is recommended)
- A modern browser with ES modules and WebGL2
- Network access for online speech or an optional external language model. The 3D dependencies are bundled locally; browser speech synthesis is used when online speech is unavailable.

### Installation and startup

On Windows, double-click `run.cmd` in the project root or run it in a terminal. It searches `.venv`, `venv`, `env`, and `virtualenv` in the project, then an active virtual environment, then global `python` or `py -3`. It prints an installation command if dependencies are missing; it does not install them automatically. `run.cmd --check` reports the selected Python without starting the server.

```powershell
# Install the web application dependencies.
python -m pip install -r requirements-vrm.txt

# Start the server from the project root.
python vrm_demo/vrm_server.py

# Open http://localhost:8890/ in a browser.
```

If you have multiple Python installations, use the interpreter where you installed the dependencies (for example, `D:\anaconda\python.exe`).

### Using the demo

The interface currently uses Chinese labels; English translations below identify the matching controls.

1. Select **开始说话** (Start Speaking; no need to hold the button), or type a request. Use **放大文字** (Enlarge Text) to increase the font size. Example requests in Chinese: “我最近头晕”, “查看健康预警”, or “帮我预约门诊”.
2. Use the large buttons below the reply to acknowledge an alert, choose a department and time, and confirm a booking. At any booking step, choose or type “取消预约” to cancel.
3. The default character is the school boy, `models/characters/schoolBoy.vrm`, with a male voice preset, shown from the front in a full-body view. Drag with the left mouse button to rotate, Shift-drag to pan, and use the wheel to zoom. **恢复全身** (Restore Full Body) resets the view. Select another character in **演示人员设置** (Demo Character Settings), or load a local `.vrm` file.
4. The default idle is now `Idle_Doctor` (8 seconds), and explanations use `Explain_Gentle` (10 seconds), with a 10-frame transition back to folded hands. Previous explanation clips are archived in `models/animations/legacy/` and excluded from selection. You can load and play a local `.vrma` animation. Put scene actions in `models/animations/` and name versions `scene_number.vrma`. The app randomly picks among versions for the same scene and avoids repeating the previous version when alternatives exist. Refresh the page after adding an action.
5. If speech recognition is unsupported, the page shows a message and typed input remains available. The quick actions **问问健康** (Ask About Health), **查看提醒** (View Alerts), and **预约服务** (Book a Service) work without typing; choosing another service starts its workflow.

Alerts, family contact, and appointments are local simulations: they do not send messages or submit data to a hospital. Health information in the demo is not a medical diagnosis.

#### Optional database demo

The checked-in `digitalhelper_demo.sqlite3` contains fictional data only. Database use is off by default. Set `DIGITALHELPER_DB_ENABLED=true` and `DIGITALHELPER_DB_BACKEND=sqlite` in the root `.env`, then restart the server. The application copies the seed to the Git-ignored `output/digitalhelper_demo.sqlite3`, where demo bookings and alert choices are saved. It adds fictional slots for the next 14 days as needed. “People ahead” counts earlier confirmed demo bookings in the same department, date, and time slot; it is not a live hospital queue. Switching the feature off restores the original rule-based flow. See [database integration](docs/database-integration.md) for MySQL setup and data details.

Text replies appear before speech. Audio is requested and played sentence by sentence; if online synthesis or playback fails for a sentence, the browser attempts to speak that sentence. The backend synthesizes sentences in sequence and analyzes up to three lip-sync segments concurrently. Each online speech service has a 15-second limit per request. Rhubarb timelines require the included Rhubarb tool and the optional `av` package; missing components do not prevent text chat or fallback lip sync.

Online speech requires `edge-tts>=7.2.8,<8`. Following [upstream fix #491](https://github.com/rany2/edge-tts/pull/491), the gateway adapts the known legacy synthesis URL to `api.msedgeservices.com` after the October 2026 HTTP 403 failures. Voice settings and TLS verification are preserved. This project-local compatibility fix does not edit installed packages or overwrite future upstream endpoints. Failure logs contain only the error type and HTTP status, never tokens or spoken text. Verify connectivity using actual audio from `/api/tts`; dependency status in `/api/health` is not a live upstream check.

### Development checks and legacy media tools

```powershell
python -B -m unittest discover -s tests -v
node --test tests/test_vrm_frontend.cjs tests/test_hospital_scenes.cjs tests/test_avatar_surface.cjs tests/test_hospital_rooms.cjs
npm ci
npm run build:vrm
npm run test:browser
```

Media-processing tests require `numpy` and `opencv-python`. The frontend unit tests use Node's built-in test runner with browser API stubs. The browser smoke test requires the npm development dependencies and a local Edge installation, or a browser specified by `BROWSER_EXECUTABLE`. After changing 3D dependencies, run `npm run build:vrm` to update the browser bundle committed in the repository. Check the actual microphone, online TTS, and visual appearance of each model manually.

The legacy video tool starts from `app.py` (requires Gradio). Its command-line entry point is `python data_preparation_mini.py input_video output_directory`. It creates `data/processed.mp4` and frame-aligned `data/processed.pkl` for `data_preparation_web.py`. It uses FFmpeg, OpenCV, NumPy, PyTorch, `checkpoint/scrfd_2.5g_kps.onnx`, and `checkpoint/face_landmarker_256x256.pt`; later web-media generation also needs DINet model weights. Optional `--matting` uses RVM and additionally needs RobustVideoMatting, its dependencies, CUDA, and `checkpoint/rvm_resnet50.pth`. These weights and environments are not bundled with this project. The media script removes only temporary frame directories it created, including after errors, and preserves any existing user `frames` directory.

#### Action file naming

| Filename | Trigger keywords |
|----------|------------------|
| `greet_1.vrma` | 你好 / 您好 / 嗨 / 在吗 / hello |
| `booking_1.vrma` | 预约 / 挂号 / 门诊 |
| `thanks_1.vrma` | 谢谢 / 感谢 / 辛苦 |
| `explain_1.vrma` (Explain_Gentle) | 健康 / 不舒服 / 症状 / 头晕 / 头疼 / 血压 / 血糖 / 失眠 |
| `alert_1.vrma` | 预警 / 异常 / 提醒 |
| `confirm_1.vrma` | 确认 / 知道了 / 联系家人 |

Missing action files do not affect dialogue; the corresponding animations simply do not play.

### Project layout

```text
vrm_demo/
├── vrm_server.py           # FastAPI: dialogue, TTS, actions, static files
└── static/
    ├── VRMCharacter.html   # Main page
    └── js/
        └── VRMCharacter.js # Rendering, lip sync, expressions, actions, UI
models/
├── characters/             # VRM characters
└── animations/             # Scene actions, idle motion, supporting motion data
docs/
├── 需求定义书.md            # Requirements document (Chinese)
└── 技术设计文档.md          # Technical design document (Chinese)
```

The main application lives in `vrm_demo/`.

### Further documentation

- [Optional language-model configuration and rule fallback](docs/model-integration.md) (Chinese)
- [SQLite demo database and MySQL adapter](docs/database-integration.md) (Chinese)
- [Character voices, TTS, and chat configuration](docs/voice-and-tts.md) (Chinese)
- [Requirements document](docs/需求定义书.md) (Chinese)
- [Technical design document](docs/技术设计文档.md) (Chinese)

See [models/README.md](models/README.md) for character assets and the Blender idle-animation project. The page loads the reviewed eight-second doctor idle with folded hands, breathing, blinking, and a gentle smile. VRM humanoid retargeting handles each character; live speech retains mouth control. Hair and clothing use the character’s own physics. The legacy JSON idle remains available as a loading fallback.

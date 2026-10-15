# 人物与动作资源

## 当前运行时动作

经用户确认，网页默认启用关节修正版 V2：

| 用途 | 文件 / 接口 | Action | 时长 |
|---|---|---|---|
| 待机 | `animations/Idle_Doctor.vrma` · `/api/animations/idle` | `Idle_Doctor` | 8 秒，30 fps |
| 健康讲解 | `animations/explain_1.vrma` · `/api/animations/explain/explain_1` | `Explain_Gentle` | 10 秒，30 fps |

两个运行文件与 `animations/review_health/` 中经过审核的 V2 导出完全一致。Blender 工程为 `animations/review_health/Anxin_Health_Actions.blend`。实际播放 F1–240 / F1–300，导出保留 F241 / F301 的闭合时间戳，首尾及两个动作的基础姿态一致。

待机采用腹前叠手、轻微呼吸、眨眼和微笑。讲解用右手缓缓展开并回收。运行时通过 VRM 标准骨骼映射和身高换算适配人物；VRM0 的旋转坐标转换交由 three-vrm-animation 处理。新待机完整控制手腕和手指，不再叠加旧的手指与手腕摆动；自带的眨眼及眼骨轨道播放时暂停自动眨眼和鼠标视线跟随，避免同时控制同一部位。

每次讲解播放一次，以 10 帧（约 0.33 秒）的平滑过渡进入和返回叠手待机。开始场景动作时将新待机重置至共同基础姿态，动作期间暂停待机时钟；过渡结束后继续呼吸。其他场景动作与手动导入动作也沿用这一过渡。低帧率下骨骼片段按实际经过时间播放，物理模拟使用受限步长；返回后台标签页时重置时钟，避免跳过整个动作。

口型始终由语音驱动：动作过滤五种元音及下颌轨道，保留微笑与眨眼。语音期间临时解除表情对嘴部的覆盖，更新后恢复原配置。减少动态时显示共同基础姿态，停止场景动作，保留自动眨眼和语音口型。

## 人物选择与适配

在「帮助与设置 → 演示人员设置」选择形象，再点击「切换形象」。当前提供 `doctorBoy`、`schoolBoy`、`schoolGirl`、`studentGirl` 四个模型，系统默认校服男生 `schoolBoy`。人物文件不会被动作接入过程改写。

`/api/avatars` 自动发现 `characters/` 直属目录中的 VRM 文件；支持中文、空格及大小写扩展名，不开放子目录或符号链接。新增或移除人物后重新打开设置即可刷新列表。标准骨骼和表达能力缺失时按模型已有能力适配。新人物下载失败保留原形象，过期下载释放，切换不清空对话。

人物按真实包围盒进行全身取景；3D 医院场景使用脚底采样与接触阴影辅助落地。保留各人物的材质、口型、表情和物理配置。已测试四个现有人物的资源加载与动作流程；跨人物重定向不等同于所有服装、比例在每一帧都绝无穿插。

「设为默认」只保存本浏览器偏好；「恢复系统默认」清除偏好并恢复 `schoolBoy`。人物移除或目录不可用时回退到系统默认。人物声音按人物保存，可选择自动、男声或女声。

## 场景动作与归档

| 场景 | 当前资源 | 自动触发 |
|---|---|---|
| greet | `greet_1.vrma` | 问候 |
| explain | `explain_1.vrma`（新版温和讲解） | 健康咨询与服务讲解 |
| alert | `alert_1.vrma` | 健康预警 |
| booking | `booking_1.vrma` | 预约引导 |
| confirm | `confirm_1.vrma` | 完成、取消、确认 |
| thanks | `thanks_1.vrma` | 致谢 |
| wink | `wink_1.vrma` | 轻松互动 |

旧 `explain_1`、`explain_2` 及第二版的配套摆动、预览已移入 `animations/legacy/`，不参与目录扫描或随机选择。旧 Blender 工程保留。旧 `Lumine_idle.json` 通过 `/api/animations/idle/legacy` 保留，只有新待机加载失败时才回退；回退时旧的人形待机、手型、眨眼和视线逻辑仍可用。

`GET /api/animations` 提供七个白名单场景的版本目录。目录只扫描 `animations/` 直属文件，编号格式为 `场景_正整数.vrma`。某场景以后增加多个有效版本时继续随机选择并避免连续重复。编号接口 `/api/animations/{name}/{variant}` 按版本缓存；旧 `/api/animations/{name}` 返回编号最小的版本。缺失动作不影响对话，恢复待机；失败缓存可以重试。

可选 `.secondary.json` 配套摆动只用于匹配的旧 Lumine 人物。当前四个人物使用自身物理配置。`animations/review_health/previous_v1/` 是修改前审核版本，`joint_audit/` 是历史问题证据，`joint_audit_v2/` 是已修正检查证据。

## 验证与制作

- `tests/test_health_motion_assets.py`：运行资源与审核导出一致、时长、循环、共同姿态、固定脚部、无发音轨道。
- `tests/test_vrm_frontend.cjs`：手型与表情控制、口型、10 帧过渡、减少动态、计时、缓存、过期加载和故障回退。
- `tests/test_browser_smoke.cjs`：真实浏览器切换四个现有人物、讲解返回待机、问候及无 3D 时对话降级。
- `animations/review_health/runtime-integration.json`：本次接入验证记录。
- `tools/animation_authoring/`：可重建的 Blender 制作、检查、导出和视频脚本。复现命令见审核目录 README。

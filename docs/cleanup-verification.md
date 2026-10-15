# 冗余文件清理与验证

本次仅清理当前运行不使用的文件，保留旧视频数字人、素材处理、抠像代码及其测试，避免移除项目独立功能。

删除清单：

- `vrm_demo/tools/tools_backup/`：多层工具备份；清理前第一层 49 个文件与正式目录逐个哈希一致，四份 rhubarb.exe 哈希相同。
- `vrm_demo/tools/extras/`、`vrm_demo/tools/tests/`：Rhubarb 第三方编辑器插件、示例与测试素材。
- `vrm_demo/_check2.py`：硬编码旧路径和旧动作实现的检查脚本。
- `vrm_demo/static/animations/`：仅包含过时的动作目录说明。
- `vrm_demo/static/assets/companion-stage.png`：当前页面未引用的旧背景。
- `vrm_demo/static/js/lib/`：未使用的两个口型库；同步删除 HTML import map 中的映射。
- `.pytest_cache/`：生成缓存，并加入 Git 忽略。

清理约 385.36 MiB 的工作区内容，不改写 Git 历史。保留正式 Rhubarb 可执行程序、res、许可证、说明文件，以及全部人物、场景动作和制作工程。

## 自动化验证

删除前后分别运行：

```text
python -B -m unittest discover -s tests -q
node --test tests/test_vrm_frontend.cjs
```

两次均为 Python 41/41、前端 30/30 通过。覆盖业务流程、模型配置和失败回退、语音降级、七种场景及动作资源、随机选择和异步竞争、动作/待机恢复、旧视频素材处理等现有测试。`run.cmd --check` 成功。

## 运行验证与限制

- 启动实际后端，页面、JS、CSS、人物、待机、动作目录、健康接口均返回 200。
- 浏览器实测数字人正常显示；点击预约服务后返回科室选择和取消按钮，无浏览器错误。验证后关闭临时浏览器页及测试后端，恢复检查前的停止状态。
- 实际问候回复返回 greet 和两段在线语音。
- 单独使用生成的测试 WAV 调用正式 Rhubarb：退出码 0，返回有效 mouthCues；临时 WAV 已自动清理。
- 当前全局 Python 环境缺少 `av`（PyAV），因此真实聊天没有精确口型时间轴，使用已有备用口型。清理未操作 Python 安装目录；这是本次发现的环境缺项，不能把精确口型整条链路记为通过。现有 requirements.txt 已包含 av。
- 旧视频生成/训练的真实模型推理、真实麦克风输入未实测；现有自动化测试通过不等同于这些外部环境和权重也已验证。

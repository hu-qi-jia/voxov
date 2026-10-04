# 面试助手（voxov）

本地优先的面试实时辅助 Windows 客户端：上传你的面试八股 md → 本地向量知识库；监听**系统音频**（面试官声音）实时出字幕；按热键即时生成口语化参考回答。

- **本地**：语音识别（FunASR SenseVoice-Small）与向量模型（bge-small-zh-v1.5）全部本地运行，不上传音频。
- **低延迟**：热键触发 → 首字目标 ≤2s（检索本地 SQLite，生成走 SSE 流式）。
- **仅系统音频**：只采集系统输出（WASAPI loopback），**不采集、不记录麦克风**——你自己的声音不会进入任何数据。
- **可彩排**：用一段 wav 录音按真实时长回放全链路，首次真实使用前先验证。

> 截图占位（主窗口 / 悬浮窗 / 彩排）

## 安装与运行（源码）

需要 Python 3.11+（开发环境为 3.13）：

```bash
git clone https://github.com/hu-qi-jia/voxov.git
cd voxov
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -e ".[ml]"        # ml 组含 funasr/torch/sentence-transformers 等大件
python main.py
```

### 首次运行：下载模型（约 0.5 GB）

主窗口或托盘菜单点 **下载模型**，自动从 ModelScope（语音模型）与 hf-mirror.com（向量模型）下载到 `models/`，支持断点续传。HuggingFace 直连不畅时已默认走 `HF_ENDPOINT=https://hf-mirror.com` 镜像。

### 配置 LLM（设置页）

主窗口 **设置** 集中了全部配置。LLM 为任意 OpenAI 兼容接口，例如 DeepSeek：

| 配置项 | 示例值 |
|---|---|
| Base URL | `https://api.deepseek.com/v1` |
| API Key | `sk-...` |
| 模型 | `deepseek-chat` |

> **注意：API Key 以明文存储在 `data/config.json`**。该目录在本仓库中被 gitignore；请自行确保本机与该文件的安全。

## 使用

1. **上传**：把面试八股 md 拖进来（结构感知切分，代码块/表格不拆散）。
2. **监听**：开始后悬浮窗实时滚动字幕（面试官的声音）。
3. **触发生成**：`Ctrl+Alt+Space` —— 悬浮窗流式输出参考回答（口语化分点，附知识库来源）。
4. **急隐藏**：`Ctrl+Alt+H` —— 悬浮窗+托盘即刻隐藏，再按一次恢复。
5. **导出**：把本次问答导出为 md 复盘。

热键均可在设置页修改。

## 彩排模式（首次真实使用前必读）

点 **彩排** 选一段 wav 录音：应用按真实时长回放该录音走完整链路（字幕→检索→生成→导出），不接音频设备。第一次真实面试前，请务必用彩排验证：模型已就绪、LLM key 有效、字幕跟手、热键出答案。

## 路径配置

`models/`（模型）与 `data/`（知识库、配置、会话记录）默认在应用根目录，均可在设置页改为其他位置。两者都不入库。

## 打包版

```bash
pip install pyinstaller
pyinstaller interview-assistant.spec
```

产物在 `dist/notes-viewer/`，整目录拷走即用；`models/`、`data/` 放在同目录。对外进程名与窗口标题均为中性的 `notes-viewer` / `Notes`。

## 开发

```bash
pip install -e ".[dev]"
pytest              # 单元与集成（不依赖模型/网络）
pytest -m model     # 需本地已下载模型
```

## 协议与免责声明

MIT License（见 [LICENSE](LICENSE)）。

本项目仅供个人学习、练习与技术演示。使用者应自行遵守所在场景的规则与法律法规，并对使用方式及其后果自负其责；本项目作者不对任何滥用承担责任。

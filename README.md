# 面试助手（voxov）

本地优先的面试实时辅助 Windows 客户端：上传你的面试八股 md → 本地向量知识库；监听**系统音频**（面试官声音）实时出字幕；按热键即时生成口语化参考回答。

- **本地**：语音识别（sherpa-onnx SenseVoice）与向量模型（bge-small-zh-v1.5）全部本地运行，不上传音频。
- **低延迟**：热键触发 → 首字目标 ≤2s（检索本地 SQLite，生成走 SSE 流式）。
- **仅系统音频**：只采集系统输出（WASAPI loopback），**不采集、不记录麦克风**——你自己的声音不会进入任何数据。

> 截图占位（主窗口）

## 安装与运行（源码）

需要 Python 3.11+（开发环境为 3.13）：

```bash
git clone https://github.com/hu-qi-jia/voxov.git
cd voxov
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -e ".[ml]"        # ml 组含 sherpa-onnx / onnxruntime / tokenizers（无 torch）
python main.py
```

### 首次运行：模型自动下载（开箱即用）

首次启动检测到模型缺失时**自动在后台下载**（共约 250MB：sherpa-onnx SenseVoice int8 语音模型 + bge-small-zh 向量模型，GitHub Releases / hf-mirror，支持断点重试），无需任何点击——设置页实时显示「下载中… N%/模型就绪/下载失败」。下载失败时在设置页点 **重新下载** 重试。

### 配置 LLM（设置页）

主窗口 **设置** 集中了全部配置。LLM 为任意 OpenAI 兼容接口，例如 DeepSeek：

| 配置项 | 示例值 |
|---|---|
| Base URL | `https://api.deepseek.com/v1` |
| API Key | `sk-...` |
| 模型 | `deepseek-chat` |

> **注意：API Key 以明文存储在 `data/config.json`**。该目录在本仓库中被 gitignore；请自行确保本机与该文件的安全。

## 使用

主窗口顶栏导航：**监听 / 知识库 / 设置**；模型状态灯与下载在设置页。

1. **上传**（知识库页）：把面试八股 md 拖进来（结构感知切分，代码块/表格不拆散）。
2. **监听**（监听页）：开始后系统音频（面试官的声音）转成字幕，转写流逐条留档；「自动作答」开启时实质话轮自动触发回答。
3. **触发生成**：`Ctrl+Alt+Space` —— 主窗口转写流内流式输出参考回答（口语化分点，附知识库来源）。
4. **急隐藏**：`Ctrl+Alt+H` —— 主窗口+托盘即刻隐藏，再按一次恢复。
5. **导出**（知识库页）：把本次问答导出为 md 复盘。

热键均可在设置页修改。

## 路径配置

`models/`（模型）与 `data/`（知识库、配置、会话记录）默认在应用根目录，均可在设置页改为其他位置。两者都不入库。

## 打包版

```bash
pip install pyinstaller
pyinstaller interview-assistant.spec
```

产物在 `dist/notes-viewer/`，整目录拷走即用；`models/`、`data/` 放在同目录。对外进程名为中性的 `notes-viewer`，窗口标题为 `voxov`。

## 开发

```bash
pip install -e ".[dev]"
pytest              # 单元与集成（不依赖模型/网络）
pytest -m model     # 需本地已下载模型
```

## 协议与免责声明

MIT License（见 [LICENSE](LICENSE)）。

本项目仅供个人学习、练习与技术演示。使用者应自行遵守所在场景的规则与法律法规，并对使用方式及其后果自负其责；本项目作者不对任何滥用承担责任。

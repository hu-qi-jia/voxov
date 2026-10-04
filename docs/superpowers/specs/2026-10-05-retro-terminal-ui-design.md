# 设计：retro terminal UI 重构

日期：2026-10-05
状态：待评审
视觉基准（唯一）：`docs/design/2026-10-04-retro-terminal-preview.html`（交互式，tab 可切，#kb/#set 直达）
决策记录：暗色终端（用户钦定）；彻底移除 qfluentwidgets；全中文文案；标题 voxov。

## 1. 目标与范围

整壳重构：FluentWindow → 原生 QMainWindow + 顶栏文本 tab + 底部状态行；三页全部按预览页重做；删除彩排、向导、设置弹窗；Lucide 图标体系。与全话轮路由 spec（2026-10-04）同一批次交付。

## 2. Tokens（app/theme.py 全量重写）

| token | 值 | 用途 |
|---|---|---|
| bg | #0a0a0a | 窗口底 |
| bg_raise | #111111 | 输入框/下拉 |
| bg_hover | #151515 | 悬停 |
| fg | #e6e6e6 | 正文 |
| fg_dim | #9a9a9a | 次级 |
| fg_faint | #5c5c5c | 标注/状态 |
| line | #2a2a2a | 1px 边框/分割线 |
| accent | #5af78e | 强调/激活/ok |
| warn | #e3b341 | 警告 |
| danger | #f85149 | 错误/删除线 |

字体 `Cascadia Mono → Consolas → Microsoft YaHei UI`，QFont letter-spacing +0.5pt。
全局禁用：圆角、阴影、渐变。选择态用反白（fg 底 / bg 字，表格行、选中项）。

## 3. 壳（app/main_window.py 重写）

- QMainWindow；窗标题 `voxov`（放弃旧中性名 Notes——用户指示）；
- 顶栏：文本 tab 监听/知识库/设置（QPushButton 扁平 + 底边 2px accent 为激活态），1px 下边线；无 logo、无图标；
- 底部状态行：`model: 就绪 · kb: 4 文件 · hotkey: ctrl+alt+space` + 右侧消息槽（替代 InfoBar：保存/失败/停止等反馈打在状态行，4s 后清空）；
- InfoBar、悬浮窗残留全部移除；托盘菜单「下载模型」→「设置」跳转设置页。

## 4. 页面

### 监听（app/ui_chat.py 重写）
- 头行仅两个控件：[开始监听]（accent 描边按钮，图标 mic/square）+ [x] 自动作答（复选框：方框内 accent 实心方块表示选中）；**右上不放任何状态文本**；
- 对话流无气泡容器：面试官行 = fg_dim + `›` 前缀；回答 = fg 正文（QTextBrowser markdown，**加粗渲染为 accent 色**）；标注 = fg_faint 12px + `──` 前缀；话轮间 1px 分割线（#1e1e1e）；
- 回答正文区沿用 `_AutoHeightBrowser`（NoFrame、无滚动条、高度实排）；
- 生成中占位 `正在生成…`；中断标注沿用现有 notice 文案。

### 知识库
- QTableView：无编辑触发器、整行选中、反白选中态、无竖向网格线、行间 1px 横线、行高加大、表头 fg_faint 12px；
- 操作行：上传/删除/导出（Lucide 图标 + 文字，1px 边框方角按钮）；
- 空态：`暂无文件 —— 上传 markdown 开始构建知识库`。

### 设置（app/settings_page.py 新建；settings_dialog.py 删除）
直线分节表单（label 左 9ch 弱色 + 字段右）：
1. `# 语音模型`：状态行 + 下载/取消按钮 + 平面进度条（下载中态；就绪态显示 `已就绪 · [重新下载]`）——DownloadWorker 迁入本页，wizard.py 删除；
2. `# 大模型`：base url / api key（密码态）/ 模型名；
3. `# 热键`：触发 / 急隐藏（保存前 keyboard.parse_hotkey 校验，沿用现逻辑，非法拒绝并打状态行）；
4. `# 音频与目录`：设备下拉；模型目录（hint：语音识别与向量检索模型统一存放于此）；数据目录；
5. 右下 [保存]：save_config + 重建 LLM 客户端 + 重绑热键（沿用 _apply_settings）。

## 5. 图标（app/icons.py 新建）

Lucide（ISC）SVG vendor 进 `assets/icons/*.svg`：mic、square、upload、trash、download、save、file-text、x、refresh-cw。`icon(name, color) -> QIcon`：QSvgRenderer 渲染、按 token 着色。按钮图标 13px、stroke-width 1.75、square 线帽。依赖 PySide6-QtSvg（PySide6 自带）。

## 6. 删除清单

- 彩排：`start_rehearsal`、`_rehearse_clicked`、`rehearsal_rag_factory` 及 MainWindow 参数、`SessionRecorder(rehearsal=True)` 分支、tests/test_rehearsal.py；`WavFileSource` 类保留（管线基建，单测仍覆盖）；
- `app/wizard.py`、`app/settings_dialog.py`；
- qfluentwidgets 全部 import（main_window/ui_chat/main.py）及 pyproject 依赖；`setTheme` 调用删除；
- InfoBar 及 _info() —— 统一改状态行消息 `set_status(text)`。

## 7. 测试影响面

- 改写：test_main_window.py、test_main_window_ui.py、test_main_app.py、test_theme.py、test_download_flow.py（向导→设置页）；
- 删除：test_rehearsal.py；
- 新增：状态行消息、设置页保存/校验、tab 切换、图标 helper；
- 不动：core/* 全部测试。

## 8. 验收

1. 截图与预览页逐屏比对（监听/知识库/设置）；
2. 全量 pytest 通过（路由 + UI 两批）；
3. 彩排删除后：托盘与主窗无残留入口，导出会话仍工作；
4. 打包 spec（interview-assistant.spec）如有 qfluentwidgets hiddenimports 引用一并清理。

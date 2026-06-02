# 🎬 视频笔记生成器（Video Notes）

> 输入视频链接或本地文件，AI 自动分析字幕和画面，生成结构化笔记。
> **支持无字幕视频 — Whisper 语音识别 + AI 视觉分析。**

---

## ✨ 功能

- 🔗 **支持数千个视频网站** — YouTube、Bilibili、Twitter/X、TikTok、Vimeo 等
- 📁 **本地视频文件** — 拖入 mp4/mkv/webm，直接分析（无需字幕）
- 📥 **自动下载字幕** — 手动字幕 + 自动生成字幕，多语言按优先级尝试
- 🎙️ **Whisper 语音识别** — 无字幕时自动提取音频转文字
- 🖼️ **智能提取关键帧** — 按时间间隔截取画面，用于 AI 视觉分析
- 🧠 **多 AI 平台** — OpenAI（GPT-4o-mini）、Anthropic（Claude）、DeepSeek、Ollama 本地模型
- 🌐 **自定义 API 地址** — 支持中转 API（如 highwayapi.ai），GUI 一键切换
- 🍪 **年龄限制绕过** — 自动从 Chrome 提取 cookies 访问受限视频
- 📝 **结构化笔记** — 视频信息、更新摘要、逐条时间戳内容、浓缩总结
- 🖥️ **GUI + CLI 双模式** — 双击启动图形界面，也支持命令行批量处理
- 📦 **单文件分发** — 自包含 Python + ffmpeg + Whisper，无需安装任何依赖

---

## 🚀 快速开始

### 方式一：图形界面（推荐）

双击 `video-notes.exe`，然后：

1. 粘贴视频链接或选择本地文件
2. 选择 AI 平台（OpenAI / Anthropic / DeepSeek / Ollama）
3. 填入 API 密钥
4. 点击「生成笔记」

> **提示**：API 地址字段已预填默认值（OpenAI → highwayapi.ai，Ollama → localhost:11434），可按需修改。

### 方式二：命令行

```bash
# 基本用法
video-notes.exe "https://www.youtube.com/watch?v=XXXXX"

# 指定平台和模型
video-notes.exe "URL" -p openai -m gpt-4o-mini -l zh

# 自定义 API 地址
video-notes.exe "URL" --api-base https://api.highwayapi.ai/openai

# 本地视频（无字幕自动用 Whisper + 视觉分析）
video-notes.exe --local-file video.mp4 -l zh

# 仅获取视频信息
video-notes.exe "URL" --dry-run
```

### 命令行参数

| 参数                  | 默认值          | 说明                                                    |
| --------------------- | --------------- | ------------------------------------------------------- |
| `url`                 | *必填*          | 视频链接                                                |
| `--local-file`        | —               | 本地视频文件路径                                        |
| `-o, --output`        | `./notes`       | 输出目录                                                |
| `-p, --provider`      | `openai`        | AI 平台：`openai` / `anthropic` / `deepseek` / `ollama` |
| `-m, --model`         | 自动选择        | 模型名称                                                |
| `-k, --api-key`       | 环境变量        | API 密钥                                                |
| `--api-base`          | —               | 自定义 API 地址（中转站 / 代理）                        |
| `--use-cookies`       | —               | 从 Chrome 提取 cookies（年龄限制视频）                  |
| `--frame-interval`    | `30`            | 截图间隔（秒）                                          |
| `--max-frames`        | `20`            | 最大截图数                                              |
| `--languages`         | `en,zh-Hans,ja` | 字幕语言偏好列表                                        |
| `-l, --note-language` | `zh`            | 笔记语言：`zh` / `en` / `ja` 等                         |
| `--keep-video`        | —               | 保留下载的视频文件                                      |
| `--keep-frames`       | —               | 保留提取的截图                                          |
| `--dry-run`           | —               | 仅获取视频信息，不分析                                  |
| `-v, --verbose`       | —               | 输出详细日志                                            |

### 环境变量

```bash
# Windows (cmd)
set OPENAI_API_KEY=sk-xxx
set ANTHROPIC_API_KEY=sk-ant-xxx
set DEEPSEEK_API_KEY=sk-xxx
set WHISPER_MODEL=small      # Whisper 模型: tiny / small / medium

# macOS / Linux
export OPENAI_API_KEY=sk-xxx
```

---

## 🤖 AI 平台对比

| 平台          | 视觉分析 | 默认模型        | 默认 API 地址                       | API Key 获取       |
| ------------- | :------: | --------------- | ----------------------------------- | ------------------ |
| **OpenAI**    |    ✅     | `gpt-4o-mini`   | `https://api.highwayapi.ai/openai`  | highwayapi.ai      |
| **Anthropic** |    ✅     | `claude-sonnet-4-20250514` | — (官方 SDK)          | console.anthropic.com |
| **DeepSeek**  |    ❌     | `deepseek-chat` | `https://api.deepseek.com`          | platform.deepseek.com |
| **Ollama**    |    ✅     | `llama3.2-vision` | `http://localhost:11434`          | 本地，无需 Key     |

> DeepSeek 不支持图像输入，无法分析视频画面。如需视觉分析请使用 OpenAI 或 Anthropic。

---

## 📄 笔记输出格式

```
[视频信息]
标题: xxx
频道: xxx
时长: 6m 12s
来源: https://...

[更新摘要]
简要概述视频核心内容

[更新内容列表]
00:05 - 具体更新项（带时间戳）
02:13 - 另一项更新
...

[浓缩总结]
将所有更新内容浓缩为一段连贯叙述
```

---

## 🔧 无字幕视频处理流程

```
无字幕视频
  └→ ffmpeg 提取音频 (16kHz mono WAV)
  └→ faster-whisper 语音转文字 (small 模型)
  └→ ffmpeg 提取关键帧 (每 N 秒一张)
  └→ AI 视觉分析 (帧 + 文字 → 结构化笔记)
```

---

## ❓ 常见问题

<details>
<summary><b>没有字幕的视频能分析吗？</b></summary>
可以。程序会自动用 Whisper 语音识别 + AI 视觉分析画面帧来生成笔记。
</details>

<details>
<summary><b>年龄限制视频怎么处理？</b></summary>
GUI 中勾选「年龄限制视频自动从 Chrome 登录」，程序会从 Chrome 提取 YouTube cookies 来验证年龄。
</details>

<details>
<summary><b>如何用中转 API（如 highwayapi.ai）？</b></summary>
GUI 的 API 地址字段已默认预填 highwayapi.ai，直接填 Key 即可。CLI 用 `--api-base` 参数指定。
</details>

<details>
<summary><b>需要安装 Python 或 ffmpeg 吗？</b></summary>
不需要。exe 已内置 Python 运行时、ffmpeg、Whisper 模型和全部依赖库。
</details>

<details>
<summary><b>支持哪些视频网站？</b></summary>
基于 yt-dlp，支持数千个网站：YouTube、Bilibili、Twitter/X、TikTok、Vimeo、Twitch、微博、优酷、爱奇艺、腾讯视频等。
</details>

<details>
<summary><b>API 密钥安全吗？</b></summary>
密钥仅存在于本地内存中，不会上传、记录或发送到第三方。
</details>

---

## 🛠️ 技术栈

| 组件                   | 用途                 |
| ---------------------- | -------------------- |
| Python 3.12            | 主体语言             |
| yt-dlp                 | 视频 / 字幕下载      |
| ffmpeg                 | 关键帧 + 音频提取    |
| faster-whisper         | 语音识别（无字幕时） |
| OpenAI / Anthropic SDK | AI 视觉 + 文本分析   |
| Pillow                 | 图像处理与压缩       |
| tkinter                | GUI 图形界面         |
| PyInstaller            | 打包为单文件 exe     |

---

## 📋 版本

| 版本 | 日期    | 更新                                                    |
| ---- | ------- | ------------------------------------------------------- |
| v1.3 | 2026-06 | 自定义 API 地址、highwayapi.ai 集成、cookies 年龄验证、GUI API 地址输入框 |
| v1.2 | 2026-06 | GUI 全中文、通用视频网站支持、内置 ffmpeg、取消响应优化 |
| v1.1 | 2026-06 | 新增 GUI、修复 21 个代码缺陷、管道重构                  |
| v1.0 | 2026-05 | 初版 CLI                                                |

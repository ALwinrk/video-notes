# 🎬 视频笔记生成器（Video Notes）

> 输入视频链接，AI 自动下载视频、提取字幕和关键帧，生成结构化笔记。
>
> **一个 exe 文件，无需安装 Python，开箱即用。**

---

## ✨ 功能

- 🔗 **支持数千个视频网站** — YouTube、Bilibili、Twitter/X、TikTok、Vimeo 等
- 📥 **自动下载字幕** — 手动字幕 + 自动生成字幕，多语言按优先级尝试
- 🖼️ **智能提取关键帧** — 按时间间隔截取画面，用于 AI 视觉分析
- 🧠 **多 AI 平台** — OpenAI（GPT-4o）、Anthropic（Claude）、DeepSeek、Ollama 本地模型
- 📝 **结构化笔记** — 视频信息、更新摘要、逐条时间戳内容、浓缩总结
- 🖥️ **GUI + CLI 双模式** — 双击启动图形界面，也支持命令行批量处理
- 🚫 **随时取消** — 生成过程中点击取消，1-5 秒恢复就绪
- 📦 **单文件分发** — 111MB 的 exe，无需安装任何依赖

---

## 🚀 快速开始

### 方式一：图形界面（推荐）

双击 `video-notes.exe`，然后：

1. 粘贴视频链接
2. 选择 AI 平台和模型
3. 填入 API 密钥
4. 点击「生成笔记」

### 方式二：命令行

```bash
# 基本用法
video-notes.exe "https://www.youtube.com/watch?v=XXXXX"

# 指定平台和模型
video-notes.exe "URL" -p anthropic -m claude-sonnet-4-20250514 -l zh

# 使用 DeepSeek
video-notes.exe "URL" -p deepseek -m deepseek-chat -l zh

# 只查看信息不分析
video-notes.exe "URL" --dry-run
```

### 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `url` | *必填* | 视频链接 |
| `-o, --output` | `./notes` | 输出目录 |
| `-p, --provider` | `openai` | AI 平台：`openai` / `anthropic` / `deepseek` / `ollama` |
| `-m, --model` | 自动选择 | 模型名称 |
| `-k, --api-key` | 环境变量 | API 密钥 |
| `--api-base` | — | 自定义 API 地址（代理 / Ollama） |
| `--frame-interval` | `30` | 截图间隔（秒） |
| `--max-frames` | `20` | 最大截图数 |
| `--languages` | `en,zh-Hans,ja` | 字幕语言偏好列表 |
| `-l, --note-language` | `zh` | 笔记语言：`zh` / `en` / `ja` 等 |
| `--keep-video` | — | 保留下载的视频文件 |
| `--keep-frames` | — | 保留提取的截图 |
| `--dry-run` | — | 仅获取视频信息，不分析 |
| `-v, --verbose` | — | 输出详细日志 |

### 环境变量

```bash
# Windows (cmd)
set OPENAI_API_KEY=sk-xxx
set ANTHROPIC_API_KEY=sk-ant-xxx
set DEEPSEEK_API_KEY=sk-xxx

# macOS / Linux
export OPENAI_API_KEY=sk-xxx
```

---

## 🤖 AI 平台对比

| 平台 | 视觉分析 | 推荐模型 | 获取 API Key |
|------|:---:|------|------|
| **OpenAI** | ✅ | `gpt-4o` | https://platform.openai.com |
| **Anthropic** | ✅ | `claude-sonnet-4-20250514` | https://console.anthropic.com |
| **DeepSeek** | ❌ | `deepseek-chat` | https://platform.deepseek.com |
| **Ollama** | ✅ | `llama3.2-vision` | 本地运行，无需 Key |

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

## ❓ 常见问题

<details>
<summary><b>程序启动有点慢？</b></summary>
首次启动约 15 秒（解压内置组件到缓存），之后每次约 2 秒。缓存位置：<code>%LOCALAPPDATA%\video-notes</code>，重启电脑不会清除。
</details>

<details>
<summary><b>需要安装 Python 或 ffmpeg 吗？</b></summary>
完全不需要。exe 已内置 Python 运行时、ffmpeg 和全部依赖库。
</details>

<details>
<summary><b>没有字幕的视频能分析吗？</b></summary>
可以。程序会仅基于视频画面帧进行视觉分析（需要支持视觉的 AI 平台如 OpenAI/Anthropic）。
</details>

<details>
<summary><b>为什么 DeepSeek 不能分析画面？</b></summary>
DeepSeek API 目前不支持图像视觉输入。如需画面分析请换用 OpenAI 或 Anthropic。DeepSeek 仍可用于基于字幕的文本分析。
</details>

<details>
<summary><b>点击取消后卡住了？</b></summary>
已优化为 1-5 秒内响应。唯一无法立即中断的是正在进行的 AI API 调用（取决于网络延迟），调用完成后会立即停止后续步骤。
</details>

<details>
<summary><b>支持哪些视频网站？</b></summary>
基于 yt-dlp，支持数千个网站：YouTube、Bilibili、Twitter/X、TikTok、Vimeo、Twitch、微博、优酷、爱奇艺、腾讯视频等。
</details>

<details>
<summary><b>API 密钥安全吗？</b></summary>
密钥仅存在于本地内存中，不会上传、记录或发送到任何第三方。程序只向所选 AI 平台的官方 API 端点发送请求。
</details>

---

## 🛠️ 技术栈

| 组件 | 用途 |
|------|------|
| Python 3.12 | 主体语言 |
| yt-dlp | 视频 / 字幕下载 |
| ffmpeg | 关键帧提取（已内置） |
| OpenAI / Anthropic SDK | AI 分析 |
| Pillow | 图像处理与压缩 |
| tkinter | GUI 图形界面 |
| PyInstaller | 打包为单文件 exe |

---

## 📋 版本

| 版本 | 日期 | 更新 |
|------|------|------|
| v1.2 | 2026-06 | GUI 全中文、通用视频网站支持、内置 ffmpeg、取消响应优化 |
| v1.1 | 2026-06 | 新增 GUI、修复 21 个代码缺陷、管道重构 |
| v1.0 | 2026-05 | 初版 CLI |

---

## 📧 反馈

如有问题或建议，请联系开发者。

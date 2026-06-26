# Video Notes — AI 视频笔记生成器

下载视频、提取关键帧、语音转录，使用 AI 视觉分析自动生成结构化笔记。

专为**游戏更新视频**优化（爆料、Patch Notes、开发者日志），同时支持所有视频类型。

## 支持平台

| 视频平台 | 字幕 | 下载 | 说明 |
|----------|------|------|------|
| YouTube | ✅ 多通道获取 | ✅ | transcript-api / yt-dlp / Invidious |
| Bilibili (B站) | ✅ | ✅ | yt-dlp 内置提取器 |
| TikTok / 抖音 | ✅ | ✅ | yt-dlp 内置提取器 |
| Facebook | ✅ | ✅ | yt-dlp 内置提取器 |
| 本地文件 | — | — | mp4/mkv/webm/avi/mov/flv |
| 其他 | ✅ | ✅ | yt-dlp 支持 1000+ 站点 |

## AI 平台支持

| 平台 | 模型 | 视觉分析 | 费用 | 适用场景 |
|------|------|----------|------|----------|
| **OpenAI** | gpt-4o / gpt-4o-mini | ✅ | 按量付费 | 综合最佳 |
| **Anthropic** | claude-sonnet-4 / opus-4 | ✅ | 按量付费 | 长视频深度分析 |
| **DeepSeek** | deepseek-chat | ❌ 仅文字 | ¥0.001/1K tokens | 有字幕视频 |
| **Ollama** | llama3.2-vision 等 | ✅ | 免费本地 | 离线/隐私 |

## 语音转录

无字幕视频自动语音转文字，三级降级链：

```
Groq Whisper（1000分钟/月免费，最快）
  → OpenAI Whisper（$0.006/分钟）
    → whisper.cpp tiny（本地 75MB，离线可用）
```

## 视频类型自适应

自动检测视频中有无字幕和音频，走最优路径：

| 类型 | 字幕 | 音频 | 处理方式 |
|------|------|------|----------|
| 完整 | ✅ | ✅ | 字幕优先 + 关键帧提取 |
| 有字幕无声 | ✅ | ❌ | 字幕 + 帧提取 |
| 无字幕有声 | ❌ | ✅ | 语音转录 + 帧提取 |
| 纯画面 | ❌ | ❌ | 纯视觉帧分析（最多 60 帧） |

## 安装

### 方式一：EXE 直接运行（推荐）

下载 `video-notes.exe`，双击启动。

首次运行需安装依赖：
- **ffmpeg**（必需）：`winget install ffmpeg` 或下载放入同目录

### 方式二：Python 源码运行

```bash
git clone https://github.com/ALwinrk/video-notes.git
cd video-notes/youtube_notes
pip install -r requirements.txt
python main.py
```

**依赖：**
- Python 3.12+
- ffmpeg（系统安装或放入 youtube_notes/ 目录）
- yt-dlp, openai, anthropic, pillow, youtube-transcript-api

## 使用

### GUI（双击 EXE 或无参数运行）

```
video-notes.exe
```

1. 粘贴视频链接（或选择本地文件）
2. 选择 AI 平台和模型
3. 填入 API 密钥（Ollama 本地无需）
4. 可选：配置 Cookies 绕过 YouTube 登录
5. 点击「生成笔记」

### CLI

```bash
# 基本使用
video-notes.exe "https://www.youtube.com/watch?v=XXXXX"

# 指定平台和模型
video-notes.exe URL -p anthropic -m claude-sonnet-4-20250514

# 指定输出语言
video-notes.exe URL -l zh

# 使用 Ollama 本地模型
video-notes.exe URL -p ollama -m llama3.2-vision --api-base http://localhost:11434

# 使用 DeepSeek（便宜，无视觉）
video-notes.exe URL -p deepseek -m deepseek-chat

# 导入 cookies 绕过登录
video-notes.exe URL --cookies-file cookies.txt
video-notes.exe URL --cookies-from-browser chrome

# 选择转录方案
video-notes.exe URL --transcriber groq      # 仅 Groq（免费）
video-notes.exe URL --transcriber local     # 仅本地 whisper.cpp

# 禁用游戏分析模式
video-notes.exe URL --no-game-analysis

# 预览模式（仅获取信息，不分析）
video-notes.exe URL --dry-run

# 本地文件
video-notes.exe "C:\videos\gameplay.mp4"
```

### 环境变量

```bash
set OPENAI_API_KEY=sk-xxxxx        # OpenAI
set ANTHROPIC_API_KEY=sk-ant-xxxxx # Anthropic
set DEEPSEEK_API_KEY=sk-xxxxx      # DeepSeek
set GROQ_API_KEY=gsk_xxxxx         # Groq Whisper（免费转录）
```

## YouTube 登录问题

部分 YouTube 视频需要登录才能获取。两种方式：

1. **浏览器 Cookies**（GUI 下拉选择 chrome/firefox/edge）
2. **手动导出** cookies.txt 并导入（使用 Get cookies.txt LOCALLY 扩展）

## 输出格式

```
[视频信息]
标题: 3.8版本更新内容
频道: 官方频道
时长: 15m 30s
性质: official

[更新摘要]
本次 3.8 版本更新带来了新英雄"影"、排位赛段位奖励调整...

[更新内容列表]
03:22 - 🆕 [官方] 新增英雄"影"，被动技能每3次普攻触发额外伤害
05:10 - ⚖️ [官方] 排位赛段位奖励调整，钻石段位新增限定皮肤
07:45 - 🐛 [官方] 修复了组队时语音断连的bug
12:30 - 🎉 [官方] 限时活动"夏日庆典"7月15日至7月30日开启
18:00 - 💬 [爆料] 据传下个版本将加入新地图"龙穴"

[浓缩总结]
3.8版本更新引入了新英雄"影"...（完整叙述段落）
```

## 分类标签

| 标签 | 含义 |
|------|------|
| 🆕 新增 | 新功能、英雄、皮肤、物品、地图 |
| 🔧 改动 | 调整、重做、修改 |
| 🐛 修复 | Bug 修复、崩溃修复 |
| ⚖️ 平衡 | 平衡性调整、增强/削弱 |
| 🎉 活动 | 限时活动、促销 |
| 💬 爆料 | 泄漏、数据挖掘（未确认） |

## 构建 EXE

```bash
pip install pyinstaller
pyinstaller youtube-notes.spec
```

需要 ffmpeg (ffmpeg.exe + ffprobe.exe) 放在 `ffmpeg_bundle/` 目录中。

## License

MIT

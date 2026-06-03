---
name: video-agent
description: AI 视频自动生成。输入一个主题，自动搜索资料、LLM生成脚本、中文配音、动态网页动画生成视频。Use when needing to create a video from a topic.
---

# 🎬 AI 视频自动生成智能体

输入主题 → 搜索 → 脚本 → 配音 → 动态视频

## 概述

这个 skill 封装了完整的视频自动生成流水线，包含五个步骤：

1. **搜索** — DuckDuckGo 自动搜索主题资料
2. **脚本** — LLM 整理为结构化视频脚本
3. **配音** — Edge TTS 高质量中文语音合成
4. **图片** — 可选 DALL-E / gpt-image-2 生成背景图
5. **视频** — 动态 HTML + Playwright 录制 + ffmpeg 合成

## 前置条件

安装依赖（仅需一次）：

```powershell
cd C:\Users\lkp\video-agent

# Python 依赖
pip install -r requirements.txt

# Playwright 浏览器
playwright install chromium

# FFmpeg（视频录制 + 音频合成必需）
winget install ffmpeg
```

## 配置

编辑 `.env` 文件填入 API Key：

```env
LLM_API_KEY=sk-your-key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o

# 图片生成（可选，不需要则用 --no-images）
IMAGE_GEN_ENABLED=true
IMAGE_GEN_MODEL=gpt-image-2
IMAGE_QUALITY=auto
```

详见 [references/config.md](references/config.md)。

## 使用

### 命令行

```powershell
cd C:\Users\lkp\video-agent

# 基本用法
python main.py "黑洞是如何形成的"

# 不用 AI 图片
python main.py "人工智能的未来" --no-images

# 仅生成 HTML 预览（不录制视频）
python main.py "量子计算" --no-record

# 换配音音色
python main.py "中国航天" --voice zh-CN-YunjianNeural

# 更多参数
python main.py --help
```

### 项目结构

```
video-agent/
├── main.py                  # 主入口
├── config.py                # 配置管理
├── requirements.txt         # 依赖
├── .env.example
├── modules/
│   ├── search.py            # 搜索 (DuckDuckGo)
│   ├── script_generator.py  # LLM 脚本生成
│   ├── tts.py               # 语音合成 (Edge TTS)
│   ├── image_gen.py         # 图片生成 (OpenAI)
│   └── video_builder.py     # HTML构建 + Playwright录制
├── output/                  # 输出目录
│   ├── temp/                # 临时文件
│   ├── images/              # AI 图片
│   └── *.mp4                # 最终视频
└── .agents/skills/video-agent/  # 本 skill
```

## 常见操作

### 只跑 2 个场景测试（快速验证）

在 `modules/script_generator.py` 中，`SYSTEM_PROMPT` 已设为 2 个场景。

### 扩展到完整视频

修改 `modules/script_generator.py` 中的 `SYSTEM_PROMPT`：
- 场景数：`2` → `5~10`
- 旁白字数：`30~60` → `80~150`

### 单独执行某一步

```powershell
# 仅搜索
python main.py "主题" --search-only

# 仅生成 HTML（不进 Playwright）
python main.py "主题" --no-record
```

## 故障排查

| 问题 | 解决 |
|------|------|
| 视频没声音 | 确保安装了 ffmpeg（`winget install ffmpeg`） |
| 图片生成失败 | 检查 `IMAGE_GEN_MODEL` 和 `IMAGE_QUALITY`；或用 `--no-images` |
| TTS 失败 | 检查网络连接微软服务器 |
| 视频只有几秒 | 这是 `-shortest` 的保护机制，检查 TTS 是否成功生成完整音频 |

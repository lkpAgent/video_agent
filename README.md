# 🎬 AI 视频自动生成智能体

输入一个主题 → 自动搜索资料 → LLM 整理脚本 → 中文配音 → 动态网页动画 → 输出视频

## ✨ 核心特性

- 🔍 **自动搜索** — 基于 DuckDuckGo 自动搜索主题相关资料
- 📝 **智能脚本** — LLM 将资料整理为结构化短视频脚本（5~10 个场景）
- 🔊 **中文配音** — Edge TTS 高质量中文语音合成，支持多种音色
- 🎨 **AI 图片** — 可选调用 DALL-E 等多模态模型生成场景背景图
- 🎬 **动态视频** — 通过动态 HTML 网页（CSS 动画 + 音频）生成视频，无需视频大模型
- 🎥 **Playwright 录制** — 自动录制网页动画为 .webm 视频

## 🔄 工作流程

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  输入主题  │ ──▶ │  搜索资料  │ ──▶ │  生成脚本  │ ──▶ │  中文配音  │ ──▶ │  构建视频  │
└──────────┘     └──────────┘     └──────────┘     └──────────┘     └──────────┘
                      │                                  │                  │
                      ▼                                  ▼                  ▼
               DuckDuckGo API                      Edge TTS         动态 HTML 页面
                                                                   + Playwright 录制
                                           ┌──────────┐
                                           │ AI 图片生成 │ (可选)
                                           └──────────┘
                                                │
                                          DALL-E / 兼容 API
```

## 📦 安装

```bash
# 1. 克隆 / 进入项目目录
cd video-agent

# 2. 安装 Python 依赖
pip install -r requirements.txt

# 3. 安装 Playwright 浏览器（用于视频录制）
playwright install chromium

# 4. 可选：安装音频处理库（用于合并多个音频片段）
pip install pydub

# 5. 配置环境变量
copy .env.example .env
# 编辑 .env 文件，填入你的 LLM API Key
```

## ⚙️ 配置

编辑 `.env` 文件：

```env
# 必填：LLM API Key
LLM_API_KEY=sk-your-api-key-here

# API 地址（支持任何 OpenAI 兼容接口，如 DeepSeek、通义千问等）
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o

# 可选：图片生成
IMAGE_GEN_ENABLED=true
IMAGE_GEN_MODEL=dall-e-3
```

### 兼容的 LLM 服务

| 服务 | BASE_URL |
|------|----------|
| OpenAI | `https://api.openai.com/v1` |
| DeepSeek | `https://api.deepseek.com` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` |
| 本地 Ollama | `http://localhost:11434/v1` |
| SiliconFlow | `https://api.siliconflow.cn/v1` |

## 🚀 使用

### 命令行模式

```bash
# 基本用法：输入主题，全流程生成视频
python main.py "黑洞是如何形成的"

# 不生成 AI 图片（使用纯色背景）
python main.py "人工智能的起源" --no-images

# 仅生成 HTML 预览，不录制视频
python main.py "全球变暖的影响" --no-record

# 更换配音音色
python main.py "中国航天发展史" --voice zh-CN-YunjianNeural

# 更换视频主题风格
python main.py "量子计算机原理" --theme light

# 自定义输出文件名
python main.py "5G技术解析" --output 5g_explained

# 仅搜索（调试用）
python main.py "区块链技术" --search-only

# 添加额外创作指令
python main.py "深度学习入门" --custom-instruction "面向小学生的科普，用简单比喻"
```

### 交互模式

```bash
python main.py
# 然后输入主题
```

### TTS 音色参考

| 音色 ID | 描述 |
|---------|------|
| `zh-CN-XiaoxiaoNeural` | 温柔女声（默认） |
| `zh-CN-YunxiNeural` | 阳光男声 |
| `zh-CN-YunjianNeural` | 沉稳男声 |
| `zh-CN-XiaoyiNeural` | 活泼女声 |
| `zh-CN-YunyangNeural` | 新闻男声 |

### 视频主题风格

| 风格 | 说明 |
|------|------|
| `dark` | 暗色主题（默认），科技感 |
| `light` | 亮色主题，清新 |
| `warm` | 暖色主题，温馨 |

## 📁 项目结构

```
video-agent/
├── main.py                  # 主入口，编排全流程
├── config.py                # 配置管理
├── requirements.txt         # Python 依赖
├── .env.example             # 环境变量模板
├── modules/
│   ├── __init__.py
│   ├── search.py            # 搜索模块 (DuckDuckGo)
│   ├── script_generator.py  # 脚本生成模块 (LLM)
│   ├── tts.py               # 语音合成模块 (Edge TTS)
│   ├── image_gen.py         # 图片生成模块 (DALL-E)
│   └── video_builder.py     # 视频构建模块 (HTML + Playwright)
├── output/                  # 输出目录
│   ├── temp/                # 临时文件（脚本、音频、HTML）
│   ├── images/              # AI 生成的图片
│   └── *.webm               # 最终视频文件
└── README.md
```

## 🔧 脚本结构说明

LLM 生成的脚本格式：

```json
{
  "title": "视频标题",
  "description": "一句话简介",
  "scenes": [
    {
      "type": "opening",
      "narration": "开场旁白文案（80~150字）",
      "text_overlay": "屏幕叠加文字",
      "image_prompt": "英文图片描述 prompt",
      "duration": 4
    },
    {
      "type": "content",
      "narration": "正文旁白",
      "text_overlay": "关键观点",
      "image_prompt": "visual description in English",
      "duration": 8
    },
    {
      "type": "closing",
      "narration": "结尾文案",
      "text_overlay": "感谢观看",
      "image_prompt": "end screen prompt",
      "duration": 4
    }
  ]
}
```

## 🎯 设计理念

### 为什么用动态网页代替视频大模型？

1. **成本低** — 无需昂贵的视频生成 API
2. **可控性强** — CSS 动画精确控制每个场景的效果
3. **质量稳定** — 不会出现视频大模型的"幻觉"和画面扭曲
4. **可定制** — 轻松修改 HTML 模板来改变视频风格
5. **速度快** — 渲染一个网页比生成视频帧快得多

### 技术栈

- **搜索**: DuckDuckGo (免费无需 API Key)
- **LLM**: OpenAI / 兼容 API（生成脚本 + 图片 prompt）
- **TTS**: Microsoft Edge TTS (免费，高质量中文)
- **图片**: DALL-E 3 / 兼容 API
- **视频**: HTML5 + CSS Animations + Playwright 录制

## 🛠️ 常见问题

### Q: 视频格式是 .webm，如何转为 .mp4？

```bash
ffmpeg -i output/video.webm -c:v libx264 -preset fast -crf 22 output/video.mp4
```

### Q: 如何在没有 GPU 的服务器上运行？

Playwright 支持 headless 模式，无需 GPU。如果无法安装 Chromium：

```bash
playwright install --with-deps chromium
```

### Q: TTS 提示下载失败？

Edge TTS 需要网络连接微软服务器。如遇问题，可以：
- 检查网络连接
- 尝试升级 edge-tts：`pip install --upgrade edge-tts`

### Q: 可以用本地大模型吗？

可以！设置 `LLM_BASE_URL=http://localhost:11434/v1` 配合 Ollama：

```bash
ollama pull qwen2.5:7b
# .env
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen2.5:7b
```

## 📝 License

MIT

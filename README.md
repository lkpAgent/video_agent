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
cd video-agent
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
# 编辑 .env，填入 API Key
```

## 🚀 启动（Web 界面）

### 本地开发

开两个终端：

```bash
# 终端 1：后端 API
python web_server.py
# → http://localhost:8888

# 终端 2：前端页面
python -m http.server 3000 --directory static
# → http://localhost:3000
```

浏览器打开 `http://localhost:3000`。

### 生产部署

后端：
```bash
cd /opt/video-agent
bash start_backend.sh
```

前端（Nginx）：
```nginx
server {
    listen 80;
    server_name your-domain.com;

    location /video {
        alias /usr/share/nginx/html/video;
        index index.html;
        try_files $uri $uri/ /video/index.html;
    }

    location /video-api/ {
        proxy_pass http://127.0.0.1:8888;
        proxy_read_timeout 600s;
    }

    location /output/ {
        proxy_pass http://127.0.0.1:8888;
    }
}
```

访问 `http://your-domain.com/video`。

### 命令行模式（无 Web）

```bash
# 科普视频
python main.py "黑洞是如何形成的"

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
├── web_server.py            # FastAPI 后端
├── main.py                  # CLI 入口
├── config.py                # 配置管理
├── requirements.txt         # 依赖
├── .env.example             # 环境变量模板
├── nginx.conf               # Nginx 配置示例
├── start_backend.sh         # 生产启动脚本
├── static/
│   ├── index.html           # React 前端
│   └── backgrounds/         # 预设背景图
├── modules/
│   ├── db.py                # 数据库（PostgreSQL/SQLite）
│   ├── search.py            # 搜索（DuckDuckGo/Tavily）
│   ├── script_generator.py  # LLM 脚本生成
│   ├── tts.py               # 语音合成（Edge/Doubao/ElevenLabs）
│   ├── image_gen.py         # 图片生成（OpenAI/Doubao）
│   ├── video_builder.py     # 科普视频 HTML + 录制
│   ├── narration_video.py   # 口播视频 HTML + 录制
│   └── selenium_recorder.py # Selenium 录制引擎
├── tools/
│   └── clone_voice_doubao.py # 豆包声音克隆工具
├── data/                    # 数据库文件
└── output/                  # 生成的视频

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

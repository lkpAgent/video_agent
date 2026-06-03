# 视频智能体配置参考

## 完整环境变量

```env
# ====== LLM 大模型 ======
LLM_API_KEY=sk-your-api-key-here
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o
LLM_MAX_TOKENS=4096

# ====== 图片生成 ======
IMAGE_GEN_ENABLED=true
IMAGE_GEN_API_KEY=          # 留空复用 LLM_API_KEY
IMAGE_GEN_BASE_URL=         # 留空默认 OpenAI 官方
IMAGE_GEN_MODEL=gpt-image-2
IMAGE_QUALITY=auto          # gpt-image-2 支持: low/medium/high/auto
IMAGE_SIZE=1792x1024

# ====== TTS 语音 ======
# 音色:
#   zh-CN-XiaoxiaoNeural  温柔女声(默认)
#   zh-CN-YunxiNeural     阳光男声
#   zh-CN-YunjianNeural   沉稳男声
#   zh-CN-XiaoyiNeural    活泼女声
TTS_VOICE=zh-CN-XiaoxiaoNeural
TTS_RATE=+10%
TTS_PITCH=+0Hz

# ====== 视频 ======
VIDEO_WIDTH=1920
VIDEO_HEIGHT=1080
VIDEO_FPS=30
VIDEO_THEME=dark            # dark / light / warm

# ====== 搜索 ======
SEARCH_MAX_RESULTS=10
SEARCH_REGION=zh-cn

# ====== 输出 ======
OUTPUT_DIR=./output
TEMP_DIR=./output/temp
IMAGE_OUTPUT_DIR=./output/images
VIDEO_OUTPUT_DIR=./output
```

## 兼容的 LLM 服务

| 服务 | BASE_URL | 模型示例 |
|------|----------|----------|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o`, `gpt-4-turbo` |
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-plus` |
| Ollama 本地 | `http://localhost:11434/v1` | `qwen2.5:7b` |
| SiliconFlow | `https://api.siliconflow.cn/v1` | `Qwen/Qwen2.5-7B-Instruct` |

## 兼容的图片生成服务

| 服务 | BASE_URL | 模型 | quality |
|------|----------|------|---------|
| OpenAI | `https://api.openai.com/v1` | `dall-e-3` | `standard`, `hd` |
| OpenAI | `https://api.openai.com/v1` | `gpt-image-2` | `low`, `medium`, `high`, `auto` |

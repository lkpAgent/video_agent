"""
视频自动生成智能体 - 配置文件

通过 .env 文件或环境变量配置 API Key 等参数
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """全局配置"""

    # ======== LLM 配置 ========
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "your-api-key-here")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "8192"))

    # ======== 图片生成配置 ========
    IMAGE_GEN_ENABLED: bool = os.getenv("IMAGE_GEN_ENABLED", "true").lower() == "true"
    # 提供商: openai / doubao
    IMAGE_GEN_PROVIDER: str = os.getenv("IMAGE_GEN_PROVIDER", "openai")
    # API Key：留空则复用 LLM 的 Key
    IMAGE_GEN_API_KEY: str = os.getenv("IMAGE_GEN_API_KEY") or LLM_API_KEY
    # API 地址：留空默认 OpenAI 官方（不跟随 LLM 地址，因为 LLM 可能用的不兼容服务）
    IMAGE_GEN_BASE_URL: str = os.getenv("IMAGE_GEN_BASE_URL") or "https://api.openai.com/v1"
    IMAGE_GEN_MODEL: str = os.getenv("IMAGE_GEN_MODEL", "dall-e-3")
    # 生成图片的分辨率
    IMAGE_SIZE: str = os.getenv("IMAGE_SIZE", "1024x1792")  # 竖屏 9:16
    # 图片质量: low / medium / high / auto（gpt-image-2 不支持 standard）
    IMAGE_QUALITY: str = os.getenv("IMAGE_QUALITY", "auto")
    # 豆包（Doubao / 火山引擎）
    DOUBAO_API_KEY: str = os.getenv("DOUBAO_API_KEY", "")
    DOUBAO_ACCESS_KEY: str = os.getenv("DOUBAO_ACCESS_KEY", "")
    DOUBAO_MODEL: str = os.getenv("DOUBAO_MODEL", "doubao-seedream-4-5-251128")
    DOUBAO_SIZE: str = os.getenv("DOUBAO_SIZE", "2K")
    # 豆包声音克隆
    DOUBAO_SPEAKER_ID: str = os.getenv("DOUBAO_SPEAKER_ID", "")  # 克隆后的音色 ID
    # 豆包 TTS（声音复刻）
    DOUBAO_TTS_API_KEY: str = os.getenv("DOUBAO_TTS_API_KEY", DOUBAO_API_KEY)
    DOUBAO_TTS_VOICE_TYPE: str = os.getenv("DOUBAO_TTS_VOICE_TYPE", "")
    DOUBAO_TTS_CLUSTER: str = os.getenv("DOUBAO_TTS_CLUSTER", "volcano_icl")
    DOUBAO_TTS_SYNTHESIS_URL: str = os.getenv(
        "DOUBAO_TTS_SYNTHESIS_URL",
        "https://openspeech.bytedance.com/api/v3/tts/unidirectional",
    )
    DOUBAO_TTS_SYNTHESIS_RESOURCE_ID: str = os.getenv("DOUBAO_TTS_SYNTHESIS_RESOURCE_ID", "seed-tts-2.0")
    IMAGE_OUTPUT_DIR: str = os.getenv("IMAGE_OUTPUT_DIR", "./output/images")

    # ======== TTS 配置 ========
    # 语音提供商: edge(免费) / elevenlabs(声音克隆)
    TTS_PROVIDER: str = os.getenv("TTS_PROVIDER", "edge")
    # edge-tts 中文语音：
    #   zh-CN-XiaoxiaoNeural (温柔女声)
    #   zh-CN-YunxiNeural    (阳光男声)
    #   zh-CN-YunjianNeural  (沉稳男声)
    #   zh-CN-XiaoyiNeural   (活泼女声)
    TTS_VOICE: str = os.getenv("TTS_VOICE", "zh-CN-XiaoxiaoNeural")
    TTS_RATE: str = os.getenv("TTS_RATE", "+10%")   # 语速
    TTS_PITCH: str = os.getenv("TTS_PITCH", "+0Hz") # 音调
    # ElevenLabs 声音克隆
    ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
    ELEVENLABS_VOICE_ID: str = os.getenv("ELEVENLABS_VOICE_ID", "")  # 克隆后的 Voice ID
    ELEVENLABS_MODEL: str = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")

    # ======== 视频配置 ========
    # 录制引擎: selenium(默认，Firefox) / playwright
    RECORD_ENGINE: str = os.getenv("RECORD_ENGINE", "selenium")
    RECORD_BROWSER: str = os.getenv("RECORD_BROWSER", "firefox")
    GECKODRIVER_PATH: str = os.getenv("GECKODRIVER_PATH", "./tools/geckodriver.exe" if os.name == "nt" else "")
    VIDEO_OUTPUT_DIR: str = os.getenv("VIDEO_OUTPUT_DIR", "./output")
    # 视频分辨率（竖屏 1080x1920）
    VIDEO_WIDTH: int = int(os.getenv("VIDEO_WIDTH", "1080"))
    VIDEO_HEIGHT: int = int(os.getenv("VIDEO_HEIGHT", "1920"))
    # 帧率
    VIDEO_FPS: int = int(os.getenv("VIDEO_FPS", "30"))
    VIDEO_END_HOLD_SECONDS: float = float(os.getenv("VIDEO_END_HOLD_SECONDS", "2"))
    # 视频色温风格："dark"/"light"/"warm"
    VIDEO_THEME: str = os.getenv("VIDEO_THEME", "dark")

    # ======== 搜索配置 ========
    # 搜索引擎: duckduckgo(免费) / tavily(需API Key，更精准)
    SEARCH_ENGINE: str = os.getenv("SEARCH_ENGINE", "duckduckgo")
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")
    SEARCH_MAX_RESULTS: int = int(os.getenv("SEARCH_MAX_RESULTS", "10"))
    SEARCH_REGION: str = os.getenv("SEARCH_REGION", "zh-cn")

    # ======== 数据库 ========
    # 如果没有配 DATABASE_URL，默认用本地 SQLite
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///data/profiles.db")

    # ======== 输出目录 ========
    OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "./output")
    TEMP_DIR: str = os.getenv("TEMP_DIR", "./output/temp")


config = Config()

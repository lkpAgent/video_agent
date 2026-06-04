"""
豆包（火山引擎）声音克隆脚本
1. 上传录音 → 创建克隆音色
2. 获取 custom_speaker_id 用于后续 TTS

API: POST https://openspeech.bytedance.com/api/v3/tts/voice_clone
"""

import os, sys, json, uuid, base64
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import config


def clone_voice(audio_path: str, speaker_name: str):
    """
    上传音频，克隆声音

    Args:
        audio_path: 录音文件路径（m4a/wav/mp3）
        speaker_name: 自定义音色名称（如 custom_zh_myself）

    Returns:
        custom_speaker_id
    """
    print(f"🎙️  声音克隆: {speaker_name}")
    print(f"   音频文件: {audio_path}")

    if not os.path.exists(audio_path):
        print(f"❌ 文件不存在: {audio_path}")
        return None

    # 读取音频并转 base64
    with open(audio_path, "rb") as f:
        audio_data = f.read()
    audio_b64 = base64.b64encode(audio_data).decode()

    # 检测格式
    ext = Path(audio_path).suffix.lower().replace(".", "")
    if ext in ("m4a", "mp4"):
        audio_format = "m4a"
    elif ext == "mp3":
        audio_format = "mp3"
    else:
        audio_format = ext

    print(f"   格式: {audio_format}, 大小: {len(audio_data)/1024:.1f} KB")

    # 请求
    headers = {
        "X-Api-Key": config.DOUBAO_API_KEY,
        "X-Api-Request-Id": uuid.uuid4().hex,
        "Content-Type": "application/json"
    }

    payload = {
        "speaker_id": "custom_speaker_id",
        "custom_speaker_id": speaker_name,
        "audio": {
            "data": audio_b64,
            "format": "wav"
        },
        "language": 0,
        "extra_params": {
            "voice_clone_denoise_model_id": ""
        }
    }

    url = "https://openspeech.bytedance.com/api/v3/tts/voice_clone"

    print(f"   发送请求...")
    resp = requests.post(url, json=payload, headers=headers, timeout=60)

    print(f"   状态码: {resp.status_code}")
    print(f"   响应: {resp.text[:500]}")

    if resp.status_code == 200:
        result = resp.json()
        speaker_id = result.get("speaker_id") or result.get("custom_speaker_id") or speaker_name
        print(f"\n✅ 克隆成功！")
        print(f"   custom_speaker_id: {speaker_id}")
        print(f"\n   在 .env 中设置:")
        print(f"   DOUBAO_SPEAKER_ID={speaker_id}")
        return speaker_id
    else:
        print(f"\n❌ 克隆失败")
        return None


if __name__ == "__main__":
    audio = r"C:\Users\lkp\Documents\录音\录音 (37).m4a"
    name = "custom_zh_myself"

    if len(sys.argv) >= 2:
        audio = sys.argv[1]
    if len(sys.argv) >= 3:
        name = sys.argv[2]

    clone_voice(audio, name)

"""
统一语音合成模块：支持 Edge TTS(免费) 和 ElevenLabs(声音克隆)

配置 .env:
  TTS_PROVIDER=edge          # 默认免费
  TTS_PROVIDER=elevenlabs    # 声音克隆

ElevenLabs 使用步骤：
  1. 注册 https://elevenlabs.io
  2. 获取 API Key → 填入 ELEVENLABS_API_KEY
  3. 在 ElevenLabs 后台克隆声音 → 获取 VOICE_ID
  4. 填入 ELEVENLABS_VOICE_ID
"""

import os
import asyncio
import uuid
import base64
import requests
from typing import Optional
from rich.console import Console

from config import config

console = Console()

# ====== 统一入口 ======

def tts_generate(text: str, output_path: str) -> str:
    """
    统一 TTS 接口：根据 TTS_PROVIDER 配置自动选择引擎
    """
    provider = config.TTS_PROVIDER.lower()
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    if provider == "elevenlabs":
        return _elevenlabs_tts(text, output_path)
    elif provider == "doubao":
        return _doubao_tts(text, output_path)
    else:
        return _edge_tts_sync(text, output_path)


# ====== Edge TTS（免费，公开音色）======

def _edge_tts_sync(text: str, output_path: str) -> str:
    """Edge TTS 同步调用"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_edge_tts_async(text, output_path))
    finally:
        loop.close()
    return output_path


async def _edge_tts_async(text: str, output_path: str, retries=3):
    """Edge TTS 异步实现，带重试"""
    import edge_tts
    last_err = None
    for attempt in range(retries):
        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=config.TTS_VOICE,
                rate=config.TTS_RATE,
                pitch=config.TTS_PITCH
            )
            await communicate.save(output_path)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 100:
                return
            last_err = RuntimeError("音频文件为空或过小")
        except Exception as e:
            last_err = e
            console.print(f"[yellow]TTS 第 {attempt+1}/{retries} 次失败: {e}[/yellow]")
            if attempt < retries - 1:
                await asyncio.sleep(2)
    raise RuntimeError(f"TTS 重试 {retries} 次均失败: {last_err}")


# ====== ElevenLabs（声音克隆）======

# ====== 豆包 TTS（声音复刻）======

def _doubao_tts(text: str, output_path: str) -> str:
    """豆包（火山引擎）声音复刻 TTS"""
    api_key = config.DOUBAO_TTS_API_KEY
    voice_type = config.DOUBAO_TTS_VOICE_TYPE

    if not api_key:
        raise ValueError("请在 .env 中设置 DOUBAO_API_KEY")
    if not voice_type:
        raise ValueError("请在 .env 中设置 DOUBAO_TTS_VOICE_TYPE（声音克隆后获得的 voice_type）")

    url = "https://openspeech.bytedance.com/api/v1/tts"
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}

    payload = {
        "app": {"cluster": config.DOUBAO_TTS_CLUSTER},
        "user": {"uid": "video_agent"},
        "audio": {"voice_type": voice_type, "encoding": "mp3", "speed_ratio": 1.0},
        "request": {"reqid": uuid.uuid4().hex, "text": text, "operation": "query"}
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=120)
    resp.raise_for_status()
    result = resp.json()

    if result.get("code") != 3000:
        raise RuntimeError(f"豆包 TTS 失败: {result.get('message', 'unknown')}")

    audio_b64 = result.get("data", "")
    if not audio_b64:
        raise RuntimeError("豆包 TTS 未返回音频数据")

    with open(output_path, "wb") as f:
        f.write(base64.b64decode(audio_b64))
    return output_path


def _elevenlabs_tts(text: str, output_path: str) -> str:
    """ElevenLabs 语音合成（支持克隆声音）"""
    api_key = config.ELEVENLABS_API_KEY
    voice_id = config.ELEVENLABS_VOICE_ID

    if not api_key:
        raise ValueError("请在 .env 中设置 ELEVENLABS_API_KEY")
    if not voice_id:
        raise ValueError("请在 .env 中设置 ELEVENLABS_VOICE_ID（在 ElevenLabs 后台克隆声音后获取）")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg"
    }

    data = {
        "text": text,
        "model_id": config.ELEVENLABS_MODEL,
        "voice_settings": {
            "stability": 0.5,       # 0-1，越高越稳定
            "similarity_boost": 0.8, # 0-1，越高越像原声
            "style": 0.3,           # 0-1，表现力
            "use_speaker_boost": True
        }
    }

    resp = requests.post(url, json=data, headers=headers, timeout=120)
    resp.raise_for_status()

    with open(output_path, "wb") as f:
        f.write(resp.content)

    return output_path


# ====== 兼容旧接口（科普模式用）======

async def _generate_one_shot_audio(script: dict, output_path: str):
    """科普模式：合并旁白 → TTS → 保存文件"""
    scenes = script.get("scenes", [])
    narrations = [s.get("narration", "").strip() for s in scenes if s.get("narration", "").strip()]
    full_text = "。\n".join(narrations)

    if not full_text:
        return

    console.print(f"   📝 合并旁白共 [cyan]{len(full_text)}[/cyan] 字，合成中...")

    provider = config.TTS_PROVIDER.lower()
    if provider == "elevenlabs":
        _elevenlabs_tts(full_text, output_path)
    elif provider == "doubao":
        _doubao_tts(full_text, output_path)
    else:
        await _edge_tts_async(full_text, output_path)

    console.print(f"✅ 配音完成: {output_path}")
    
    # 验证文件非空
    if os.path.exists(output_path) and os.path.getsize(output_path) < 100:
        console.print(f"[red]音频文件异常（{os.path.getsize(output_path)} 字节）[/red]")
        raise RuntimeError("TTS 生成失败，音频文件为空")


def generate_audio(script: dict) -> tuple[str, list, list]:
    """
    科普模式配音：生成完整音频 + 按字数比例分配真实时长给每个场景
    Returns: (音频路径, 空列表, 场景时长列表)
    """
    import subprocess

    provider = config.TTS_PROVIDER.lower()
    provider_name = "ElevenLabs 克隆" if provider == "elevenlabs" else "Edge TTS"
    console.print(f"\n🔊 [bold green]正在生成中文配音 ({provider_name})...[/bold green]")

    audio_dir = os.path.join(config.TEMP_DIR, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    merged_path = os.path.join(audio_dir, "full_audio.mp3")
    # 删掉可能残留的旧文件
    if os.path.exists(merged_path):
        os.remove(merged_path)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_generate_one_shot_audio(script, merged_path))
    finally:
        loop.close()

    # 获取真实音频时长
    total_duration = 0.0
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", merged_path],
            capture_output=True, text=True, timeout=10
        )
        total_duration = float(result.stdout.strip())
    except Exception:
        total_duration = 0.0

    # 按字数比例分配真实时长给每个场景
    scenes = script.get("scenes", [])
    scene_durations = []
    total_chars = sum(len(s.get("narration", "")) for s in scenes)

    if total_duration > 0 and total_chars > 0:
        for s in scenes:
            chars = len(s.get("narration", ""))
            ratio = chars / total_chars
            dur = max(3.0, round(total_duration * ratio, 1))
            s["duration"] = dur  # 更新脚本中的 duration
            scene_durations.append(dur)
        console.print(f"   真实总时长: [cyan]{total_duration:.1f}秒[/cyan]，已按字数比例分配")
    else:
        # 回退：用 LLM 估算值
        scene_durations = [s.get("duration", 5) for s in scenes]
        console.print(f"   [dim]无法获取真实时长，使用 LLM 估算值[/dim]")

    console.print("✅ [green]配音生成完成！[/green]\n")
    return merged_path, [], scene_durations


def generate_single_audio(text: str, output_path: str) -> str:
    """单段配音（兼容旧接口）"""
    return tts_generate(text, output_path)

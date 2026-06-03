"""
图片生成模块：调用多模态大模型生成场景背景图
支持 OpenAI DALL-E 和兼容 API
"""

import os
import base64
import time
import requests
from typing import Optional
from openai import OpenAI
from rich.console import Console

from config import config

console = Console()


def generate_scene_images(script: dict, progress_callback=None) -> list[str]:
    """
    为脚本中每个场景生成背景图
    progress_callback(idx, total) 可选，报告进度
    """
    if not config.IMAGE_GEN_ENABLED:
        console.print("[yellow]⚠️  图片生成已禁用，将使用纯色背景[/yellow]")
        return [""] * len(script["scenes"])

    console.print("\n🎨 [bold blue]正在为场景生成背景图...[/bold blue]")

    image_dir = config.IMAGE_OUTPUT_DIR
    os.makedirs(image_dir, exist_ok=True)

    image_paths = []
    scenes = script.get("scenes", [])

    for i, scene in enumerate(scenes):
        prompt = scene.get("image_prompt", "")
        if not prompt:
            image_paths.append("")
            continue

        console.print(f"  生成场景 {i+1}/{len(scenes)} 背景图...")
        path = _generate_single_image(prompt, i + 1, image_dir)
        image_paths.append(path)

        if progress_callback:
            progress_callback(i + 1, len(scenes), path or "")
        time.sleep(0.5)  # API 限速

    valid_count = sum(1 for p in image_paths if p)
    console.print(f"✅ [green]共生成 {valid_count}/{len(scenes)} 张背景图[/green]\n")
    return image_paths


def _generate_single_image(prompt: str, index: int, output_dir: str) -> str:
    """
    生成单张图片，根据 IMAGE_GEN_PROVIDER 配置选择引擎
    """
    provider = config.IMAGE_GEN_PROVIDER.lower()

    if provider == "doubao":
        return _generate_doubao_image(prompt, index, output_dir)
    else:
        return _generate_openai_image(prompt, index, output_dir)


def _generate_doubao_image(prompt: str, index: int, output_dir: str) -> str:
    """豆包（火山引擎）图片生成 - 速度快，中文理解好"""
    api_key = config.DOUBAO_API_KEY
    if not api_key:
        raise ValueError("请先在 .env 中设置 DOUBAO_API_KEY")

    url = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    # 豆包不需要额外后缀，prompt 可以包含中文
    payload = {
        "model": config.DOUBAO_MODEL,
        "prompt": f"{prompt}, 16:9 aspect ratio, cinematic lighting, high quality, 4K",
        "sequential_image_generation": "disabled",
        "response_format": "url",
        "size": config.DOUBAO_SIZE,
        "stream": False,
        "watermark": True
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    # 豆包返回格式: {"data": [{"url": "..."}]}
    img_url = data.get("data", [{}])[0].get("url", "")
    if not img_url:
        console.print(f"[dim]  豆包响应: {data}[/dim]")
        raise ValueError("豆包 API 未返回图片 URL")

    output_path = os.path.join(output_dir, f"scene_{index:02d}.png")
    _download_image(img_url, output_path)
    return output_path


def _generate_openai_image(prompt: str, index: int, output_dir: str) -> str:
    try:
        # 双重兜底：Key 复用 LLM 的，但 URL 默认走 OpenAI（LLM 可能用的不兼容服务）
        api_key = config.IMAGE_GEN_API_KEY or config.LLM_API_KEY
        base_url = config.IMAGE_GEN_BASE_URL or "https://api.openai.com/v1"

        if not api_key or api_key == "your-api-key-here":
            raise ValueError("请先在 .env 中设置 LLM_API_KEY")

        client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )

        # 确保 prompt 有质量描述
        enhanced_prompt = (
            f"{prompt}, high quality, cinematic lighting, "
            f"16:9 aspect ratio, photorealistic, 4K, professional photography"
        )

        response = client.images.generate(
            model=config.IMAGE_GEN_MODEL,
            prompt=enhanced_prompt,
            size=config.IMAGE_SIZE,
            quality=config.IMAGE_QUALITY,
            n=1
        )

        img_data = response.data[0]

        # gpt-image-2 返回 b64_json，dall-e-3 返回 url，兼容两种
        if hasattr(img_data, "b64_json") and img_data.b64_json:
            # base64 直接解码存图
            output_path = os.path.join(output_dir, f"scene_{index:02d}.png")
            with open(output_path, "wb") as f:
                f.write(base64.b64decode(img_data.b64_json))
            return output_path

        image_url = getattr(img_data, "url", None)
        if not image_url:
            # 打印完整响应以便调试
            console.print(f"[dim]  响应数据: {response}[/dim]")
            raise ValueError("API 未返回图片 URL 或 b64_json")

        # 下载图片
        output_path = os.path.join(output_dir, f"scene_{index:02d}.png")

        if image_url.startswith("data:"):
            # Base64 编码的图片
            _save_base64_image(image_url, output_path)
        else:
            # URL 图片
            _download_image(image_url, output_path)

        return output_path

    except Exception as e:
        console.print(f"[red]图片生成失败 (场景{index}): {e}[/red]")
        return ""


def _download_image(url: str, path: str):
    """下载图片到本地"""
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    with open(path, "wb") as f:
        f.write(resp.content)


def _save_base64_image(data_url: str, path: str):
    """保存 base64 编码的图片"""
    header, encoded = data_url.split(",", 1)
    with open(path, "wb") as f:
        f.write(base64.b64decode(encoded))

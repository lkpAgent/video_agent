from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import requests
from rich.console import Console

from config import config

from .schemas import MediaAsset

console = Console()


def analyze_media_assets(
    assets: list[MediaAsset],
    project_title: str = "",
    readme_excerpt: str = "",
    limit: int = 6,
) -> list[MediaAsset]:
    if not assets:
        return assets
    if not (config.VISION_LLM_API_KEY or "").strip():
        console.print("[yellow]   未配置 VISION_LLM_API_KEY，官方图片不会进入视频[/yellow]")
        return []

    console.print(f"[bold]   视觉理解智能体分析官方图片素材 ({min(len(assets), limit)} 张)...[/bold]")
    understood: list[MediaAsset] = []
    for idx, asset in enumerate(assets[:limit], 1):
        try:
            result = _analyze_one(asset, project_title, readme_excerpt)
            if result.get("use_in_video") is False:
                console.print(f"[dim]      [{idx}] 视觉模型判断不适合入镜，跳过: {asset.title[:24]}[/dim]")
                continue
            asset.description = result.get("description", "").strip()
            if not asset.description:
                console.print(f"[yellow]      [{idx}] 图片理解结果为空，丢弃该图[/yellow]")
                continue
            asset.tags = _as_str_list(result.get("tags"))[:8]
            asset.suggested_pages = _as_str_list(result.get("suggested_pages"))[:5]
            if not asset.title or asset.title.startswith("asset"):
                asset.title = result.get("title", "").strip() or asset.title
            console.print(f"      [{idx}] {asset.title[:24]}: {asset.description[:70]}")
            understood.append(asset)
        except Exception as exc:
            console.print(f"[yellow]      [{idx}] 图片理解失败，丢弃该图: {exc}[/yellow]")
    if not understood:
        console.print("[yellow]   没有通过视觉理解的图片，本次将生成纯文本页面[/yellow]")
    return understood


def _analyze_one(asset: MediaAsset, project_title: str, readme_excerpt: str) -> dict:
    prompt = (
        "你是技术短视频的视觉素材理解智能体。请理解这张来自官方 README/项目文档的图片，"
        "判断它是否适合放进项目介绍视频中，以及适合支撑哪类页面。\n"
        f"项目/文档标题：{project_title or '未知'}\n"
        f"图片 alt/title：{asset.alt or asset.title}\n"
        f"README 摘要：{(readme_excerpt or '')[:1200]}\n\n"
        "请只输出 JSON，不要 markdown。格式：\n"
        "{"
        "\"title\":\"给图片起一个短标题\","
        "\"description\":\"用中文说明图片主要展示了什么，以及和项目价值/功能的关系，80-160字\","
        "\"tags\":[\"功能关键词\"],"
        "\"suggested_pages\":[\"适合放入的页面主题，如产品效果/工作流/架构/使用界面/对比/结果展示\"],"
        "\"use_in_video\":true"
        "}"
    )
    image_url = _image_payload_url(asset, prefer_source_url=True)
    try:
        return _call_vision_model(image_url, prompt)
    except Exception:
        if not asset.local_path:
            raise
        fallback_url = _image_payload_url(asset, prefer_source_url=False)
        if fallback_url == image_url:
            raise
        return _call_vision_model(fallback_url, prompt)


def _call_vision_model(image_url: str, prompt: str) -> dict:
    payload = {
        "model": config.VISION_LLM_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "temperature": 0.2,
    }
    url = config.VISION_LLM_BASE_URL.rstrip("/") + "/chat/completions"
    resp = requests.post(
        url,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.VISION_LLM_API_KEY}",
        },
        json=payload,
        timeout=config.VISION_LLM_TIMEOUT,
    )
    resp.raise_for_status()
    content = (((resp.json() or {}).get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return _parse_json(content)


def _image_payload_url(asset: MediaAsset, prefer_source_url: bool = True) -> str:
    if prefer_source_url and _is_http(asset.source_url):
        return asset.source_url
    path = Path(asset.local_path)
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _is_http(value: str) -> bool:
    parsed = urlparse(value or "")
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _parse_json(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.removeprefix("json").strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start:end + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"description": text.strip()}


def _as_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []

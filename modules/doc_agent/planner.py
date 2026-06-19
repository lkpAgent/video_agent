from __future__ import annotations

import json
import re
from pathlib import Path

from openai import OpenAI
from rich.console import Console

from config import config

from .prompts import CONTENT_PLANNER_SYSTEM, CONTENT_PLANNER_USER, STYLE_INSTRUCTIONS
from .schemas import ContentBundle, PageScript, PageSpec

console = Console()

MAX_MEDIA_PAGES = 3


def generate_page_script(
    bundle: ContentBundle,
    audience: str = "beginner",
    style: str = "tech_explainer",
    visual_style: str = "bright_unified",
    duration: int = 90,
    focus: str = "",
    work_dir: str = "",
) -> PageScript:
    console.print("[bold]Step 2/5: 页面文案智能体重组内容[/bold]")
    bundle_json = json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2)
    client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
    user_prompt = CONTENT_PLANNER_USER.format(
        title=bundle.title,
        audience=audience,
        style=style,
        style_instruction=STYLE_INSTRUCTIONS.get(style, STYLE_INSTRUCTIONS["tech_explainer"]),
        duration=duration,
        focus=focus or "无",
        bundle_json=bundle_json[:30000],
    )
    response = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[
            {"role": "system", "content": CONTENT_PLANNER_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=config.LLM_MAX_TOKENS,
        temperature=0.55,
    )
    raw = (response.choices[0].message.content or "").strip()
    data = _parse_json(raw)
    script = _coerce_script(data, bundle, audience, style, visual_style, duration)
    if work_dir:
        Path(work_dir).mkdir(parents=True, exist_ok=True)
        (Path(work_dir) / "page_script.json").write_text(
            json.dumps(script.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    console.print(f"   已生成 [cyan]{len(script.pages)}[/cyan] 页页面脚本")
    return script


def _parse_json(raw: str) -> dict:
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        raw = match.group(0)
    return json.loads(raw)


def _coerce_script(
    data: dict,
    bundle: ContentBundle,
    audience: str,
    style: str,
    visual_style: str,
    target_duration: int,
) -> PageScript:
    pages_raw = data.get("pages") or []
    if not isinstance(pages_raw, list) or not pages_raw:
        pages_raw = _fallback_pages(bundle)
    pages: list[PageSpec] = []
    for idx, item in enumerate(pages_raw[:8], 1):
        page_type = str(item.get("page_type") or "concept")
        if page_type not in {
            "hero", "problem", "concept", "feature_cards", "workflow",
            "code_demo", "comparison", "metrics", "summary",
        }:
            page_type = "concept"
        bullets = item.get("bullets") or []
        if not isinstance(bullets, list):
            bullets = [str(bullets)]
        bullets = [str(b).strip()[:28] for b in bullets if str(b).strip()][:4]
        narration = str(item.get("narration") or item.get("subtitle") or item.get("title") or "").strip()
        bullets = _ensure_page_density(
            page_type=page_type,
            title=str(item.get("title") or bundle.title),
            subtitle=str(item.get("subtitle") or ""),
            narration=narration,
            bullets=bullets,
            code=str(item.get("code") or ""),
        )
        duration = float(item.get("duration") or max(6, min(16, len(narration) / 5)))
        pages.append(PageSpec(
            page_id=str(item.get("page_id") or f"p{idx}"),
            page_type=page_type,
            title=str(item.get("title") or bundle.title)[:40],
            subtitle=str(item.get("subtitle") or "")[:80],
            bullets=bullets,
            narration=narration,
            duration=duration,
            code=str(item.get("code") or "")[:1200],
            accent=str(item.get("accent") or "")[:30],
            media_asset_id=str(item.get("media_asset_id") or "").strip()[:40],
        ))
    if pages:
        pages[0].page_type = "hero"
        pages[-1].page_type = "summary"
    pages = _limit_install_pages(pages, style)
    _attach_media_assets(pages, bundle)
    total = sum(p.duration for p in pages) or 1
    if target_duration > 0:
        ratio = target_duration / total
        for page in pages:
            page.duration = round(max(5, min(24, page.duration * ratio)), 2)
    return PageScript(
        title=str(data.get("title") or bundle.title)[:80],
        audience=str(data.get("audience") or audience),
        style=str(data.get("style") or style),
        visual_style=visual_style,
        pages=pages,
    )


def _attach_media_assets(pages: list[PageSpec], bundle: ContentBundle) -> None:
    assets = [
        asset for asset in getattr(bundle, "media_assets", [])
        if asset.kind == "image" and asset.local_path and getattr(asset, "description", "").strip()
    ]
    if not assets:
        return
    by_id = {asset.asset_id: asset for asset in assets if asset.asset_id}
    used: set[str] = set()
    for page in pages:
        if len(used) >= MAX_MEDIA_PAGES:
            page.media_asset_id = ""
            continue
        if page.page_type in {"hero", "code_demo", "summary"}:
            page.media_asset_id = ""
            continue
        asset = by_id.get(page.media_asset_id)
        if asset and asset.asset_id not in used:
            _set_page_media(page, asset)
            used.add(asset.asset_id)
        elif page.media_asset_id:
            page.media_asset_id = ""

    candidates = [
        page for page in pages
        if page.page_type not in {"hero", "code_demo", "summary"} and not page.media_path
    ]
    for page in candidates:
        if len(used) >= min(MAX_MEDIA_PAGES, len(assets)):
            break
        scored = [
            (_media_relevance_score(page, asset), asset)
            for asset in assets
            if (asset.asset_id or asset.local_path) not in used
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        if not scored:
            break
        score, asset = scored[0]
        if score < 2:
            continue
        _set_page_media(page, asset)
        used.add(asset.asset_id or asset.local_path)
        if len(used) >= min(MAX_MEDIA_PAGES, len(assets)):
            break


def _set_page_media(page: PageSpec, asset) -> None:
    page.media_path = asset.local_path
    page.media_alt = asset.description or asset.alt or asset.title
    page.media_asset_id = asset.asset_id


def _media_relevance_score(page: PageSpec, asset) -> int:
    page_text = " ".join([page.title, page.subtitle, page.narration, " ".join(page.bullets)]).lower()
    asset_parts = [
        asset.title,
        asset.alt,
        asset.description,
        " ".join(getattr(asset, "tags", []) or []),
        " ".join(getattr(asset, "suggested_pages", []) or []),
    ]
    asset_text = " ".join(asset_parts).lower()
    score = 0
    for token in _keywords(page_text):
        if token and token in asset_text:
            score += 2 if len(token) >= 4 else 1
    for token in _keywords(asset_text):
        if token and token in page_text:
            score += 1
    page_type_map = {
        "workflow": ("流程", "工作流", "workflow", "pipeline"),
        "feature_cards": ("功能", "能力", "feature", "capability"),
        "comparison": ("对比", "差异", "compare"),
        "metrics": ("结果", "效果", "指标", "result"),
        "concept": ("架构", "原理", "概念", "architecture"),
        "problem": ("痛点", "问题", "场景", "problem"),
    }
    if any(key in asset_text for key in page_type_map.get(page.page_type, ())):
        score += 2
    if not getattr(asset, "description", ""):
        score -= 1
    return score


def _keywords(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}|[\u4e00-\u9fff]{2,6}", text or "")
    stop = {"这个", "一个", "可以", "通过", "如果", "不是", "页面", "视频", "项目", "用户", "适合"}
    return [w.lower() for w in words if w.lower() not in stop][:40]


def _limit_install_pages(pages: list[PageSpec], style: str) -> list[PageSpec]:
    if style not in {"github_intro", "tech_explainer"}:
        return pages
    install_seen = False
    for page in pages:
        text = " ".join([page.title, page.subtitle, page.narration, " ".join(page.bullets), page.code]).lower()
        is_install = any(k in text for k in (
            "uv ", "uvx", "pip ", "npm ", "pnpm ", "docker", "compose", "install",
            "安装", "部署", "启动", "环境变量", "clone",
        ))
        if not is_install:
            continue
        if page.page_type == "code_demo" or is_install:
            if not install_seen:
                install_seen = True
                page.title = page.title[:18] or "快速试用入口"
                if not page.bullets:
                    page.bullets = ["最短路径体验", "适合动手验证"]
            else:
                page.page_type = "concept"
                page.title = "为什么值得试"
                page.subtitle = "安装只是入口，价值在自动化能力"
                page.bullets = ["降低制作门槛", "串起完整流程", "适合二次开发"]
                page.narration = (
                    "安装命令只是入口，真正值得关注的是这个项目把原本分散的脚本、素材、配音和合成流程串成了一条自动化链路。"
                    "对创作者来说，它省的是剪辑时间；对开发者来说，它给了一个可以继续扩展的视频生成底座。"
                )
                page.code = ""
    return pages


def _ensure_page_density(
    page_type: str,
    title: str,
    subtitle: str,
    narration: str,
    bullets: list[str],
    code: str = "",
) -> list[str]:
    """避免页面只有一行内容；渲染前用旁白/副标题补足展示要点。"""
    if page_type == "hero":
        return bullets[:4]
    if len(bullets) >= 2:
        return bullets[:4]

    candidates = []
    candidates.extend(bullets)
    for text in (subtitle, narration):
        for part in re.split(r"[。！？；;，,\n]+", text or ""):
            part = part.strip()
            if 4 <= len(part) <= 28 and part not in candidates:
                candidates.append(part)
    if page_type == "code_demo" and code:
        code_hint = code.strip().splitlines()[0][:28]
        fallbacks = [
            "一键启动关键服务",
            "适合快速部署验证",
            "后续可接入配置管理",
        ]
        if code_hint and code_hint not in candidates:
            candidates.insert(0, code_hint)
        for item in fallbacks:
            if len(candidates) >= 3:
                break
            if item not in candidates:
                candidates.append(item)
    generic = [
        title[:18] or "核心观点",
        "先抓住关键动作",
        "再理解适用场景",
        "最后落到实践路径",
    ]
    for item in generic:
        if len(candidates) >= 3:
            break
        if item and item not in candidates:
            candidates.append(item)
    return candidates[:4]


def _fallback_pages(bundle: ContentBundle) -> list[dict]:
    text = bundle.summary or (bundle.raw_materials[0].content if bundle.raw_materials else "")
    sentences = [s.strip() for s in re.split(r"[。！？.!?\n]+", text) if len(s.strip()) > 6]
    bullets = sentences[:4] or [bundle.title]
    pages = [
        {"page_type": "hero", "title": bundle.title, "subtitle": "一页页看懂核心内容", "narration": bundle.summary[:90]},
        {"page_type": "feature_cards", "title": "核心信息", "bullets": bullets[:4], "narration": "这份资料的重点，可以先抓住这几个关键词。"},
        {"page_type": "summary", "title": "一句话总结", "bullets": bullets[:3], "narration": (sentences[0] if sentences else bundle.title)},
    ]
    if bundle.code_examples:
        pages.insert(2, {"page_type": "code_demo", "title": "最小示例", "code": bundle.code_examples[0], "narration": "如果看代码，最关键的是理解它如何被调用。"})
    return pages

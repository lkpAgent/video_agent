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
MIN_MEDIA_RELEVANCE_SCORE = 6


def generate_page_script(
    bundle: ContentBundle,
    audience: str = "beginner",
    style: str = "news_analysis",
    visual_style: str = "dark_premium",
    duration: int = 60,
    focus: str = "",
    work_dir: str = "",
) -> PageScript:
    style = _normalize_content_style(style)
    console.print("[bold]Step 2/5: 页面文案智能体重组内容[/bold]")
    bundle_json = json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2)
    client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
    user_prompt = _render_content_planner_prompt(
        title=bundle.title,
        audience=audience,
        style=style,
        style_instruction=STYLE_INSTRUCTIONS.get(style, STYLE_INSTRUCTIONS["news_analysis"]),
        duration=str(duration),
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


def _normalize_content_style(style: str) -> str:
    normalized = (style or "").strip()
    aliases = {
        "tech_explainer": "news_analysis",
        "product_doc": "news_analysis",
        "paper_brief": "paper_analysis",
        "paper": "paper_analysis",
        "news": "news_analysis",
        "article": "news_analysis",
    }
    return aliases.get(normalized, normalized or "news_analysis")


def _parse_json(raw: str) -> dict:
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        raw = match.group(0)
    return json.loads(raw)


def _render_content_planner_prompt(**values: str) -> str:
    prompt = CONTENT_PLANNER_USER
    for key, value in values.items():
        prompt = prompt.replace("{" + key + "}", str(value))
    return prompt


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
        raise ValueError("LLM 未生成可用页面脚本，请调整输入内容后重试")
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
        narration = _compact_narration(str(item.get("narration") or item.get("subtitle") or item.get("title") or "").strip())
        if not _has_enough_page_content(page_type, str(item.get("subtitle") or ""), narration, bullets, str(item.get("code") or "")):
            continue
        duration = float(item.get("duration") or max(6, min(16, len(narration) / 5)))
        pages.append(PageSpec(
            page_id=str(item.get("page_id") or f"p{idx}"),
            page_type=page_type,
            title=_compact_title(str(item.get("title") or bundle.title)),
            subtitle=str(item.get("subtitle") or "")[:80],
            bullets=bullets,
            narration=narration,
            duration=duration,
            code=str(item.get("code") or "")[:1200],
            accent=str(item.get("accent") or "")[:30],
            media_asset_id=str(item.get("media_asset_id") or "").strip()[:40],
            media_usage_reason=str(item.get("media_usage_reason") or "").strip()[:120],
        ))
    if pages:
        pages[0].page_type = "hero"
        pages[-1].page_type = "summary"
        _polish_pages_for_style(pages, style)
    if not pages:
        raise ValueError("LLM 生成的页面缺少可信内容，请调整输入内容后重试")
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


def _polish_pages_for_style(pages: list[PageSpec], style: str) -> None:
    if not pages:
        return
    final_page = pages[-1]
    if style == "news_analysis":
        _neutralize_summary_page(final_page, "关键观察")
    elif style == "paper_analysis":
        _neutralize_summary_page(final_page, "核心结论")


def _neutralize_summary_page(page: PageSpec, fallback_title: str) -> None:
    if _looks_like_forced_engagement(page.title):
        page.title = fallback_title
    page.bullets = [
        _neutralize_engagement_text(text)
        for text in page.bullets
        if not _is_pure_engagement_line(text)
    ][:4]
    page.narration = _neutralize_engagement_text(page.narration)


def _looks_like_forced_engagement(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    return any(pattern in compact for pattern in (
        "适合谁收藏", "适合谁关注", "收藏关注", "值得收藏", "建议收藏",
    ))


def _is_pure_engagement_line(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    return compact in {"收藏关注", "建议收藏", "值得收藏", "适合收藏", "持续关注"}


def _neutralize_engagement_text(text: str) -> str:
    result = text or ""
    result = re.sub(r"适合谁(?:收藏关注|收藏|关注)[？?，,：:\s]*", "", result)
    replacements = {
        "收藏关注": "继续观察",
        "建议收藏": "可以留意",
        "值得收藏": "值得了解",
    }
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result.strip()


def _compact_title(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return "核心观点"
    weighted = sum(1.0 if ord(ch) < 128 else 1.8 for ch in text)
    if len(text) <= 28 and weighted <= 46:
        return text
    limit = 32
    trimmed = text[:limit].rstrip(" ，,。；;：:")
    match = re.search(r"[A-Za-z0-9_+.-]+$", trimmed)
    if match and len(text) > limit and re.match(r"[A-Za-z0-9_+.-]", text[limit:limit + 1] or ""):
        trimmed = trimmed[:match.start()].rstrip(" ，,。；;：:")
    return trimmed or text[:limit].rstrip()


def _compact_narration(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _attach_media_assets(pages: list[PageSpec], bundle: ContentBundle) -> None:
    assets = [
        asset for asset in getattr(bundle, "media_assets", [])
        if asset.kind == "image" and asset.local_path and getattr(asset, "description", "").strip()
    ]
    assets = [asset for asset in assets if not _is_non_content_media_asset(_asset_text(asset))]
    if not assets:
        return
    console.print(f"[dim]   可用图片素材: {len(assets)} 张，开始匹配页面[/dim]")
    by_id = {asset.asset_id: asset for asset in assets if asset.asset_id}
    used: set[str] = set()
    rejected_pages: set[str] = set()
    for page in pages:
        if len(used) >= MAX_MEDIA_PAGES:
            page.media_asset_id = ""
            continue
        if page.page_type in {"hero", "code_demo", "summary"}:
            page.media_asset_id = ""
            continue
        asset = by_id.get(page.media_asset_id)
        if asset and asset.asset_id not in used and _is_media_relevant(page, asset):
            _set_page_media(page, asset)
            used.add(asset.asset_id)
            console.print(f"[dim]   图片 {asset.asset_id} 已按 LLM 选择挂到页面: {page.title}[/dim]")
        elif page.media_asset_id:
            rejected_pages.add(page.page_id)
            page.media_usage_reason = ""
            page.media_asset_id = ""

    candidates = [
        page for page in pages
        if page.page_type not in {"hero", "code_demo", "summary"}
        and not page.media_path
        and page.page_id not in rejected_pages
        and not getattr(page, "_skip_auto_media", False)
    ]
    for page in candidates:
        if len(used) >= min(MAX_MEDIA_PAGES, len(assets)):
            break
        scored = [
            (_media_relevance_score(page, asset), asset)
            for asset in assets
            if (asset.asset_id or asset.local_path) not in used
            and not _is_non_content_media_asset(_asset_text(asset))
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        if not scored:
            break
        score, asset = scored[0]
        if score < MIN_MEDIA_RELEVANCE_SCORE:
            continue
        _set_page_media(page, asset)
        used.add(asset.asset_id or asset.local_path)
        console.print(f"[dim]   图片 {asset.asset_id} 已自动挂到页面: {page.title} score={score}[/dim]")
        if len(used) >= min(MAX_MEDIA_PAGES, len(assets)):
            break
    _attach_fallback_media(pages, assets, used, rejected_pages)


def _attach_fallback_media(
    pages: list[PageSpec],
    assets: list,
    used: set[str],
    rejected_pages: set[str],
) -> None:
    if used or not assets:
        return
    candidates = [
        page for page in pages
        if page.page_type not in {"hero", "code_demo", "summary"}
        and not page.media_path
        and page.page_id not in rejected_pages
    ]
    if not candidates:
        return
    for page in candidates:
        if len(used) >= min(MAX_MEDIA_PAGES, len(assets), len(candidates)):
            break
        scored = [
            (_media_relevance_score(page, asset), asset)
            for asset in assets
            if (asset.asset_id or asset.local_path) not in used
            and not _is_non_content_media_asset(_asset_text(asset))
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        if not scored:
            break
        score, asset = scored[0]
        if score < MIN_MEDIA_RELEVANCE_SCORE:
            continue
        _set_page_media(page, asset)
        used.add(asset.asset_id or asset.local_path)
        console.print(f"[dim]   图片 {asset.asset_id} 已作为相关正文配图挂到页面: {page.title} score={score}[/dim]")


def _set_page_media(page: PageSpec, asset) -> None:
    page.media_path = asset.local_path
    page.media_alt = asset.description or asset.alt or asset.title
    page.media_asset_id = asset.asset_id


def _is_media_relevant(page: PageSpec, asset) -> bool:
    return _media_relevance_score(page, asset) >= MIN_MEDIA_RELEVANCE_SCORE


def _media_relevance_score(page: PageSpec, asset) -> int:
    core_page_text = " ".join([
        page.title,
        page.subtitle,
        page.narration,
        " ".join(page.bullets),
    ]).lower()
    usage_reason = getattr(page, "media_usage_reason", "").lower()
    page_text = " ".join([core_page_text, usage_reason]).lower()
    asset_text = _asset_text(asset)
    if _is_non_content_media_asset(asset_text):
        return -100
    score = 0
    for token in _keywords(page_text):
        if token and token in asset_text:
            score += 2 if len(token) >= 4 else 1
    for token in _keywords(asset_text):
        if token and token in page_text:
            score += 1
    if page.media_asset_id and not getattr(page, "media_usage_reason", "").strip():
        score -= 3
    if _is_generic_design_asset(asset_text) and not _page_is_visual_output_page(core_page_text, page.page_type):
        score -= 12
    if usage_reason and _is_weak_media_reason(usage_reason, core_page_text):
        score -= 8
    if _is_news_scene_asset(asset_text) and _page_can_use_news_scene(core_page_text, page.page_type):
        score += 5
    page_type_map = {
        "workflow": ("流程", "工作流", "落地", "应用", "workflow", "pipeline"),
        "feature_cards": ("功能", "能力", "feature", "capability"),
        "comparison": ("对比", "差异", "compare"),
        "metrics": ("结果", "效果", "指标", "数字", "数据", "result"),
        "concept": ("架构", "原理", "概念", "现场", "赛道", "大赛", "赛事", "技术", "architecture"),
        "problem": ("痛点", "问题", "场景", "背景", "事实", "problem"),
    }
    if any(key in asset_text for key in page_type_map.get(page.page_type, ())):
        score += 2
    if not getattr(asset, "description", ""):
        score -= 1
    return score


def _is_news_scene_asset(asset_text: str) -> bool:
    scene_hints = (
        "现场", "实拍", "活动", "会议", "开幕", "启幕", "决赛", "大赛", "赛事",
        "参会", "嘉宾", "评审", "主持人", "大屏", "雄安", "新闻", "发布",
    )
    return any(hint in asset_text for hint in scene_hints)


def _page_can_use_news_scene(page_text: str, page_type: str) -> bool:
    if page_type in {"hero", "code_demo", "summary"}:
        return False
    if page_type in {"problem", "concept", "feature_cards", "workflow", "metrics"}:
        return True
    page_hints = (
        "发生", "背景", "现场", "活动", "大赛", "赛事", "决赛", "启幕", "开幕",
        "赛道", "数字", "成果", "技术", "医疗", "健康", "县医院", "落地", "信号",
    )
    return any(hint in page_text for hint in page_hints)


def _asset_text(asset) -> str:
    asset_parts = [
        getattr(asset, "title", ""),
        getattr(asset, "alt", ""),
        getattr(asset, "description", ""),
        " ".join(getattr(asset, "tags", []) or []),
        " ".join(getattr(asset, "suggested_pages", []) or []),
        getattr(asset, "source_url", ""),
    ]
    return " ".join(str(part) for part in asset_parts if part).lower()


def _is_non_content_media_asset(asset_text: str) -> bool:
    if not asset_text:
        return True
    hard_reject_hints = (
        "头像", "作者头像", "媒体头像", "账号头像", "官方品牌头像", "profile photo", "author avatar",
    )
    if any(hint in asset_text for hint in hard_reject_hints):
        return True
    non_content_hints = (
        "logo", "logotype", "标识", "品牌标识",
        "官方品牌", "水印", "二维码", "qr code", "广告", "赞助", "下载app", "app icon",
        "publisher", "brand mark", "media logo",
    )
    if any(hint in asset_text for hint in non_content_hints):
        strong_content_hints = (
            "现场", "赛场", "决赛现场", "产品界面", "截图", "架构", "流程", "示意图",
            "实验", "结果", "图表", "设备", "技术应用", "demo", "screenshot", "diagram",
        )
        return not any(hint in asset_text for hint in strong_content_hints)
    return False


def _is_generic_design_asset(asset_text: str) -> bool:
    generic_hints = (
        "设计样例", "设计模板", "视觉展示", "视觉输出", "排版设计", "海报设计",
        "风格化", "frame system", "design template", "poster", "visual",
    )
    return any(hint in asset_text for hint in generic_hints)


def _page_is_visual_output_page(page_text: str, page_type: str) -> bool:
    visual_hints = (
        "界面", "效果", "样例", "模板", "设计规范", "frame.md", "成片",
        "产品效果", "输出质量", "风格模板", "排版模板", "设计系统",
    )
    if page_type in {"metrics", "workflow"}:
        return True
    return any(hint in page_text for hint in visual_hints)


def _is_weak_media_reason(reason: str, core_page_text: str) -> bool:
    weak_patterns = (
        "视觉质量", "设计样例", "设计效果", "视觉效果", "好看", "美观",
        "展示项目能力", "体现项目能力", "体现视觉", "展示设计",
    )
    if not any(pattern in reason for pattern in weak_patterns):
        return False
    strong_page_hints = (
        "frame.md", "设计规范", "设计系统", "模板", "界面", "工作流",
        "产品效果", "效果展示", "成片", "输出质量",
    )
    return not any(hint in core_page_text for hint in strong_page_hints)


def _keywords(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}|[\u4e00-\u9fff]{2,6}", text or "")
    stop = {"这个", "一个", "可以", "通过", "如果", "不是", "页面", "视频", "项目", "用户", "适合"}
    return [w.lower() for w in words if w.lower() not in stop][:40]


def _has_enough_page_content(
    page_type: str,
    subtitle: str,
    narration: str,
    bullets: list[str],
    code: str = "",
) -> bool:
    if page_type == "hero":
        return bool(narration or subtitle or bullets)
    if page_type == "code_demo":
        return bool(code and (narration or len(bullets) >= 1))
    return bool(narration and len(bullets) >= 1)

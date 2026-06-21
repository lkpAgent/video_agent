from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

from config import config

from .schemas import PageScript, PageSpec


def build_document_html(script: PageScript, work_dir: str) -> str:
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    font_face_css, font_family = _font_css(work)
    total_duration = sum(page.duration for page in script.pages)
    visual_style = _normalize_visual_style(getattr(script, "visual_style", "bright_unified"))
    pages_html = []
    timeline_parts = []
    audio_tags = []
    acc = 0.0
    media_count = 0
    for idx, page in enumerate(script.pages, 1):
        _prepare_page_media(page, work)
        media_order = 0
        if getattr(page, "_media_src", ""):
            media_count += 1
            media_order = media_count
        pages_html.append(_render_page(page, idx, len(script.pages), acc))
        timeline_parts.append(_timeline_js(page, idx, acc, media_order))
        audio_path = page_to_audio_path(page)
        if audio_path:
            src = Path(audio_path)
            rel = Path("audio") / src.name
            audio_tags.append(
                f'<audio id="page-audio-{idx}" data-start="{acc:.2f}" '
                f'data-duration="{page.duration:.2f}" data-track-index="{100 + idx}" '
                f'src="./{rel.as_posix()}"></audio>'
            )
        acc += page.duration

    html_text = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>
{font_face_css}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{
  width:{config.VIDEO_WIDTH}px;height:{config.VIDEO_HEIGHT}px;overflow:hidden;
  font-family:{font_family};background:#edf1f6;color:#0f172a;
}}
#composition{{
  position:relative;width:100%;height:100%;overflow:hidden;
  background:
    radial-gradient(circle at 18% 8%,rgba(255,255,255,.9),transparent 28%),
    linear-gradient(135deg,#f5f7fa 0%,#e4e8f0 100%);
}}
#composition::before{{
  content:"";position:absolute;right:-145px;top:-95px;width:430px;height:430px;
  border:1px solid rgba(15,23,42,.06);transform:rotate(24deg);opacity:.9;
}}
.page{{
  position:absolute;inset:0;padding:78px 72px 78px;overflow:hidden;
  display:grid;grid-template-rows:auto minmax(0,1fr) auto;gap:30px;
}}
.topline{{display:flex;align-items:center;justify-content:space-between;gap:24px;z-index:3}}
.eyebrow{{font-size:18px;letter-spacing:6px;color:#64748b;font-weight:800;text-transform:uppercase}}
.counter{{font-size:24px;color:#64748b;letter-spacing:1px}}.counter b{{font-size:30px;color:#0f172a;font-weight:950}}
.title{{font-size:66px;line-height:1.1;font-weight:950;letter-spacing:0;max-width:940px;text-wrap:balance;overflow-wrap:anywhere;word-break:break-word;line-break:loose;color:#0f172a}}
.title-long{{font-size:54px;line-height:1.14;max-width:950px}}
.title-compact{{font-size:46px;line-height:1.18;max-width:952px}}
.title-mini{{font-size:40px;line-height:1.2;max-width:952px}}
.title-xl{{font-size:76px;line-height:1.06;max-width:940px}}
.subtitle{{display:inline-flex;align-items:center;gap:18px;font-size:31px;line-height:1.38;color:#64748b;max-width:920px;margin-top:18px;font-weight:600}}
.accent{{display:inline-flex;margin-top:16px;padding:6px 14px;border-radius:8px;background:#0f172a;color:#fff;font-size:25px;font-weight:900;box-shadow:none}}
.content{{position:relative;z-index:3;display:flex;flex-direction:column;justify-content:center;gap:32px;padding-top:0;padding-bottom:10px}}
.cards{{display:grid;grid-template-columns:1fr;gap:42px;max-width:930px;margin-top:2px}}
.card{{display:grid;grid-template-columns:78px 1fr;align-items:center;gap:24px;min-height:150px;padding:34px 46px;background:rgba(255,255,255,.82);border:1px solid rgba(255,255,255,.7);border-radius:34px;box-shadow:0 12px 44px rgba(15,23,42,.05);backdrop-filter:blur(14px)}}
.card:first-child{{border-color:rgba(37,99,235,.32);box-shadow:0 24px 64px rgba(37,99,235,.13);transform:translateY(-3px)}}
.card::before{{content:attr(data-index);width:58px;height:58px;border-radius:50%;display:grid;place-items:center;background:rgba(37,99,235,.13);color:#2563eb;font-size:26px;font-weight:950}}
.card b{{display:block;font-size:36px;line-height:1.28;font-weight:900;color:#0f172a}}
.workflow{{display:grid;grid-template-columns:1fr;gap:42px;max-width:930px;margin-top:2px}}
.step{{display:grid;grid-template-columns:78px 1fr;align-items:center;gap:24px;min-height:150px;padding:34px 46px;background:rgba(255,255,255,.82);border:1px solid rgba(255,255,255,.7);border-radius:34px;box-shadow:0 12px 44px rgba(15,23,42,.05);backdrop-filter:blur(14px)}}
.step:first-child{{border-color:rgba(37,99,235,.32);box-shadow:0 24px 64px rgba(37,99,235,.13);transform:translateY(-3px)}}
.step-num{{width:58px;height:58px;border-radius:50%;display:grid;place-items:center;background:rgba(37,99,235,.13);color:#2563eb;font-size:25px;font-weight:950}}
.step-text{{font-size:36px;line-height:1.28;font-weight:900;color:#0f172a}}
.split{{display:grid;grid-template-columns:1fr 1fr;gap:28px;max-width:930px}}
.split-panel{{padding:34px;background:rgba(255,255,255,.82);border:1px solid rgba(255,255,255,.7);border-radius:30px;min-height:300px;box-shadow:0 12px 44px rgba(15,23,42,.05)}}
.split-panel h3{{font-size:32px;margin-bottom:22px;color:#0f172a}}.split-panel li{{font-size:28px;line-height:1.55;margin-left:1em;color:#334155;font-weight:700}}
pre{{max-width:930px;max-height:570px;overflow:hidden;padding:34px;background:#0f172a;border:1px solid rgba(15,23,42,.2);border-radius:26px;box-shadow:0 24px 70px rgba(15,23,42,.16)}}
code{{font-family:Consolas,"Cascadia Code",monospace;font-size:25px;line-height:1.55;color:#bfdbfe;white-space:pre-wrap}}
.hero-panel{{margin-top:26px;padding:38px 42px;background:rgba(255,255,255,.82);border:1px solid rgba(255,255,255,.86);border-radius:34px;box-shadow:0 28px 78px rgba(15,23,42,.10);max-width:930px}}
.hero-kicker{{font-size:28px;line-height:1.55;color:#263447;font-weight:760;text-align:left}}
.keyword-row{{display:flex;flex-wrap:wrap;gap:16px;margin-top:26px}}
.keyword{{padding:12px 18px;border-radius:999px;background:rgba(37,99,235,.1);color:#2563eb;font-size:24px;font-weight:900}}
.layout-hero .content{{justify-content:center;align-items:center;text-align:center;padding-bottom:0;gap:30px}}
.layout-hero .subtitle{{justify-content:center;text-align:center}}
.layout-hero .hero-panel{{width:100%;max-width:930px;text-align:left}}
.layout-hero .title{{font-size:72px;line-height:1.1;max-width:940px}}
.layout-hero .title-long{{font-size:54px;line-height:1.15}}
.layout-hero .title-compact{{font-size:46px;line-height:1.18}}
.layout-hero .title-mini{{font-size:39px;line-height:1.2}}
.layout-hero .title-xl{{font-size:80px;line-height:1.04}}
.layout-hero .footer{{display:flex}}
.layout-hero .caption{{font-size:27px;line-height:1.43;padding:28px 38px 24px;max-height:240px}}
.layout-bento .cards{{grid-template-columns:1fr 1fr;gap:28px;max-width:930px}}
.layout-bento .card{{grid-template-columns:1fr;align-items:start;gap:18px;min-height:210px;padding:36px;border-radius:34px}}
.layout-bento .card::before{{content:attr(data-index);width:54px;height:54px}}
.layout-bento .card b{{font-size:32px}}
.layout-timeline .cards{{gap:30px}}
.layout-timeline .card{{min-height:128px;border-radius:28px}}
.layout-emphasis .cards{{grid-template-columns:1fr;gap:24px}}
.layout-emphasis .card{{grid-template-columns:64px 1fr;min-height:112px;border-radius:26px;padding:28px 34px}}
.layout-emphasis .card b{{font-size:32px}}
.layout-code .content{{gap:30px}}
.code-layout{{display:grid;grid-template-columns:1fr;gap:24px;max-width:930px}}
.code-layout pre{{max-height:260px;margin:0}}
.code-notes{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
.code-note{{padding:24px 28px;background:rgba(255,255,255,.78);border:1px solid rgba(255,255,255,.72);border-radius:26px;box-shadow:0 12px 34px rgba(15,23,42,.05);font-size:27px;line-height:1.35;font-weight:850;color:#0f172a}}
.media-layout{{display:flex;flex-direction:column;gap:24px;align-items:stretch;max-width:930px}}
.layout-media .content{{justify-content:flex-start;gap:24px;padding-bottom:0}}
.layout-media .title{{font-size:56px;line-height:1.12}}
.layout-media .title-long{{font-size:48px;line-height:1.15}}
.layout-media .title-compact{{font-size:42px;line-height:1.18}}
.media-frame{{position:relative;min-height:560px;padding:20px;background:rgba(255,255,255,.86);border:1px solid rgba(255,255,255,.82);border-radius:34px;box-shadow:0 32px 82px rgba(15,23,42,.13);overflow:hidden;isolation:isolate;transform-style:preserve-3d;perspective:1200px;will-change:transform,opacity,clip-path,filter}}
.media-frame::before{{content:"";position:absolute;inset:-18%;background:radial-gradient(circle at 28% 24%,rgba(96,165,250,.22),transparent 34%),radial-gradient(circle at 76% 70%,rgba(14,165,233,.16),transparent 36%);z-index:0;pointer-events:none}}
.media-frame::after{{content:"";position:absolute;inset:auto 10% -20px;height:44px;border-radius:50%;background:rgba(15,23,42,.18);filter:blur(24px);z-index:-1}}
.media-backdrop-img{{position:absolute;inset:-8%;width:116%;height:116%;object-fit:cover;border-radius:28px;filter:blur(32px) saturate(1.18) brightness(.72);opacity:.42;transform-origin:center;z-index:0}}
.media-main{{position:relative;z-index:1;width:100%;height:100%;min-height:520px;object-fit:contain;border-radius:22px;display:block;background:#fff;transform-origin:center;will-change:transform}}
.media-glare{{position:absolute;top:-24%;bottom:-24%;left:-54%;width:32%;z-index:3;background:linear-gradient(90deg,transparent,rgba(255,255,255,.58),transparent);filter:blur(2px);transform:skewX(-14deg);opacity:0;pointer-events:none}}
.media-points{{display:grid;grid-template-columns:1fr;gap:14px;align-content:stretch}}
.media-point{{display:grid;grid-template-columns:44px 1fr;align-items:center;gap:14px;min-height:78px;padding:18px 22px;background:rgba(255,255,255,.78);border:1px solid rgba(255,255,255,.72);border-radius:22px;box-shadow:0 12px 34px rgba(15,23,42,.05);font-size:24px;line-height:1.28;font-weight:900;color:#0f172a}}
.media-point::before{{content:attr(data-index);width:48px;height:48px;border-radius:50%;display:grid;place-items:center;background:rgba(37,99,235,.13);color:#2563eb;font-size:22px;font-weight:950}}
.layout-summary .content{{justify-content:center;padding-bottom:80px}}
.layout-summary .cards{{grid-template-columns:1fr;gap:26px}}
.layout-summary .card{{min-height:124px;border-radius:30px;background:#0f172a;color:#fff}}
.layout-summary .card::before{{background:rgba(255,255,255,.14);color:#93c5fd}}
.layout-summary .card b{{color:#fff;font-size:34px}}
.footer{{z-index:3;display:flex;flex-direction:column;align-items:stretch;justify-content:flex-end;margin-top:auto;min-height:0;padding-bottom:42px}}
.caption{{padding:28px 40px 24px;background:rgba(255,255,255,.76);border:1px solid rgba(15,23,42,.08);border-radius:28px;box-shadow:0 18px 46px rgba(15,23,42,.08),inset 0 2px 4px rgba(255,255,255,.75);font-size:28px;line-height:1.43;font-weight:760;color:#263447;max-height:250px;overflow:visible;text-align:left}}
.caption-long{{font-size:25px;line-height:1.4}}
.caption-xl{{font-size:22px;line-height:1.36}}
.progress{{width:92px;height:7px;background:rgba(15,23,42,.28);border-radius:999px;overflow:hidden;margin:18px auto 0}}.progress span{{display:block;height:100%;background:rgba(15,23,42,.32);width:100%}}
.page-hero,.page-problem,.page-concept,.page-feature_cards,.page-workflow,.page-code_demo,.page-comparison,.page-metrics,.page-summary{{background:transparent}}
.theme-dark-premium{{
  background:#050505;color:#e2e8f0;
}}
.theme-dark-premium #composition{{
  background:
    radial-gradient(circle at 20% 0%,rgba(56,189,248,.12),transparent 30%),
    linear-gradient(135deg,#0f172a 0%,#020617 100%);
}}
.theme-dark-premium #composition::before{{
  border-color:rgba(255,255,255,.05);
}}
.theme-dark-premium .eyebrow{{color:#38bdf8;opacity:.92}}
.theme-dark-premium .counter{{color:#94a3b8}}.theme-dark-premium .counter b{{color:#38bdf8}}
.theme-dark-premium .title{{color:#f8fafc}}
.theme-dark-premium .subtitle{{color:#94a3b8}}
.theme-dark-premium .accent{{background:rgba(56,189,248,.15);color:#38bdf8;border:1px solid rgba(56,189,248,.3)}}
.theme-dark-premium .card,.theme-dark-premium .step,.theme-dark-premium .split-panel,.theme-dark-premium .hero-panel,.theme-dark-premium .code-note{{
  background:rgba(30,41,59,.62);border-color:rgba(255,255,255,.08);box-shadow:0 16px 48px rgba(0,0,0,.22);
}}
.theme-dark-premium .media-frame,.theme-dark-premium .media-point{{
  background:rgba(30,41,59,.62);border-color:rgba(255,255,255,.08);box-shadow:0 16px 48px rgba(0,0,0,.22);color:#f8fafc;
}}
.theme-dark-premium .media-main{{background:#0f172a}}
.theme-dark-premium .media-frame::before{{background:linear-gradient(115deg,transparent 36%,rgba(56,189,248,.16) 47%,transparent 58%)}}
.theme-dark-premium .media-frame::after{{background:rgba(56,189,248,.20)}}
.theme-dark-premium .media-point::before{{background:rgba(56,189,248,.15);color:#38bdf8;border:1px solid rgba(56,189,248,.22)}}
.theme-dark-premium .card:first-child,.theme-dark-premium .step:first-child{{
  background:rgba(30,41,59,.82);border-color:rgba(56,189,248,.42);box-shadow:0 24px 64px rgba(56,189,248,.14);
}}
.theme-dark-premium .card::before,.theme-dark-premium .step-num{{
  background:rgba(56,189,248,.15);color:#38bdf8;border:1px solid rgba(56,189,248,.22);
}}
.theme-dark-premium .card b,.theme-dark-premium .step-text,.theme-dark-premium .split-panel h3,.theme-dark-premium .code-note{{color:#f8fafc}}
.theme-dark-premium .split-panel li,.theme-dark-premium .hero-kicker{{color:#cbd5e1}}
.theme-dark-premium .keyword{{background:rgba(56,189,248,.12);color:#38bdf8;border:1px solid rgba(56,189,248,.16)}}
.theme-dark-premium pre{{background:#020617;border-color:rgba(56,189,248,.16);box-shadow:0 24px 70px rgba(0,0,0,.36)}}
.theme-dark-premium code{{color:#7dd3fc}}
.theme-dark-premium .layout-summary .card{{background:rgba(30,41,59,.9)}}
.theme-dark-premium .caption{{
  background:rgba(2,6,23,.66);border-color:rgba(148,163,184,.13);box-shadow:0 18px 48px rgba(0,0,0,.28),inset 0 1px 0 rgba(255,255,255,.04);
  color:#e2e8f0;
}}
.theme-dark-premium .progress,.theme-dark-premium .progress span{{background:rgba(148,163,184,.25)}}
.theme-dark-premium #progress{{background:#38bdf8!important;box-shadow:0 0 20px rgba(56,189,248,.35)}}
#progress{{
  position:absolute;left:0;bottom:0;height:4px;background:#111827;
  z-index:20;animation:progressAnim {total_duration:.2f}s linear forwards;
}}
@keyframes progressAnim{{from{{width:0}}to{{width:100%}}}}
</style>
</head>
<body class="theme-{visual_style}">
<div id="composition" data-composition-id="doc-agent" data-start="0" data-duration="{total_duration:.2f}" data-width="{config.VIDEO_WIDTH}" data-height="{config.VIDEO_HEIGHT}">
  <div id="progress"></div>
  {''.join(pages_html)}
  {''.join(audio_tags)}
</div>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{paused:true}});
gsap.set(".page", {{autoAlpha:0}});
{''.join(timeline_parts)}
window.__timelines["doc-agent"] = tl;
window.__READY = false;
window.__stopTimeline = () => {{ tl.pause(0); window.__READY = false; }};
window.__renderAt = (seconds) => {{ tl.pause(seconds); return seconds; }};
window.__renderScene = (idx) => {{
  const pages = Array.from(document.querySelectorAll(".page"));
  gsap.set(pages, {{autoAlpha:0}});
  if (pages[idx]) gsap.set(pages[idx], {{autoAlpha:1}});
  return idx;
}};
window.addEventListener("DOMContentLoaded", () => {{
  const timer = setInterval(() => {{
    if (window.__READY) {{
      clearInterval(timer);
      tl.play(0);
    }}
  }}, 100);
  setTimeout(() => {{
    if (!window.__READY) {{
      window.__READY = true;
      tl.play(0);
    }}
  }}, 3000);
}});
</script>
</body>
</html>"""
    path = work / "index.html"
    path.write_text(html_text, encoding="utf-8")
    return str(path)


def page_to_audio_path(page: PageSpec) -> str:
    return getattr(page, "audio_path", "")


def _prepare_page_media(page: PageSpec, work_dir: Path) -> None:
    media_path = getattr(page, "media_path", "") or ""
    if not media_path:
        return
    src = Path(media_path)
    if not src.exists():
        page.media_path = ""
        return
    asset_dir = work_dir / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    target = asset_dir / src.name
    if not target.exists() or target.stat().st_size != src.stat().st_size:
        shutil.copy2(src, target)
    setattr(page, "_media_src", f"./assets/{target.name}")


def _normalize_visual_style(value: str) -> str:
    value = (value or "bright_unified").strip().lower().replace("_", "-")
    if value in {"dark", "dark-premium", "premium-dark"}:
        return "dark-premium"
    return "bright-unified"


def _font_css(work_dir: Path) -> tuple[str, str]:
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
    ]
    font_path = next((p for p in candidates if p.exists()), None)
    if not font_path:
        return "", '"Microsoft YaHei","Noto Sans CJK SC",sans-serif'
    target = work_dir / f"doc-agent-cjk{font_path.suffix.lower()}"
    if not target.exists() or target.stat().st_size != font_path.stat().st_size:
        shutil.copy2(font_path, target)
    return f'@font-face{{font-family:"DocAgent CJK";src:url("./{target.name}");font-display:block;}}', '"DocAgent CJK",sans-serif'


def _render_page(page: PageSpec, idx: int, total: int, start: float) -> str:
    layout = _choose_layout(page, idx, total)
    title = _e(page.title)
    title_class = _title_class(page.title)
    subtitle = _e(page.subtitle)
    bullets = [_e(b) for b in page.bullets]
    accent = _e(page.accent)
    body = _body(page, bullets, layout, idx)
    meta_html = ""
    if subtitle or accent:
        meta_parts = []
        if accent:
            meta_parts.append(f'<span class="accent">{accent}</span>')
        if subtitle:
            meta_parts.append(f"<span>{subtitle}</span>")
        meta_html = '<div class="subtitle">' + "".join(meta_parts) + "</div>"
    caption = _e(page.narration)
    caption_class = _caption_class(page.narration)
    return f"""
  <section id="page-{idx}" class="page page-{_e(page.page_type)} layout-{layout}" data-start="{start:.2f}" data-duration="{page.duration:.2f}">
    <div class="topline"><div class="eyebrow">{_e(page.page_type.replace("_", " "))}</div><div class="counter"><b>{idx:02d}</b> / {total:02d}</div></div>
    <div class="content">
      <div>
        <h1 class="title {title_class}">{title}</h1>
        {meta_html}
      </div>
      {body}
    </div>
    <div class="footer"><div class="caption {caption_class}">{caption}</div><div class="progress"><span></span></div></div>
  </section>"""


def _choose_layout(page: PageSpec, idx: int, total: int) -> str:
    if page.page_type == "hero" or idx == 1:
        return "hero"
    if page.page_type == "code_demo":
        return "code"
    if getattr(page, "_media_src", ""):
        return "media"
    if page.page_type == "workflow":
        return "timeline"
    if page.page_type == "comparison":
        return "comparison"
    if page.page_type == "summary" or idx == total:
        return "summary"
    if len(page.bullets) >= 4:
        return "bento"
    return "emphasis" if idx % 2 == 0 else "timeline"


def _title_class(title: str) -> str:
    text = (title or "").strip()
    length = len(text)
    weighted = sum(1.0 if ord(ch) < 128 else 1.8 for ch in text)
    if weighted <= 18 and length <= 10:
        return "title-xl"
    if weighted >= 46 or length >= 28:
        return "title-mini"
    if weighted >= 36 or length >= 22:
        return "title-compact"
    if weighted >= 24 or length >= 13:
        return "title-long"
    return ""


def _caption_class(text: str) -> str:
    length = len((text or "").strip())
    if length >= 130:
        return "caption-xl"
    if length >= 85:
        return "caption-long"
    return ""


def _media_motion(idx: int) -> str:
    return ("wipe", "tilt", "stack", "spotlight")[(idx - 1) % 4]


def _body(page: PageSpec, bullets: list[str], layout: str, idx: int) -> str:
    if layout == "hero":
        keywords = "".join(f'<span class="keyword">{b}</span>' for b in bullets[:4])
        intro = _e(page.subtitle or page.narration or page.title)
        return f'<div class="hero-panel"><div class="hero-kicker">{intro}</div><div class="keyword-row">{keywords}</div></div>'
    if page.page_type == "code_demo" and page.code:
        notes = "".join(f'<div class="code-note">{b}</div>' for b in bullets[:4])
        return f'<div class="code-layout"><pre><code>{_e(page.code)}</code></pre><div class="code-notes">{notes}</div></div>'
    if layout == "media":
        image_src = _e(getattr(page, "_media_src", ""))
        image_alt = _e(getattr(page, "media_alt", "") or page.title)
        motion = _media_motion(idx)
        points = "".join(
            f'<div class="media-point" data-index="{i:02d}">{b}</div>'
            for i, b in enumerate((bullets or [page.subtitle])[:4], 1)
        )
        return (
            f'<div class="media-layout media-motion-{motion}">'
            f'<div class="media-frame">'
            f'<img class="media-backdrop-img" src="{image_src}" alt="">'
            f'<img class="media-main" src="{image_src}" alt="{image_alt}">'
            f'<div class="media-glare"></div>'
            f'</div>'
            f'<div class="media-points">{points}</div>'
            '</div>'
        )
    if page.page_type == "workflow":
        items = "".join(
            f'<div class="step"><div class="step-num">{i:02d}</div><div class="step-text">{b}</div></div>'
            for i, b in enumerate(bullets or [page.subtitle], 1)
        )
        return f'<div class="workflow">{items}</div>'
    if page.page_type == "comparison":
        left = bullets[:2] or ["传统方式", "信息分散"]
        right = bullets[2:] or ["重构页面", "更适合讲解"]
        return (
            '<div class="split">'
            f'<div class="split-panel"><h3>原始信息</h3><ul>{"".join(f"<li>{b}</li>" for b in left)}</ul></div>'
            f'<div class="split-panel"><h3>视频表达</h3><ul>{"".join(f"<li>{b}</li>" for b in right)}</ul></div>'
            '</div>'
        )
    cards = "".join(f'<div class="card" data-index="{i:02d}"><b>{b}</b></div>' for i, b in enumerate(bullets, 1))
    return f'<div class="cards">{cards}</div>' if cards else ""


def _timeline_js(page: PageSpec, idx: int, start: float, media_order: int = 0) -> str:
    selector = f"#page-{idx}"
    duration = max(1.0, page.duration - 0.2)
    media_js = ""
    if getattr(page, "_media_src", ""):
        move_duration = max(1.4, page.duration - 1.0)
        motion = _media_motion(idx)
        if motion == "wipe":
            image_from = "{clipPath:'inset(0 100% 0 0)',x:-120,scale:.94,filter:'blur(6px)'}"
            image_to = "{clipPath:'inset(0 0% 0 0)',x:0,scale:1,filter:'blur(0px)',duration:1.02,ease:'expo.out'}"
        elif motion == "tilt":
            image_from = "{clipPath:'inset(10% 10% 10% 10%)',rotationY:-52,rotationZ:-5,scale:.82,x:-80,filter:'blur(3px)'}"
            image_to = "{clipPath:'inset(0% 0% 0% 0%)',rotationY:0,rotationZ:-1,scale:1,x:0,filter:'blur(0px)',duration:.92,ease:'back.out(1.22)'}"
        elif motion == "stack":
            image_from = "{clipPath:'polygon(0 0,100% 12%,88% 100%,8% 88%)',rotation:8,scale:.72,y:100,filter:'blur(4px)'}"
            image_to = "{clipPath:'polygon(0 0,100% 0,100% 100%,0 100%)',rotation:-1,scale:1,y:0,filter:'blur(0px)',duration:.86,ease:'back.out(1.32)'}"
        else:
            image_from = "{clipPath:'circle(0% at 50% 50%)',scale:1.34,filter:'blur(12px)'}"
            image_to = "{clipPath:'circle(76% at 50% 50%)',scale:1,filter:'blur(0px)',duration:.9,ease:'expo.out'}"
        if media_order == 1:
            main_motion_js = f"""
tl.set("{selector} .media-main", {{transformOrigin:"50% 50%"}}, {start + .70:.2f});
tl.fromTo("{selector} .media-main", {{scale:1.01,x:0,y:0}}, {{scale:1.62,x:"18%",y:0,duration:.62,ease:"power2.inOut"}}, {start + .92:.2f});
tl.to("{selector} .media-main", {{scale:1.62,x:"-18%",y:0,duration:1.18,ease:"power1.inOut"}}, {start + 1.54:.2f});
tl.to("{selector} .media-main", {{scale:1,x:0,y:0,duration:.62,ease:"power2.out"}}, {start + 2.74:.2f});
"""
        elif media_order == 2:
            main_motion_js = f"""
tl.set("{selector} .media-main", {{transformOrigin:"50% 46%"}}, {start + .70:.2f});
tl.fromTo("{selector} .media-main", {{scale:.96,y:34,rotationZ:-1.2,filter:"brightness(.96)"}}, {{scale:1.02,y:0,rotationZ:0,filter:"brightness(1)",duration:.78,ease:"back.out(1.16)"}}, {start + .92:.2f});
tl.to("{selector} .media-main", {{scale:1.055,y:-10,rotationZ:.35,duration:{move_duration:.2f},ease:"none"}}, {start + 1.70:.2f});
"""
        else:
            main_motion_js = f"""
tl.fromTo("{selector} .media-main", {{scale:.98,x:-18,y:18,rotationZ:.8}}, {{scale:1.04,x:10,y:-8,rotationZ:0,duration:{move_duration:.2f},ease:"power1.out"}}, {start + .72:.2f});
"""
        media_js = f"""
tl.fromTo("{selector} .media-frame", {image_from}, {image_to}, {start + .58:.2f});
tl.fromTo("{selector} .media-backdrop-img", {{scale:1.06,x:0,y:0}}, {{scale:1.20,x:-22,y:16,duration:{move_duration:.2f},ease:"none"}}, {start + .62:.2f});
tl.fromTo("{selector} .media-glare", {{opacity:0,x:"-70%"}}, {{opacity:.48,x:"105%",duration:.88,ease:"power2.out"}}, {start + 1.04:.2f});
{main_motion_js}
tl.fromTo("{selector} .media-point", {{opacity:0,y:28,scale:.96}}, {{opacity:1,y:0,scale:1,duration:.45,stagger:.09,ease:"back.out(1.18)"}}, {start + 1.42:.2f});
"""
    return f"""
tl.fromTo("{selector}", {{autoAlpha:0}}, {{autoAlpha:1,duration:.25}}, {start:.2f});
tl.fromTo("{selector} .eyebrow", {{opacity:0,y:-18}}, {{opacity:1,y:0,duration:.42,ease:"power3.out"}}, {start + .08:.2f});
tl.fromTo("{selector} .title", {{opacity:0,y:58,filter:"blur(8px)"}}, {{opacity:1,y:0,filter:"blur(0px)",duration:.72,ease:"expo.out"}}, {start + .12:.2f});
tl.fromTo("{selector} .subtitle,{selector} .accent", {{opacity:0,y:24}}, {{opacity:1,y:0,duration:.55,stagger:.08,ease:"power3.out"}}, {start + .45:.2f});
tl.fromTo("{selector} .card,{selector} .step,{selector} .split-panel,{selector} pre,{selector} .hero-panel,{selector} .code-note", {{opacity:0,y:38,scale:.97}}, {{opacity:1,y:0,scale:1,duration:.55,stagger:.12,ease:"power3.out"}}, {start + .7:.2f});
{media_js}
tl.to("{selector}", {{autoAlpha:0,duration:.22}}, {start + duration:.2f});
"""


def _e(value: object) -> str:
    return html.escape(str(value or ""), quote=True)

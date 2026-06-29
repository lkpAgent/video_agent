from __future__ import annotations

import os
import re
import hashlib
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from rich.console import Console

from config import config
from modules.search import HEADERS, search_to_context, search_web

from .schemas import ContentBundle, ContentItem, MediaAsset
from .vision import analyze_media_assets

console = Console()

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MIN_URL_TEXT_CHARS = 350
MIN_BROWSER_TEXT_CHARS = 250
SKIP_IMAGE_HINTS = (
    "shields.io",
    "badge",
    "badgen.net",
    "github.com/actions",
    "github/workflows",
    "coveralls.io",
    "codecov.io",
)


def collect_content(
    topic: str = "",
    source: str = "",
    max_chars: int = 12000,
    request_headers: str | dict[str, str] = "",
) -> ContentBundle:
    source = (source or "").strip()
    topic = (topic or "").strip()
    parsed_headers = _parse_request_headers(request_headers)
    if source:
        if _is_github_repo_url(source):
            return _load_github_repo(source, max_chars)
        if _is_url(source):
            return _load_url(source, max_chars, parsed_headers)
        return _load_local_file(source, max_chars)
    if not topic:
        raise ValueError("doc-agent 需要 --topic 或 --source")
    return _search_topic(topic, max_chars)


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _is_github_repo_url(value: str) -> bool:
    parsed = urlparse(value)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    return parsed.netloc.lower() == "github.com" and len(parts) >= 2


def _clean_text(text: str, max_chars: int) -> str:
    text = re.sub(r"\r\n?", "\n", text or "")
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if len(line) <= 2:
            continue
        lines.append(line)
    return "\n".join(lines)[:max_chars]


def _extract_code_blocks(text: str, limit: int = 3) -> list[str]:
    blocks = re.findall(r"```(?:[a-zA-Z0-9_-]+)?\n([\s\S]*?)```", text or "")
    return [block.strip()[:900] for block in blocks if block.strip()][:limit]


def _load_local_file(path_value: str, max_chars: int) -> ContentBundle:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        raise FileNotFoundError(f"文档不存在: {path}")
    suffix = path.suffix.lower()
    if suffix in (".md", ".txt", ".py", ".js", ".ts", ".tsx", ".html", ".htm"):
        text = path.read_text(encoding="utf-8", errors="replace")
    elif suffix == ".pdf":
        text = _read_pdf(path)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    cleaned = _clean_text(text, max_chars)
    return ContentBundle(
        source_type=f"local_{suffix.lstrip('.') or 'text'}",
        title=path.stem,
        summary=cleaned[:700],
        raw_materials=[ContentItem(title=path.name, content=cleaned, source_url=str(path))],
        code_examples=_extract_code_blocks(text),
    )


def _read_pdf(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("读取 PDF 需要安装 pdfplumber") from exc
    parts = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages[:30]:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _load_url(url: str, max_chars: int, request_headers: dict[str, str] | None = None) -> ContentBundle:
    resp_text = ""
    title = url
    text = ""
    request_headers = request_headers or {}
    headers = {**HEADERS, **request_headers}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        resp_text = resp.text
        title, text = _extract_html_title_text(resp_text, url, max_chars)
    except Exception as exc:
        console.print(f"[yellow]普通请求读取失败，尝试用浏览器渲染读取页面: {exc}[/yellow]")

    if not _has_enough_content(text):
        console.print("[yellow]普通请求未拿到足够正文，尝试用浏览器渲染读取页面...[/yellow]")
        browser_result = _load_url_with_browser(url, max_chars, request_headers)
        if browser_result:
            title, text, rendered_html = browser_result
            media_assets = _extract_and_analyze_url_media(rendered_html, url, title, text, request_headers)
            return ContentBundle(
                source_type="url_browser",
                title=title[:80],
                summary=text[:700],
                raw_materials=[ContentItem(title=title, content=text, source_url=url)],
                links=[url],
                code_examples=_extract_code_blocks(rendered_html),
                media_assets=media_assets,
            )
    media_assets = _extract_and_analyze_url_media(resp_text, url, title, text, request_headers)
    return ContentBundle(
        source_type="url",
        title=title[:80],
        summary=text[:700],
        raw_materials=[ContentItem(title=title, content=text, source_url=url)],
        links=[url],
        code_examples=_extract_code_blocks(resp_text),
        media_assets=media_assets,
    )


def _extract_html_title_text(html: str, url: str, max_chars: int) -> tuple[str, str]:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()
    title = (soup.title.get_text(strip=True) if soup.title else url).strip() or url
    text = _clean_text(soup.get_text(separator="\n", strip=True), max_chars)
    return title, text


def _extract_and_analyze_url_media(
    html: str,
    page_url: str,
    title: str,
    text: str,
    request_headers: dict[str, str] | None = None,
) -> list[MediaAsset]:
    image_refs = _extract_html_images(html, page_url)
    if image_refs:
        console.print(f"[dim]   提取到正文候选图片 {len(image_refs)} 张[/dim]")
    media_assets = _download_url_media_assets(image_refs, page_url, title, request_headers=request_headers)
    if media_assets:
        console.print(f"[dim]   成功下载正文图片 {len(media_assets)} 张[/dim]")
    if not media_assets:
        return []
    return analyze_media_assets(media_assets, project_title=title, readme_excerpt=text[:2000])


def _extract_html_images(html: str, page_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    images: list[dict[str, str]] = []

    roots = []
    for selector in (
        "article", "main", "[role='main']",
        ".article-content", ".article-content-rich", ".syl-article-base",
        ".content", ".post-content", ".entry-content",
    ):
        roots.extend(soup.select(selector))
    search_roots = roots or [soup]

    for root in search_roots:
        for tag in root.find_all(["img", "source"]):
            if tag.name == "source" and not tag.find_parent("picture"):
                continue
            if _is_video_related_tag(tag):
                continue
            if _is_non_article_image_tag(tag):
                continue
            _append_html_image_tag(images, tag, page_url)

    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in images:
        key = item["url"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _append_html_image_tag(images: list[dict[str, str]], tag, page_url: str) -> None:
    alt = tag.get("alt") or tag.get("title") or tag.get("aria-label") or ""
    for attr in (
        "src", "data-src", "data-original", "data-url", "data-lazy-src",
        "data-img-url", "data-srcset", "srcset",
    ):
        value = tag.get(attr) or ""
        for candidate in _image_candidates_from_attr(value):
            _append_html_image_ref(images, candidate, alt, page_url)


def _is_video_related_tag(tag) -> bool:
    for node in [tag, *list(tag.parents)]:
        name = getattr(node, "name", "") or ""
        if name in {"video", "audio"}:
            return True
        attrs = getattr(node, "attrs", {}) or {}
        text = " ".join(
            str(value)
            for key, value in attrs.items()
            if key in {"class", "id", "data-log", "data-testid", "aria-label"}
        ).lower()
        if any(hint in text for hint in (
            "video", "player", "xgplayer", "tt-video", "video-player",
            "poster", "cover", "vod", "播放",
        )):
            return True
    return False


def _is_non_article_image_tag(tag) -> bool:
    text_parts = [
        tag.get("alt") or "",
        tag.get("title") or "",
        tag.get("aria-label") or "",
    ]
    for node in [tag, *list(tag.parents)[:4]]:
        attrs = getattr(node, "attrs", {}) or {}
        for key, value in attrs.items():
            if key in {"class", "id", "data-log", "data-testid", "aria-label"}:
                if isinstance(value, (list, tuple)):
                    text_parts.extend(str(item) for item in value)
                else:
                    text_parts.append(str(value))
    text = " ".join(text_parts).lower()
    return any(hint in text for hint in (
        "avatar", "author", "profile", "headimg", "user-info", "publisher", "source-logo",
        "logo", "watermark", "qrcode", "qr-code", "download-app", "media-info",
        "头像", "作者", "用户信息", "媒体信息", "来源", "标识", "水印", "二维码",
    ))


def _image_candidates_from_attr(value: str) -> list[str]:
    if not value:
        return []
    candidates = []
    for part in str(value).split(","):
        candidate = part.strip().split(" ")[0].strip()
        if candidate:
            candidates.append(candidate)
    return candidates


def _append_html_image_ref(images: list[dict[str, str]], src: str, alt: str, base_url: str) -> None:
    src = (src or "").strip().strip("'\"")
    if not src or src.startswith(("#", "data:", "blob:")):
        return
    url = urljoin(base_url, src if not src.startswith("//") else f"https:{src}")
    if not _looks_like_candidate_image(url):
        return
    images.append({"url": url, "alt": (alt or "").strip()[:80]})


def _looks_like_candidate_image(url: str) -> bool:
    lowered = url.lower()
    if any(hint in lowered for hint in SKIP_IMAGE_HINTS) or _looks_like_video_url(lowered):
        return False
    parsed = urlparse(lowered)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    suffix = Path(parsed.path).suffix
    if suffix in IMAGE_EXTENSIONS:
        return True
    image_host_hints = ("image", "img", "pstatp", "byteimg", "toutiaoimg", "ttcdn")
    image_path_hints = ("/img/", "/image/", "/tos-cn-", "/large/", "/origin/", "/pgc-image/")
    return any(hint in parsed.netloc for hint in image_host_hints) or any(hint in parsed.path for hint in image_path_hints)


def _looks_like_video_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    query = {key.lower(): [v.lower() for v in values] for key, values in parse_qs(parsed.query).items()}
    suffix = Path(path).suffix
    video_suffixes = {".mp4", ".webm", ".mov", ".m4v", ".m3u8", ".ts"}
    if suffix in video_suffixes:
        return True
    if any(hint in host for hint in ("vod", "video", "toutiaovod")):
        return True
    if any(hint in path for hint in ("/video/", "/tos-cn-ve-", "/video/tos/")):
        return True
    mime_values = query.get("mime_type", []) + query.get("mime", [])
    return any("video" in value or "mp4" in value for value in mime_values)


def _is_image_response(content_type: str, content: bytes) -> bool:
    content_type = (content_type or "").lower()
    if content_type.startswith("video/") or "video" in content_type:
        return False
    if content_type.startswith("image/"):
        return True
    signatures = (
        b"\x89PNG\r\n\x1a\n",
        b"\xff\xd8\xff",
        b"GIF87a",
        b"GIF89a",
        b"RIFF",
    )
    if content.startswith(b"RIFF"):
        return content[8:12] == b"WEBP"
    return any(content.startswith(sig) for sig in signatures if sig != b"RIFF")


def _has_enough_content(text: str) -> bool:
    cleaned = _clean_text(text, 5000)
    if len(cleaned) < MIN_URL_TEXT_CHARS:
        return False
    lines = [line for line in cleaned.splitlines() if len(line) >= 12]
    return len(lines) >= 4


def _load_url_with_browser(
    url: str,
    max_chars: int,
    request_headers: dict[str, str] | None = None,
) -> tuple[str, str, str] | None:
    engine = getattr(config, "DOC_AGENT_BROWSER_ENGINE", "selenium").strip().lower()
    if engine in {"", "none", "off", "false"}:
        console.print("[dim]浏览器正文采集已关闭，跳过浏览器兜底[/dim]")
        return None

    if engine == "playwright":
        result = _load_url_with_playwright(url, max_chars, request_headers)
        if result and _has_enough_browser_content(result[1]):
            return result
        if not getattr(config, "RECORD_FALLBACK_TO_SELENIUM", True):
            return result
        console.print("[yellow]Playwright 未拿到足够正文，回退 Firefox + Selenium...[/yellow]")

    result = _load_url_with_selenium(url, max_chars, request_headers)
    if result and _has_enough_browser_content(result[1]):
        return result

    return result


def _browser_profile_dir() -> str:
    return os.getenv(
        "DOC_AGENT_BROWSER_PROFILE_DIR",
        str(Path(config.TEMP_DIR) / "doc_agent_browser_profile"),
    )


def _has_enough_browser_content(text: str) -> bool:
    return len(_clean_text(text, 5000)) >= MIN_BROWSER_TEXT_CHARS


def _load_url_with_playwright(
    url: str,
    max_chars: int,
    request_headers: dict[str, str] | None = None,
) -> tuple[str, str, str] | None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        console.print(f"[dim]Playwright 不可用，跳过浏览器兜底: {exc}[/dim]")
        return None

    timeout_ms = int(os.getenv("DOC_AGENT_BROWSER_TIMEOUT_MS", "60000"))
    wait_ms = int(os.getenv("DOC_AGENT_BROWSER_WAIT_MS", "3000"))
    user_data_dir = _browser_profile_dir()
    Path(user_data_dir).mkdir(parents=True, exist_ok=True)
    browser_headers, user_agent, cookie_header = _prepare_browser_headers(request_headers or {})
    context = None

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=True,
                viewport={"width": 1365, "height": 900},
                locale="zh-CN",
                user_agent=user_agent,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            if browser_headers:
                context.set_extra_http_headers(browser_headers)
            if cookie_header:
                context.add_cookies(_cookies_from_header(cookie_header, url))
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 15000))
            except Exception:
                pass
            page.wait_for_timeout(wait_ms)

            html = page.content()
            title, text = _extract_rendered_page_text(page, html, url, max_chars)
            context.close()
            context = None
            return title, text, html
    except Exception as exc:
        console.print(f"[dim]Playwright 浏览器读取失败: {exc}[/dim]")
        return None
    finally:
        if context:
            context.close()


def _extract_rendered_page_text(page, html: str, url: str, max_chars: int) -> tuple[str, str]:
    try:
        data = page.evaluate(
            """
            () => {
              const title = document.querySelector('h1')?.innerText || document.title || location.href;
              const selectors = [
                'article', 'main', '[role="main"]',
                '.article-content', '.article-content-rich', '.syl-article-base',
                '.content', '.post-content', '.entry-content', '.markdown-body'
              ];
              const values = [];
              for (const selector of selectors) {
                for (const el of document.querySelectorAll(selector)) {
                  const text = (el.innerText || '').trim();
                  if (text) values.push(text);
                }
              }
              const paragraphs = Array.from(document.querySelectorAll('h1,h2,h3,p,li,blockquote,pre'))
                .map(el => (el.innerText || '').trim())
                .filter(Boolean)
                .join('\\n');
              values.push(paragraphs);
              values.push((document.body?.innerText || '').trim());
              values.sort((a, b) => b.length - a.length);
              return { title, text: values[0] || '' };
            }
            """
        )
        title = (data.get("title") or url).strip()
        text = _clean_text(data.get("text") or "", max_chars)
        if text:
            return title, text
    except Exception:
        pass
    return _extract_html_title_text(html, url, max_chars)


def _load_url_with_selenium(
    url: str,
    max_chars: int,
    request_headers: dict[str, str] | None = None,
) -> tuple[str, str, str] | None:
    try:
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service
        from modules.selenium_recorder import _find_firefox_binary, _find_geckodriver
    except Exception as exc:
        console.print(f"[dim]Selenium 不可用，跳过浏览器兜底: {exc}[/dim]")
        return None

    driver = None
    firefox_binary = ""
    geckodriver = ""
    try:
        opts = Options()
        opts.add_argument("-headless")
        firefox_binary = _find_firefox_binary()
        if firefox_binary:
            opts.binary_location = firefox_binary
        user_agent = _header_value(request_headers or {}, "user-agent")
        if user_agent:
            opts.set_preference("general.useragent.override", user_agent)
        geckodriver = _find_geckodriver()
        service = Service(executable_path=geckodriver) if geckodriver else Service()
        driver = webdriver.Firefox(options=opts, service=service)
        driver.set_page_load_timeout(60)
        driver.get(url)
        cookie_header = _header_value(request_headers or {}, "cookie")
        if cookie_header:
            for cookie in _selenium_cookies_from_header(cookie_header):
                try:
                    driver.add_cookie(cookie)
                except Exception:
                    continue
            driver.get(url)
        time.sleep(float(os.getenv("DOC_AGENT_BROWSER_WAIT_SECONDS", "4")))
        html = driver.page_source
        title = driver.title or url
        text = driver.execute_script(
            """
            const values = [];
            for (const selector of ['article','main','[role="main"]','.article-content','.content']) {
              for (const el of document.querySelectorAll(selector)) {
                const text = (el.innerText || '').trim();
                if (text) values.push(text);
              }
            }
            values.push((document.body && document.body.innerText || '').trim());
            values.sort((a, b) => b.length - a.length);
            return values[0] || '';
            """
        )
        return title, _clean_text(text or "", max_chars), html
    except Exception as exc:
        console.print(
            f"[dim]Selenium 浏览器读取失败: {exc} "
            f"Firefox={firefox_binary or '未找到'}; geckodriver={geckodriver or '未找到'}[/dim]"
        )
        return None
    finally:
        if driver:
            driver.quit()


def _parse_request_headers(raw: str | dict[str, str] | None) -> dict[str, str]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {
            str(key).strip(): str(value).strip()
            for key, value in raw.items()
            if str(key).strip() and value is not None
        }

    headers: dict[str, str] = {}
    for line in str(raw).replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith(("curl ", "-h ", "--header ")):
            match = re.search(r"['\"]([^'\"]+:[^'\"]*)['\"]", line)
            if match:
                line = match.group(1).strip()
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        name = name.strip()
        value = value.strip()
        if not name or name.startswith(":"):
            continue
        headers[name] = value
    return headers


def _header_value(headers: dict[str, str], name: str) -> str:
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return ""


def _prepare_browser_headers(headers: dict[str, str]) -> tuple[dict[str, str], str | None, str]:
    blocked = {
        "host",
        "connection",
        "content-length",
        "accept-encoding",
        "cookie",
        "user-agent",
    }
    browser_headers = {
        key: value
        for key, value in headers.items()
        if key.lower() not in blocked and not key.startswith(":")
    }
    user_agent = _header_value(headers, "user-agent") or None
    cookie_header = _header_value(headers, "cookie")
    return browser_headers, user_agent, cookie_header


def _cookies_from_header(cookie_header: str, url: str) -> list[dict[str, Any]]:
    origin = _url_origin(url)
    return [
        {"name": name, "value": value, "url": origin}
        for name, value in _cookie_pairs(cookie_header)
    ]


def _selenium_cookies_from_header(cookie_header: str) -> list[dict[str, str]]:
    return [{"name": name, "value": value} for name, value in _cookie_pairs(cookie_header)]


def _cookie_pairs(cookie_header: str) -> list[tuple[str, str]]:
    pairs = []
    for item in (cookie_header or "").split(";"):
        if "=" not in item:
            continue
        name, value = item.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name:
            pairs.append((name, value))
    return pairs


def _url_origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _extract_markdown_images(markdown: str, readme_url: str) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    for alt, src in re.findall(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", markdown or ""):
        _append_image_ref(images, alt, src, readme_url)

    soup = BeautifulSoup(markdown or "", "html.parser")
    for tag in soup.find_all("img"):
        src = tag.get("src") or ""
        alt = tag.get("alt") or tag.get("title") or ""
        _append_image_ref(images, alt, src, readme_url)

    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in images:
        key = item["url"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _append_image_ref(images: list[dict[str, str]], alt: str, src: str, base_url: str) -> None:
    src = (src or "").strip().strip("'\"")
    if not src or src.startswith("#"):
        return
    url = _resolve_github_image_url(src, base_url)
    if not _looks_like_useful_image(url):
        return
    images.append({"url": url, "alt": (alt or "").strip()[:80]})


def _resolve_github_image_url(src: str, base_url: str) -> str:
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("http://") or src.startswith("https://"):
        return _github_blob_to_raw(src)
    return urljoin(base_url, src)


def _github_blob_to_raw(url: str) -> str:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if parsed.netloc.lower() == "github.com" and len(parts) >= 5 and parts[2] == "blob":
        owner, repo, _, branch = parts[:4]
        rest = "/".join(parts[4:])
        return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{rest}"
    return url


def _looks_like_useful_image(url: str) -> bool:
    lowered = url.lower()
    if any(hint in lowered for hint in SKIP_IMAGE_HINTS):
        return False
    parsed = urlparse(lowered)
    suffix = Path(parsed.path).suffix
    return suffix in IMAGE_EXTENSIONS


def _download_media_assets(
    image_refs: list[dict[str, str]],
    owner: str,
    repo: str,
    limit: int = 6,
) -> list[MediaAsset]:
    if not image_refs:
        return []
    target_dir = Path(config.TEMP_DIR) / "doc_agent_assets" / _safe_slug(f"{owner}-{repo}")
    target_dir.mkdir(parents=True, exist_ok=True)
    assets: list[MediaAsset] = []
    for ref in image_refs:
        if len(assets) >= limit:
            break
        url = ref["url"]
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
        except Exception:
            continue
        content_type = (resp.headers.get("content-type") or "").lower()
        if not _is_image_response(content_type, resp.content):
            continue
        if len(resp.content) < 1024:
            continue
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix not in IMAGE_EXTENSIONS:
            suffix = ".png"
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
        stem = _safe_slug(ref.get("alt") or Path(urlparse(url).path).stem or "image")[:32]
        path = target_dir / f"{len(assets) + 1:02d}-{stem}-{digest}{suffix}"
        path.write_bytes(resp.content)
        asset_id = f"img_{len(assets) + 1:02d}"
        assets.append(MediaAsset(
            kind="image",
            title=ref.get("alt") or path.stem,
            alt=ref.get("alt") or "",
            asset_id=asset_id,
            source_url=url,
            local_path=str(path),
            is_official=True,
        ))
    return assets


def _download_url_media_assets(
    image_refs: list[dict[str, str]],
    page_url: str,
    title: str,
    limit: int = 6,
    request_headers: dict[str, str] | None = None,
) -> list[MediaAsset]:
    if not image_refs:
        return []
    parsed = urlparse(page_url)
    slug_source = f"{parsed.netloc}-{title or parsed.path}"
    target_dir = Path(config.TEMP_DIR) / "doc_agent_assets" / _safe_slug(f"url-{slug_source}")[:80]
    target_dir.mkdir(parents=True, exist_ok=True)
    assets: list[MediaAsset] = []
    blocked_headers = {"host", "content-length", "connection", "accept-encoding"}
    reusable_headers = {
        key: value
        for key, value in (request_headers or {}).items()
        if key.lower() not in blocked_headers and not key.startswith(":")
    }
    headers = {**HEADERS, **reusable_headers, "Referer": page_url}
    for ref in image_refs:
        if len(assets) >= limit:
            break
        url = ref["url"]
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
        except Exception:
            continue
        content_type = (resp.headers.get("content-type") or "").lower()
        if not _is_image_response(content_type, resp.content):
            continue
        if len(resp.content) < 2048:
            continue
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix not in IMAGE_EXTENSIONS:
            if "webp" in content_type:
                suffix = ".webp"
            elif "jpeg" in content_type or "jpg" in content_type:
                suffix = ".jpg"
            elif "gif" in content_type:
                suffix = ".gif"
            else:
                suffix = ".png"
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
        stem = _safe_slug(ref.get("alt") or Path(urlparse(url).path).stem or "article-image")[:32]
        path = target_dir / f"{len(assets) + 1:02d}-{stem}-{digest}{suffix}"
        path.write_bytes(resp.content)
        asset_id = f"img_{len(assets) + 1:02d}"
        assets.append(MediaAsset(
            kind="image",
            title=ref.get("alt") or path.stem,
            alt=ref.get("alt") or "",
            asset_id=asset_id,
            source_url=url,
            local_path=str(path),
            is_official=True,
        ))
    return assets


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value or "").strip("-._")
    return slug or "asset"


def _load_github_repo(url: str, max_chars: int) -> ContentBundle:
    parsed = urlparse(url)
    owner, repo = parsed.path.strip("/").split("/")[:2]
    repo = repo.removesuffix(".git")
    raw_urls = [
        f"https://raw.githubusercontent.com/{owner}/{repo}/main/README.md",
        f"https://raw.githubusercontent.com/{owner}/{repo}/master/README.md",
    ]
    readme = ""
    readme_url = ""
    for candidate in raw_urls:
        try:
            resp = requests.get(candidate, headers=HEADERS, timeout=15)
            if resp.status_code == 200 and resp.text.strip():
                readme = resp.text
                readme_url = candidate
                break
        except Exception:
            continue
    if not readme:
        bundle = _load_url(url, max_chars)
        bundle.source_type = "github"
        return bundle
    cleaned = _clean_text(readme, max_chars)
    title = repo
    first_heading = re.search(r"^#\s+(.+)$", readme, re.MULTILINE)
    if first_heading:
        heading = first_heading.group(1).strip()
        if not _looks_like_setup_title(heading):
            title = heading
    image_refs = _extract_markdown_images(readme, readme_url)
    media_assets = _download_media_assets(image_refs, owner, repo)
    media_assets = analyze_media_assets(media_assets, project_title=title, readme_excerpt=cleaned[:2000])
    return ContentBundle(
        source_type="github",
        title=title,
        summary=cleaned[:700],
        raw_materials=[ContentItem(title=f"{owner}/{repo} README", content=cleaned, source_url=readme_url)],
        code_examples=_extract_code_blocks(readme),
        links=[url, readme_url],
        media_assets=media_assets,
    )


def _looks_like_setup_title(value: str) -> bool:
    lowered = (value or "").lower()
    return any(hint in lowered for hint in (
        "install", "installation", "quick start", "getting started", "setup",
        "docker", "pip", "uv ", "uv运行", "安装", "运行", "部署", "启动",
    ))


def _search_topic(topic: str, max_chars: int) -> ContentBundle:
    results = search_web(topic, max_results=6, fetch_content=True)
    context = _clean_text(search_to_context(results), max_chars)
    return ContentBundle(
        source_type="topic_search",
        title=topic,
        summary=context[:700],
        raw_materials=[
            ContentItem(title=r.title, content=(r.content or r.snippet)[:2500], source_url=r.url)
            for r in results
        ],
        links=[r.url for r in results if r.url],
    )

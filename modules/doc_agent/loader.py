from __future__ import annotations

import os
import re
import hashlib
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from rich.console import Console

from config import config
from modules.search import HEADERS, search_to_context, search_web

from .schemas import ContentBundle, ContentItem, MediaAsset
from .vision import analyze_media_assets

console = Console()

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
SKIP_IMAGE_HINTS = (
    "shields.io",
    "badge",
    "badgen.net",
    "github.com/actions",
    "github/workflows",
    "coveralls.io",
    "codecov.io",
)


def collect_content(topic: str = "", source: str = "", max_chars: int = 12000) -> ContentBundle:
    source = (source or "").strip()
    topic = (topic or "").strip()
    if source:
        if _is_github_repo_url(source):
            return _load_github_repo(source, max_chars)
        if _is_url(source):
            return _load_url(source, max_chars)
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


def _load_url(url: str, max_chars: int) -> ContentBundle:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    title = (soup.title.get_text(strip=True) if soup.title else url).strip()
    text = _clean_text(soup.get_text(separator="\n", strip=True), max_chars)
    return ContentBundle(
        source_type="url",
        title=title[:80],
        summary=text[:700],
        raw_materials=[ContentItem(title=title, content=text, source_url=url)],
        links=[url],
        code_examples=_extract_code_blocks(resp.text),
    )


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
        if "image" not in content_type and not _looks_like_useful_image(url):
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

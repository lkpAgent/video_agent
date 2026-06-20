from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from rich.console import Console

from config import config
from modules.gallery_video import (
    _check_hyperframes_available,
    _get_hyperframes_cli,
    _mux_gallery_audio,
    _resolve_rendered_video_path,
    record_gallery_video,
)
from modules.tts import tts_generate

from .html_builder import build_document_html
from .schemas import PageScript

console = Console()

DOC_AGENT_TTS_SPEED = float(os.getenv("DOC_AGENT_TTS_SPEED", "1.5"))


def generate_page_audio(script: PageScript, work_dir: str, voice_id: str = "", voice_type: int = 1) -> PageScript:
    console.print("[bold]Step 4/5: 免费 TTS 逐页生成旁白[/bold]")
    audio_dir = Path(work_dir) / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    for idx, page in enumerate(script.pages, 1):
        text = page.narration.strip() or page.title
        audio_path = audio_dir / f"page_{idx:02d}.mp3"
        tts_generate(text, str(audio_path), voice_id, voice_type)
        audio_path = _speed_up_audio(audio_path, DOC_AGENT_TTS_SPEED)
        duration = _get_audio_duration(str(audio_path))
        if duration > 0:
            page.duration = round(duration + 0.3, 2)
        setattr(page, "audio_path", str(audio_path))
        console.print(f"   [{idx}/{len(script.pages)}] {page.duration:.1f}s {page.title[:18]}")
    return script


def render_document_video(
    script: PageScript,
    work_dir: str,
    output_filename: str = "",
    record: bool = True,
) -> str:
    console.print("[bold]Step 5/5: 生成 HTML 并合成视频[/bold]")
    html_path = build_document_html(script, work_dir)
    console.print(f"   HTML: [cyan]{html_path}[/cyan]")
    if not record:
        return html_path
    engine = config.RECORD_ENGINE.lower()
    if engine in ("hyperframes", "hf") and _check_hyperframes_available():
        video_path = _render_with_hyperframes(html_path, script, work_dir, output_filename)
        if video_path:
            return video_path
        console.print("[yellow]HyperFrames 渲染失败，回退到浏览器录制[/yellow]")
    scenes = _pages_as_scenes(script)
    return record_gallery_video(html_path, scenes, "", output_filename or "doc-agent.mp4")


def _render_with_hyperframes(html_path: str, script: PageScript, work_dir: str, output_filename: str = "") -> str:
    video_dir = Path(config.VIDEO_OUTPUT_DIR).resolve()
    video_dir.mkdir(parents=True, exist_ok=True)
    output_path = video_dir / (output_filename or _safe_filename(script.title, "doc-agent.mp4"))
    if output_path.suffix.lower() != ".mp4":
        output_path = output_path.with_suffix(".mp4")
    total_duration = sum(p.duration for p in script.pages)
    cli = _get_hyperframes_cli()
    if not cli:
        return ""
    cmd = [cli, "--yes", "hyperframes", "render", str(Path(html_path).resolve().parent), "-o", str(output_path)]
    timeout_seconds = int(os.getenv(
        "HYPERFRAMES_TIMEOUT_SECONDS",
        str(min(1800, max(300, int(total_duration * 20) + 180))),
    ))
    console.print(f"   HyperFrames: [dim]{' '.join(cmd)}[/dim]")
    started_at = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            cwd=work_dir,
        )
    except subprocess.TimeoutExpired:
        actual = _resolve_rendered_video_path(str(output_path), "", started_at)
        return actual
    actual = _resolve_rendered_video_path(
        str(output_path),
        (result.stdout or "") + "\n" + (result.stderr or ""),
        started_at,
    )
    if result.returncode == 0 and actual:
        console.print(f"   视频: [green]{actual}[/green]")
        return actual
    if result.stderr:
        for line in result.stderr.strip().splitlines()[-10:]:
            console.print(f"[dim]   {line}[/dim]")
    return ""


def _pages_as_scenes(script: PageScript) -> list[dict]:
    scenes = []
    for page in script.pages:
        scenes.append({
            "scene_title": page.title,
            "narration": page.narration,
            "duration": page.duration,
            "audio_path": getattr(page, "audio_path", ""),
        })
    return scenes


def _get_audio_duration(path: str) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def _speed_up_audio(path: Path, speed: float) -> Path:
    if speed <= 1.01:
        return path
    fast_path = path.with_name(f"{path.stem}_x{str(speed).replace('.', '_')}{path.suffix}")
    filters = _atempo_filters(speed)
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(path),
                "-filter:a", filters,
                "-vn", str(fast_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        ).check_returncode()
        if fast_path.exists() and fast_path.stat().st_size > 100:
            return fast_path
    except Exception as exc:
        console.print(f"[yellow]⚠️ 音频加速失败，使用原始语速: {exc}[/yellow]")
    return path


def _atempo_filters(speed: float) -> str:
    parts: list[str] = []
    remaining = speed
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(f"atempo={remaining:.3f}")
    return ",".join(parts)


def _safe_filename(title: str, fallback: str) -> str:
    stem = "".join(c if c.isalnum() or c in "._- " else "_" for c in title).strip()[:40]
    return f"{stem or fallback.removesuffix('.mp4')}.mp4"

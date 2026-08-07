from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from config import config

from .loader import collect_content
from .planner import generate_page_script
from .renderer import generate_page_audio, render_document_video

console = Console()


def build_document_video(
    topic: str = "",
    source: str = "",
    audience: str = "beginner",
    style: str = "news_analysis",
    visual_style: str = "dark_premium",
    duration: int = 60,
    focus: str = "",
    voice_id: str = "",
    voice_type: int = 1,
    voice_speed: float = 1.2,
    output_filename: str = "",
    record: bool = True,
    request_headers: str = "",
) -> str:
    work_dir = Path(config.TEMP_DIR) / "doc_agent"
    work_dir.mkdir(parents=True, exist_ok=True)
    console.print(Panel.fit(
        f"[bold cyan]Doc Agent 项目视频模式[/bold cyan]\n"
        f"主题: [yellow]{topic or '-'}[/yellow]\n"
        f"来源: [yellow]{source or '-'}[/yellow]\n"
        f"观众: [yellow]{audience}[/yellow]  内容风格: [yellow]{style}[/yellow]\n"
        f"页面主题: [yellow]{visual_style}[/yellow]",
        border_style="cyan",
    ))

    console.print("[bold]Step 1/5: 内容采集智能体收集资料[/bold]")
    bundle = collect_content(topic=topic, source=source, request_headers=request_headers)
    (work_dir / "content_bundle.json").write_text(
        json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    console.print(f"   来源类型: [cyan]{bundle.source_type}[/cyan]，标题: [cyan]{bundle.title}[/cyan]")

    script = generate_page_script(
        bundle,
        audience=audience,
        style=style,
        visual_style=visual_style,
        duration=duration,
        focus=focus,
        work_dir=str(work_dir),
    )

    console.print("[bold]Step 3/5: HTML 页面智能体选择页面样式[/bold]")
    console.print("   页面类型: " + ", ".join(page.page_type for page in script.pages))

    script = generate_page_audio(script, str(work_dir), voice_id, voice_type, voice_speed)
    (work_dir / "page_script_with_audio.json").write_text(
        json.dumps(script.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return render_document_video(
        script,
        str(work_dir),
        output_filename=output_filename,
        record=record,
    )

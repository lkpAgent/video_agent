"""
🎬 视频自动生成智能体 - 主入口

用法：
  科普模式：python main.py "黑洞是如何形成的"
  口播模式：python main.py --mode narration --text "你的文案..." --name "你的名字"
  python main.py "ChatGPT的工作原理" --no-images
  python main.py "全球变暖的影响" --voice zh-CN-YunxiNeural --theme light
"""

import sys
import os
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.panel import Panel

from config import config
from modules.search import search_web, search_to_context
from modules.script_generator import generate_script
from modules.tts import generate_audio
from modules.image_gen import generate_scene_images
from modules.video_builder import build_video

console = Console()

BANNER = """
[bold cyan]
╔══════════════════════════════════════════════╗
║   🎬  AI 视频自动生成智能体  v1.0           ║
║   主题 → 搜索 → 脚本 → 配音 → 视频          ║
╚══════════════════════════════════════════════╝
[/bold cyan]
"""


# ==================== 口播叙述模式 ====================
def _run_narration_mode(args):
    """口播模式：输入主题/文案 → LLM生成或直接拆分 → TTS配音 → 口播视频"""
    from modules.narration_video import (
        split_sentences, generate_narration_audio,
        generate_narration_html, record_narration_video
    )
    from openai import OpenAI

    if args.voice:
        config.TTS_VOICE = args.voice

    # 确定文案来源：用户直接提供 / LLM 自动生成
    if args.text:
        # 模式 A：用户直接提供文案
        text = args.text
        title = args.topic or text[:20].replace("\n", " ")
        n_sentences = 0  # 不限制
    else:
        # 模式 B：给定主题 + 句数 → LLM 生成
        topic = args.topic
        if not topic:
            topic = console.input("[bold yellow]🎯 请输入口播主题: [/bold yellow]").strip()
            if not topic:
                console.print("[red]主题不能为空[/red]")
                return

        n_input = args.sentences
        if n_input <= 0:
            n_input_str = console.input(
                "[bold yellow]📝 需要几句口播文案? (默认5): [/bold yellow]"
            ).strip()
            n_input = int(n_input_str) if n_input_str.isdigit() else 5

        console.print(f"\n🤖 [bold cyan]LLM 正在生成 {n_input} 句口播文案...[/bold cyan]")
        title, text = _llm_generate_narration(topic, n_input)
        if not text:
            console.print("[red]LLM 生成失败[/red]")
            return

        console.print(f"\n📋 [bold]生成的标题:[/bold] [cyan]{title}[/cyan]")
        console.print(f"[bold]生成的文案:[/bold]")
        for i, s in enumerate(text.replace("\n", " ").split("。"), 1):
            s = s.strip()
            if s:
                console.print(f"  [dim]{i}. {s}[/dim]")
        console.print()

    console.print(f"\n📋 [bold]口播模式配置:[/bold]")
    console.print(f"   标题: [cyan]{title}[/cyan]")
    console.print(f"   播主: [cyan]{args.name}[/cyan]")
    console.print(f"   公司: [dim]{args.company} · {args.slogan}[/dim]")
    console.print(f"   TTS: [dim]{config.TTS_VOICE}[/dim]")
    console.print(f"   文案: [dim]{len(text)} 字[/dim]\n")

    # Step 1: 拆句
    console.print("[bold]━━━ Step 1/4: 拆分句子 ━━━[/bold]")
    sentences = split_sentences(text)
    if not sentences:
        console.print("[red]未能拆分出有效句子[/red]")
        return

    # Step 2: TTS
    console.print("[bold]━━━ Step 2/4: 生成配音 ━━━[/bold]")
    audio_data = generate_narration_audio(sentences)

    # Step 3: 背景图
    bg_image = ""
    if config.IMAGE_GEN_ENABLED:
        console.print("[bold]━━━ Step 3/4: 生成背景图 ━━━[/bold]")
        fake_script = {
            "scenes": [{
                "image_prompt": "A clean professional studio background, modern tech style, "
                               "soft lighting, 16:9, 4K, minimalist, purple and dark blue tones, cinematic"
            }]
        }
        try:
            images = generate_scene_images(fake_script)
            bg_image = images[0] if images else ""
        except Exception as e:
            console.print(f"[yellow]背景图生成失败: {e}[/yellow]")
    else:
        console.print("[bold]━━━ Step 3/4: 跳过背景图 ━━━[/bold]")

    # Step 4: 构建视频
    console.print("[bold]━━━ Step 4/4: 构建视频 ━━━[/bold]")
    try:
        html_path = generate_narration_html(
            title=title, audio_data=audio_data, background_image=bg_image,
            narrator_name=args.name, narrator_avatar=args.avatar or "",
            company=args.company, slogan=args.slogan
        )
        console.print(f"📄 HTML 已生成: {html_path}")

        if args.no_record:
            console.print("[yellow]跳过录制（--no-record）[/yellow]")
            console.print(f"💡 浏览器打开: {html_path}")
            return

        video_path = record_narration_video(html_path, args.output)
        if Path(video_path).suffix.lower() in (".mp4", ".webm"):
            from modules.db import save_video
            save_video({
                "filename": Path(video_path).name,
                "type": "narration",
                "title": title,
                "topic": args.topic or title,
                "content": text,
                "narrator_name": args.name,
                "narrator_avatar": args.avatar or "",
                "company": args.company,
                "slogan": args.slogan,
                "voice_id": args.voice or config.TTS_VOICE,
                "background": bg_image,
            })
        console.print()
        console.print(Panel.fit(
            f"[bold green]✅ 口播视频生成完成！[/bold green]\n\n"
            f"📁 输出: [cyan]{video_path}[/cyan]\n"
            f"🎤 播主: [yellow]{args.name}[/yellow]",
            border_style="green"
        ))
    except Exception as e:
        console.print(f"[red]构建失败: {e}[/red]")
        import traceback
        traceback.print_exc()


def _llm_generate_narration(topic: str, n: int) -> tuple[str, str]:
    """
    调用 LLM 生成口播标题和 N 句文案
    Returns: (title, text)
    """
    from openai import OpenAI

    client = OpenAI(
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_BASE_URL
    )

    prompt = f"""你是一个专业的短视频口播文案写手。请根据主题生成一段口播文案。

主题：{topic}

要求：
1. 生成一个吸引人的标题（10字以内）
2. 生成恰好 {n} 句话的口播文案
3. 每句话是一个自然的口播句子（中文，15~40字）
4. 句子之间有逻辑递进关系
5. 语气亲切自然，像在跟朋友聊天

输出格式（严格 JSON，不要 markdown）：
{{"title": "标题", "text": "第一句话。第二句话。第三句话。..."}}"""

    try:
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
            temperature=0.9
        )

        raw = response.choices[0].message.content.strip()
        # 清理 markdown
        import re
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)

        data = json.loads(raw)
        return data.get("title", topic[:15]), data.get("text", "")

    except Exception as e:
        console.print(f"[red]LLM 调用失败: {e}[/red]")
        return topic[:15], ""


def main():
    parser = argparse.ArgumentParser(
        description="AI 视频自动生成智能体",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py "黑洞是如何形成的"              # 科普模式
  python main.py --mode narration --text "..."    # 口播模式
  python main.py "AI的未来" --no-images --theme light
        """
    )

    parser.add_argument("topic", nargs="?", help="视频主题（科普模式）")
    parser.add_argument("--mode", type=str, choices=["science", "narration"],
                        default="science", help="视频模式: science(默认), narration(口播)")
    parser.add_argument("--text", type=str, help="[口播] 文案内容（直接提供，跳过LLM生成）")
    parser.add_argument("--sentences", "-n", type=int, default=0,
                        help="[口播] LLM 生成的句子数（默认交互提问）")
    parser.add_argument("--name", type=str, default="AI 主播", help="[口播] 播主名称")
    parser.add_argument("--avatar", type=str, help="[口播] 头像路径")
    parser.add_argument("--company", type=str, default="AI Video", help="[口播] 公司名")
    parser.add_argument("--slogan", type=str, default="用 AI 创造精彩", help="[口播] Slogan")
    parser.add_argument("--no-images", action="store_true", help="不生成 AI 图片")
    parser.add_argument("--no-record", action="store_true", help="仅生成 HTML，不录制")
    parser.add_argument("--voice", type=str, help="TTS 语音")
    parser.add_argument("--theme", type=str, choices=["dark", "light", "warm"], help="主题风格")
    parser.add_argument("--output", type=str, help="输出文件名")
    parser.add_argument("--search-only", action="store_true", help="仅搜索")
    parser.add_argument("--custom-instruction", type=str, help="额外创作指令")

    args = parser.parse_args()
    console.print(BANNER)

    # ==================== 口播模式 ====================
    if args.mode == "narration":
        _run_narration_mode(args)
        return

    # ==================== 科普模式 ====================
    topic = args.topic
    if not topic:
        topic = console.input("[bold yellow]🎯 请输入视频主题: [/bold yellow]").strip()
        if not topic:
            console.print("[red]主题不能为空[/red]")
            return

    if args.no_images:
        config.IMAGE_GEN_ENABLED = False
    if args.voice:
        config.TTS_VOICE = args.voice
    if args.theme:
        config.VIDEO_THEME = args.theme

    console.print(f"\n📋 [bold]配置摘要:[/bold]")
    console.print(f"   主题: [cyan]{topic}[/cyan]")
    console.print(f"   LLM: [dim]{config.LLM_MODEL}[/dim]")
    console.print(f"   TTS: [dim]{config.TTS_VOICE}[/dim]")
    console.print(f"   图片: [dim]{'启用' if config.IMAGE_GEN_ENABLED else '禁用'}[/dim]")
    console.print(f"   风格: [dim]{config.VIDEO_THEME}[/dim]\n")

    # Step 1: 搜索
    try:
        console.print("[bold]━━━ Step 1/5: 搜索资料 ━━━[/bold]")
        results = search_web(topic)
        if not results:
            console.print("[red]未搜索到任何结果[/red]")
            return
        if args.search_only:
            console.print("[green]✅ 搜索完成[/green]")
            return
        search_context = search_to_context(results)
    except Exception as e:
        console.print(f"[red]搜索失败: {e}[/red]")
        search_context = f"主题：{topic}\n（无搜索结果，使用模型自身知识）"

    # Step 2: 生成脚本
    try:
        console.print("[bold]━━━ Step 2/5: 生成脚本 ━━━[/bold]")
        script = generate_script(topic, search_context, args.custom_instruction)
    except Exception as e:
        console.print(f"[red]脚本生成失败: {e}[/red]")
        return

    # Step 3: 生成配音
    try:
        console.print("[bold]━━━ Step 3/5: 生成配音 ━━━[/bold]")
        audio_path, _, _ = generate_audio(script)
    except Exception as e:
        console.print(f"[red]配音生成失败: {e}[/red]")
        audio_path = ""

    # Step 4: 生成图片
    try:
        console.print("[bold]━━━ Step 4/5: 生成场景图 ━━━[/bold]")
        image_paths = generate_scene_images(script)
    except Exception as e:
        console.print(f"[red]图片生成失败: {e}[/red]")
        image_paths = [""] * len(script["scenes"])

    # Step 5: 构建视频
    try:
        console.print("[bold]━━━ Step 5/5: 构建视频 ━━━[/bold]")
        video_path = build_video(
            script=script, audio_path=audio_path,
            image_paths=image_paths, output_filename=args.output,
            record=not args.no_record
        )
        if Path(video_path).suffix.lower() in (".mp4", ".webm"):
            from modules.db import save_video
            save_video({
                "filename": Path(video_path).name,
                "type": "science",
                "title": script.get("title", topic),
                "topic": topic,
                "content": "\n".join(
                    scene.get("narration", "") for scene in script.get("scenes", [])
                    if scene.get("narration")
                ),
                "narrator_name": args.name,
                "narrator_avatar": args.avatar or "",
                "company": args.company,
                "slogan": args.slogan,
                "voice_id": args.voice or config.TTS_VOICE,
                "theme": args.theme or config.VIDEO_THEME,
                "script": script,
            })
    except Exception as e:
        console.print(f"[red]视频构建失败: {e}[/red]")
        return

    console.print()
    console.print(Panel.fit(
        f"[bold green]✅ 视频生成完成！[/bold green]\n\n"
        f"📁 输出目录: [cyan]{config.OUTPUT_DIR}[/cyan]\n"
        f"🎥 视频文件: [cyan]{video_path}[/cyan]\n"
        f"📝 标题: [yellow]{script.get('title', 'N/A')}[/yellow]",
        border_style="green"
    ))

    if video_path.endswith(".html"):
        console.print(f"\n💡 浏览器打开 HTML: [cyan]{video_path}[/cyan]")
    elif video_path.endswith(".mp4"):
        console.print(f"\n🎉 [bold green]MP4 已就绪，可直接播放/上传！[/bold green]")
    elif video_path.endswith(".webm"):
        console.print(f"\n💡 转换为 MP4: ffmpeg -i \"{video_path}\" ...")


if __name__ == "__main__":
    main()

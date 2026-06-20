"""
视频生成智能体 - Web 服务
"""

import os, sys, json, uuid, re as regex, shutil
from pathlib import Path
from datetime import datetime
from rich.console import Console

console = Console()

sys.path.insert(0, str(Path(__file__).parent.resolve()))
# 确保能找到 modules 包
PROJECT_ROOT = str(Path(__file__).parent.resolve())
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 验证项目结构
if not (Path(__file__).parent / "modules").exists():
    print(f"ERROR: modules/ not found at {Path(__file__).parent}")
    print(f"Please run from the video-agent project root directory")
    exit(1)

from fastapi import FastAPI, Request, BackgroundTasks, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from config import config

Path(config.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
Path(config.TEMP_DIR).mkdir(parents=True, exist_ok=True)
BASE_TEMP_DIR = Path(config.TEMP_DIR).resolve()

app = FastAPI(title="AI Video Agent", docs_url="/docs")

# CORS：允许前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_static_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/vendor/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response

VIDEO_OUTPUT = Path(config.VIDEO_OUTPUT_DIR).resolve()
VIDEO_OUTPUT.mkdir(parents=True, exist_ok=True)

tasks: dict = {}


def _fresh_task_dir(task_id: str) -> Path:
    work_dir = (BASE_TEMP_DIR / task_id).resolve()
    if BASE_TEMP_DIR not in work_dir.parents:
        raise ValueError("非法任务目录")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def _task_dir(task_id: str) -> Path:
    work_dir = (BASE_TEMP_DIR / task_id).resolve()
    if BASE_TEMP_DIR not in work_dir.parents:
        raise ValueError("非法任务目录")
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def _safe_video_name(topic: str) -> str:
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in topic)[:30].strip() or "video"
    base = f"{safe}.mp4"
    if not (VIDEO_OUTPUT / base).exists():
        return base
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{safe}_{ts}.mp4"


def _set_task(task_id, status, detail=""):
    if task_id in tasks:
        tasks[task_id]["status"] = status
        tasks[task_id]["detail"] = detail


def _save_video_metadata(data):
    """元数据保存失败不应让已经生成成功的视频任务失败。"""
    try:
        from modules.db import save_video
        save_video(data)
        return True
    except Exception as exc:
        console.print(f"[yellow]⚠️ 视频已生成，但元数据保存失败: {exc}[/yellow]")
        return False


def _generate_science_video(task_id, topic, voice, voice_api_type, theme, name, avatar, company, slogan, profile_id=""):
    try:
        # 本次生成的独立临时目录
        work_dir = Path(config.TEMP_DIR) / task_id
        work_dir.mkdir(parents=True, exist_ok=True)
        audio_dir = work_dir / "audio"
        audio_dir.mkdir(exist_ok=True)
        orig_temp = config.TEMP_DIR
        config.TEMP_DIR = str(work_dir)
        _set_task(task_id, "searching", "🔍 搜索资料...")
        from modules.search import search_web, search_to_context
        results = search_web(topic)
        ctx = search_to_context(results) if results else f"主题：{topic}"

        _set_task(task_id, "scripting", "📝 LLM 生成脚本...")
        if theme: config.VIDEO_THEME = theme
        from modules.script_generator import generate_script
        script = generate_script(topic, ctx)

        _set_task(task_id, "audio", "🔊 生成配音...")
        from modules.tts import generate_audio
        audio_path, _, _ = generate_audio(script, voice, voice_api_type)

        _set_task(task_id, "images", "🎨 生成场景 1/? 背景图...")
        from modules.image_gen import generate_scene_images
        tasks[task_id]["images"] = []

        def img_progress(idx, total, img_path=""):
            _set_task(task_id, "images", f"🎨 生成场景 {idx}/{total} 背景图...")
            if img_path:
                # 统一转为 /output/xxx.png 格式的 URL
                abs_img = str(Path(img_path).resolve())
                abs_out = str(Path(config.OUTPUT_DIR).resolve())
                try:
                    rel = os.path.relpath(abs_img, abs_out)
                except ValueError:
                    rel = Path(img_path).name
                tasks[task_id]["images"].append(f"/output/{rel.replace(chr(92), '/')}")

        image_paths = generate_scene_images(script, progress_callback=img_progress)

        _set_task(task_id, "recording", "🎥 录制视频 + 合成音频...")
        from modules.video_builder import build_video
        filename = _safe_video_name(topic)
        video_path = build_video(script, audio_path, image_paths, output_filename=filename)
        _save_video_metadata({
            "filename": Path(video_path).name,
            "type": "science",
            "title": script.get("title", topic),
            "topic": topic,
            "content": "\n".join(
                scene.get("narration", "") for scene in script.get("scenes", [])
                if scene.get("narration")
            ),
            "profile_id": profile_id,
            "narrator_name": name,
            "narrator_avatar": avatar,
            "company": company,
            "slogan": slogan,
            "voice_id": voice,
            "voice_type": voice_api_type,
            "theme": theme,
            "script": script,
        })

        tasks[task_id].update({
            "status": "done", "detail": "✅ 完成！",
            "video": Path(video_path).name, "title": script.get("title", topic)
        })
    except Exception as e:
        import traceback
        console.print(f"[red]❌ {e}[/red]")
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        tasks[task_id].update({"status": "error", "detail": f"❌ {e}"})
    finally:
        config.TEMP_DIR = orig_temp


def _generate_gallery_video(task_id, images, text, title, bgm, voice, voice_api_type, name, avatar, company, slogan, profile_id=""):
    try:
        work_dir = Path(config.TEMP_DIR) / task_id
        work_dir.mkdir(parents=True, exist_ok=True)
        orig_temp = config.TEMP_DIR
        config.TEMP_DIR = str(work_dir)

        if not images or not text:
            raise ValueError("图片和文字内容不能为空")

        _set_task(task_id, "scripting", "📝 LLM 拆解文案...")
        from modules.gallery_video import (
            llm_breakdown_gallery_text, generate_gallery_audio,
            generate_gallery_html, record_gallery_video,
            _record_hyperframes
        )

        # Step 1: LLM 拆解
        scenes = llm_breakdown_gallery_text(text, len(images), title)

        # Step 2: 配音
        _set_task(task_id, "audio", f"🔊 生成配音 (1/{len(scenes)})...")
        scenes = generate_gallery_audio(scenes, voice, voice_api_type)

        filename = _safe_video_name(title or "gallery")
        engine = config.RECORD_ENGINE.lower()
        if engine in ("hyperframes", "hf"):
            _set_task(task_id, "recording", "🎬 HyperFrames 逐帧渲染中...")
            try:
                video_path = _record_hyperframes(scenes, images, title, bgm, filename, str(work_dir))
            except Exception as exc:
                if not getattr(config, "RECORD_FALLBACK_TO_SELENIUM", True):
                    raise
                console.print(f"[yellow]⚠️ HyperFrames 图文视频失败，回退 Firefox + Selenium: {exc}[/yellow]")
                _set_task(task_id, "html", "📄 HyperFrames 不可用，生成 HTML 页面...")
                html_path = generate_gallery_html(scenes, images, title, bgm)
                _set_task(task_id, "recording", "🎥 回退 Firefox + Selenium 录制...")
                video_path = record_gallery_video(html_path, scenes, bgm, filename)
        else:
            _set_task(task_id, "html", "📄 生成 HTML 页面...")
            html_path = generate_gallery_html(scenes, images, title, bgm)
            _set_task(task_id, "recording", "🎥 录制视频 + 合成音频...")
            video_path = record_gallery_video(html_path, scenes, bgm, filename)

        if not video_path:
            raise RuntimeError("图文视频渲染失败")

        metadata_saved = _save_video_metadata({
            "filename": Path(video_path).name,
            "type": "gallery",
            "title": title,
            "topic": title,
            "content": text,
            "profile_id": profile_id,
            "narrator_name": name,
            "narrator_avatar": avatar,
            "company": company,
            "slogan": slogan,
            "voice_id": voice,
            "voice_type": voice_api_type,
            "background": bgm,
        })

        tasks[task_id].update({
            "status": "done",
            "detail": "✅ 完成！" if metadata_saved else "✅ 视频完成，数据库元数据保存失败",
            "video": Path(video_path).name, "title": title
        })
    except Exception as e:
        import traceback
        console.print(f"[red]❌ {e}[/red]")
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        tasks[task_id].update({"status": "error", "detail": f"❌ {e}"})
    finally:
        config.TEMP_DIR = orig_temp


def _generate_narration_video(task_id, topic, n_sentences, voice, name, avatar, company, slogan, voice_type, voice_api_type, bg_preset, content, profile_id=""):
    try:
        # 独立临时目录
        work_dir = Path(config.TEMP_DIR) / task_id
        work_dir.mkdir(parents=True, exist_ok=True)
        orig_temp = config.TEMP_DIR
        config.TEMP_DIR = str(work_dir)

        from modules.search import search_web, search_to_context

        # 如果提供了直接内容，跳过搜索和 LLM，直接按行拆分
        if content and content.strip():
            lines = [l.strip() for l in content.strip().split("\n") if l.strip()]
            if not lines:
                raise ValueError("内容为空")
            title = topic.strip() if topic and topic.strip() else lines[0]
            text = "\n".join(lines)
            n_sentences = len(lines)
            console.print(f"   使用直接内容: {len(lines)} 行")
        else:
            results = search_web(topic)
            search_ctx = search_to_context(results) if results else ""

            _set_task(task_id, "scripting", "📝 LLM 生成口播文案...")
            from openai import OpenAI
            client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
            prompt = f"""主题：{topic}
生成{n_sentences}句口播文案，每句15-40字。
只返回JSON：{{"title":"标题","text":"句1。句2。句3。句4。句5。"}}"""
            resp = client.chat.completions.create(
                model=config.LLM_MODEL, messages=[{"role":"user","content":prompt}],
                max_tokens=1024, temperature=0.9)
            raw = resp.choices[0].message.content or ""
            console.print(f"   [dim]LLM 返回 {len(raw)} 字符[/dim]")
            if not raw.strip():
                console.print(f"[red]LLM 空响应[/red]")
                raise ValueError("LLM 返回空响应")
            raw = regex.sub(r'^```(?:json)?\s*', '', raw)
            raw = regex.sub(r'\s*```$', '', raw)
            json_match = regex.search(r'\{[\s\S]*\}', raw)
            if json_match:
                raw = json_match.group()
            try:
                data = json.loads(raw)
                title = data.get("title", topic[:15])
                text = data.get("text", "")
            except (json.JSONDecodeError, ValueError):
                console.print(f"[yellow]JSON 解析失败，尝试提取纯文本[/yellow]")
                title = topic.strip()
                lines = [l.strip() for l in raw.replace("\n", "").split("。") if len(l.strip()) > 3]
                text = "。".join(lines[:n_sentences])
                if not text:
                    text = raw[:200]
            if not text:
                raise ValueError("LLM 未生成有效文案")

        _set_task(task_id, "formatting", "✨ 大模型智能排版...")
        from modules.content_formatter import format_narration_content
        text, sentences = format_narration_content(text)
        tasks[task_id]["content"] = text
        console.print(f"   智能排版完成: {len(sentences)} 个页面")
        console.print("   ===== 最终排版文案开始 =====")
        console.print(text, markup=False)
        console.print("   ===== 最终排版文案结束 =====")
        tasks[task_id]["title"] = title

        _set_task(task_id, "audio", "🔊 生成配音...")
        from modules.narration_video import generate_narration_audio
        audio_data = generate_narration_audio(sentences, voice_type or voice, voice_api_type)

        # 背景图：优先用预设
        bg_image = ""
        if bg_preset:
            preset_path = Path("static") / "backgrounds" / bg_preset
            if preset_path.exists():
                bg_image = str(preset_path.resolve())
                console.print(f"   背景: {bg_preset}")
        if not bg_image and config.IMAGE_GEN_ENABLED:
            _set_task(task_id, "images", "🎨 生成背景图...")
            from modules.image_gen import generate_scene_images
            try:
                imgs = generate_scene_images({"scenes":[{"image_prompt":"professional studio, cinematic, 9:16"}]})
                bg_image = imgs[0] if imgs else ""
            except Exception: pass

        _set_task(task_id, "recording", "🎥 录制视频 + 合成音频...")
        from modules.narration_video import generate_narration_html, record_narration_video
        html_path = generate_narration_html(
            title=title, audio_data=audio_data, background_image=bg_image,
            narrator_name=name or "AI主播", narrator_avatar=avatar or "",
            company=company or "", slogan=slogan or "")
        filename = _safe_video_name(title)
        video_path = record_narration_video(html_path, filename)
        _save_video_metadata({
            "filename": Path(video_path).name,
            "type": "narration",
            "title": title,
            "topic": topic,
            "content": text,
            "profile_id": profile_id,
            "narrator_name": name,
            "narrator_avatar": avatar,
            "company": company,
            "slogan": slogan,
            "voice_id": voice_type or voice,
            "voice_type": voice_api_type,
            "background": bg_preset,
        })

        tasks[task_id].update({
            "status": "done", "detail": "✅ 完成！",
            "video": Path(video_path).name, "title": title
        })
    except Exception as e:
        import traceback
        console.print(f"[red]❌ {e}[/red]")
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        tasks[task_id].update({"status": "error", "detail": f"❌ {e}"})
    finally:
        config.TEMP_DIR = orig_temp


def _generate_doc_agent_video(task_id, topic, source, audience, style, visual_style, duration, focus, voice, voice_api_type, name, avatar, company, slogan, profile_id=""):
    orig_temp = config.TEMP_DIR
    try:
        work_dir = _fresh_task_dir(task_id)
        config.TEMP_DIR = str(work_dir)

        if not (topic or source):
            raise ValueError("请提供主题或文档来源")

        _set_task(task_id, "collecting", "📚 内容采集智能体正在收集资料...")
        from modules.doc_agent import build_document_video
        filename = _safe_video_name(topic or source or "doc-agent")

        _set_task(task_id, "generating", "🧠 文档重构智能体正在生成页面与旁白...")
        video_path = build_document_video(
            topic=topic,
            source=source,
            audience=audience or "beginner",
            style=style or "tech_explainer",
            visual_style=visual_style or "bright_unified",
            duration=int(duration or 90),
            focus=focus or "",
            voice_id=voice or "",
            voice_type=voice_api_type,
            output_filename=filename,
            record=True,
        )

        title = topic or source or "文档视频"
        metadata_saved = _save_video_metadata({
            "filename": Path(video_path).name,
            "type": "doc-agent",
            "title": title,
            "topic": topic or source,
            "content": source or topic,
            "profile_id": profile_id,
            "narrator_name": name,
            "narrator_avatar": avatar,
            "company": company,
            "slogan": slogan,
            "voice_id": voice,
            "voice_type": voice_api_type,
            "theme": style,
            "script": {"visual_style": visual_style or "bright_unified"},
        })

        tasks[task_id].update({
            "status": "done",
            "detail": "✅ 完成！" if metadata_saved else "✅ 视频完成，数据库元数据保存失败",
            "video": Path(video_path).name,
            "title": title,
            "content": source or topic,
        })
    except Exception as e:
        import traceback
        console.print(f"[red]❌ {e}[/red]")
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        tasks[task_id].update({"status": "error", "detail": f"❌ {e}"})
    finally:
        config.TEMP_DIR = orig_temp


def _prepare_doc_agent_review(task_id, topic, source, audience, style, visual_style, duration, focus, voice, voice_api_type, name, avatar, company, slogan, profile_id=""):
    orig_temp = config.TEMP_DIR
    try:
        work_dir = _fresh_task_dir(task_id)
        config.TEMP_DIR = str(work_dir)

        if not (topic or source):
            raise ValueError("请提供主题或文档来源")

        tasks[task_id].pop("bundle", None)
        tasks[task_id].pop("script", None)
        tasks[task_id].pop("content", None)
        tasks[task_id].pop("title", None)
        tasks[task_id].pop("video", None)

        tasks[task_id]["params"] = {
            "topic": topic, "source": source, "audience": audience, "style": style,
            "visual_style": visual_style, "duration": duration, "focus": focus,
            "voice": voice, "voice_api_type": voice_api_type, "name": name,
            "avatar": avatar, "company": company, "slogan": slogan, "profile_id": profile_id,
        }

        _set_task(task_id, "collecting", "📚 内容采集智能体正在收集资料...")
        from modules.doc_agent.loader import collect_content
        from modules.doc_agent.planner import generate_page_script
        bundle = collect_content(topic=topic, source=source)
        tasks[task_id]["bundle"] = bundle
        (work_dir / "content_bundle.json").write_text(
            json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        _set_task(task_id, "scripting", "🧠 正在生成每页标题、文案和旁白...")
        script = generate_page_script(
            bundle,
            audience=audience or "beginner",
            style=style or "tech_explainer",
            visual_style=visual_style or "bright_unified",
            duration=int(duration or 90),
            focus=focus or "",
            work_dir=str(work_dir),
        )
        tasks[task_id].update({
            "status": "awaiting_review",
            "detail": "文案已生成，请确认；30 秒后将自动继续生成视频。",
            "title": script.title,
            "script": script.to_dict(),
            "content": _script_preview_text(script),
        })
    except Exception as e:
        import traceback
        console.print(f"[red]❌ {e}[/red]")
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        tasks[task_id].update({"status": "error", "detail": f"❌ {e}", "error": str(e)})
    finally:
        config.TEMP_DIR = orig_temp


def _revise_doc_agent_review(task_id, feedback):
    orig_temp = config.TEMP_DIR
    try:
        task = tasks.get(task_id) or {}
        params = task.get("params") or {}
        bundle = task.get("bundle")
        if not bundle:
            raise ValueError("原始资料已失效，请重新生成文案")
        work_dir = _task_dir(task_id)
        config.TEMP_DIR = str(work_dir)
        _set_task(task_id, "scripting", "🧠 正在根据你的修改意见重写文案...")
        from modules.doc_agent.planner import generate_page_script
        focus = (params.get("focus") or "").strip()
        revision_focus = f"{focus}\n用户修改意见：{feedback}".strip()
        script = generate_page_script(
            bundle,
            audience=params.get("audience") or "beginner",
            style=params.get("style") or "tech_explainer",
            visual_style=params.get("visual_style") or "bright_unified",
            duration=int(params.get("duration") or 90),
            focus=revision_focus,
            work_dir=str(work_dir),
        )
        tasks[task_id].update({
            "status": "awaiting_review",
            "detail": "文案已按意见重写，请再次确认；30 秒后将自动继续。",
            "title": script.title,
            "script": script.to_dict(),
            "content": _script_preview_text(script),
        })
    except Exception as e:
        import traceback
        console.print(f"[red]❌ {e}[/red]")
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        tasks[task_id].update({"status": "error", "detail": f"❌ {e}", "error": str(e)})
    finally:
        config.TEMP_DIR = orig_temp


def _continue_doc_agent_video(task_id):
    orig_temp = config.TEMP_DIR
    try:
        task = tasks.get(task_id) or {}
        params = task.get("params") or {}
        script_data = task.get("script") or {}
        if not script_data:
            raise ValueError("没有可继续生成的视频文案")
        work_dir = _task_dir(task_id)
        config.TEMP_DIR = str(work_dir)

        from modules.doc_agent.renderer import generate_page_audio, render_document_video
        from modules.doc_agent.schemas import PageScript, PageSpec

        pages = [PageSpec(**page) for page in script_data.get("pages", [])]
        script = PageScript(
            title=script_data.get("title") or params.get("topic") or "文档视频",
            audience=script_data.get("audience") or params.get("audience") or "beginner",
            style=script_data.get("style") or params.get("style") or "tech_explainer",
            visual_style=script_data.get("visual_style") or params.get("visual_style") or "bright_unified",
            pages=pages,
        )

        _set_task(task_id, "audio", "🔊 正在生成逐页旁白...")
        script = generate_page_audio(
            script,
            str(work_dir),
            params.get("voice") or "",
            int(params.get("voice_api_type") or 1),
        )
        (work_dir / "page_script_with_audio.json").write_text(
            json.dumps(script.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        _set_task(task_id, "recording", "🎬 正在生成 HTML 并合成视频...")
        filename = _safe_video_name(params.get("topic") or params.get("source") or script.title or "doc-agent")
        video_path = render_document_video(script, str(work_dir), output_filename=filename, record=True)

        title = script.title or params.get("topic") or params.get("source") or "文档视频"
        metadata_saved = _save_video_metadata({
            "filename": Path(video_path).name,
            "type": "doc-agent",
            "title": title,
            "topic": params.get("topic") or params.get("source"),
            "content": params.get("source") or params.get("topic"),
            "profile_id": params.get("profile_id") or "",
            "narrator_name": params.get("name") or "",
            "narrator_avatar": params.get("avatar") or "",
            "company": params.get("company") or "",
            "slogan": params.get("slogan") or "",
            "voice_id": params.get("voice") or "",
            "voice_type": int(params.get("voice_api_type") or 1),
            "theme": params.get("style") or "tech_explainer",
            "script": script.to_dict(),
        })
        tasks[task_id].update({
            "status": "done",
            "detail": "✅ 完成！" if metadata_saved else "✅ 视频完成，数据库元数据保存失败",
            "video": Path(video_path).name,
            "title": title,
            "content": _script_preview_text(script),
            "script": script.to_dict(),
        })
    except Exception as e:
        import traceback
        console.print(f"[red]❌ {e}[/red]")
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        tasks[task_id].update({"status": "error", "detail": f"❌ {e}", "error": str(e)})
    finally:
        config.TEMP_DIR = orig_temp


def _script_preview_text(script):
    lines = []
    for idx, page in enumerate(getattr(script, "pages", []) or [], 1):
        lines.append(f"{idx}. {page.title}")
        if page.subtitle:
            lines.append(f"   {page.subtitle}")
        if page.bullets:
            lines.append("   " + " / ".join(page.bullets))
        if page.narration:
            lines.append(f"   旁白：{page.narration}")
    return "\n".join(lines)


# ====== API ======

@app.get("/video-api/health")
async def health(): return {"status": "ok"}

# ====== 播主档案 CRUD ======

@app.get("/video-api/profiles")
async def api_list_profiles():
    from modules.db import list_profiles
    return {"profiles": list_profiles()}

@app.post("/video-api/profiles")
async def api_create_profile(req: Request):
    from modules.db import save_profile
    data = await req.json()
    pid = save_profile(data)
    return {"id": pid, "ok": True}

@app.put("/video-api/profiles/{pid}")
async def api_update_profile(pid: str, req: Request):
    from modules.db import save_profile
    data = await req.json()
    data["id"] = pid
    save_profile(data)
    return {"ok": True}

@app.delete("/video-api/profiles/{pid}")
async def api_delete_profile(pid: str):
    from modules.db import delete_profile
    delete_profile(pid)
    return {"ok": True}

@app.post("/video-api/upload/avatar")
async def api_upload_avatar(file: UploadFile = File(...)):
    import uuid as _uuid
    ext = Path(file.filename).suffix or ".png"
    filename = f"avatar_{_uuid.uuid4().hex[:8]}{ext}"
    avatar_dir = Path("static") / "avatars"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    filepath = avatar_dir / filename
    with open(filepath, "wb") as f:
        f.write(await file.read())
    return {"url": f"/static/avatars/{filename}", "ok": True}

# ====== 语音管理 API ======

@app.get("/video-api/voices")
async def api_list_voices():
    from modules.db import list_voices
    return {"voices": list_voices()}

@app.post("/video-api/voices")
async def api_create_voice(req: Request):
    from modules.db import save_voice
    data = await req.json()
    save_voice(data)
    return {"ok": True}

@app.delete("/video-api/voices/{vid}")
async def api_delete_voice(vid: int):
    from modules.db import delete_voice
    delete_voice(vid)
    return {"ok": True}

@app.get("/video-api/backgrounds")
async def api_list_backgrounds():
    import os
    bg_dir = Path("static") / "backgrounds"
    if not bg_dir.exists():
        return {"backgrounds": []}
    files = []
    for f in sorted(bg_dir.iterdir()):
        if f.suffix.lower() in (".png",".jpg",".jpeg",".svg",".webp"):
            files.append({"name": f.name, "url": f"/static/backgrounds/{f.name}"})
    return {"backgrounds": files}

# ====== 生成 API ======

@app.post("/video-api/generate/science")
async def api_science(req: Request, bg: BackgroundTasks):
    d = await req.json()
    tid = uuid.uuid4().hex[:12]
    tasks[tid] = {"id": tid, "status": "starting", "detail": "启动中...", "type": "science",
                  "topic": d.get("topic",""), "created": datetime.now().isoformat()}
    bg.add_task(_generate_science_video, tid,
                d.get("topic",""), d.get("voice","") or d.get("voice_id",""),
                int(d.get("voice_api_type", 1)), d.get("theme","dark"),
                d.get("name",""), d.get("avatar",""), d.get("company",""), d.get("slogan",""),
                d.get("profile_id",""))
    return {"task_id": tid}

@app.post("/video-api/generate/gallery")
async def api_gallery(req: Request, bg: BackgroundTasks):
    d = await req.json()
    tid = uuid.uuid4().hex[:12]
    tasks[tid] = {"id": tid, "status": "starting", "detail": "启动中...", "type": "gallery",
                  "topic": d.get("title",""), "created": datetime.now().isoformat()}
    bg.add_task(_generate_gallery_video, tid,
                d.get("images",[]), d.get("text",""), d.get("title","图文展示"),
                d.get("bgm",""), d.get("voice","") or d.get("voice_id",""),
                int(d.get("voice_api_type", 1)),
                d.get("name",""), d.get("avatar",""), d.get("company",""), d.get("slogan",""),
                d.get("profile_id",""))
    return {"task_id": tid}


@app.post("/video-api/upload/images")
async def api_upload_images(files: list[UploadFile] = File(...)):
    """批量上传图片，返回路径列表"""
    import uuid as _uuid
    upload_dir = Path(config.TEMP_DIR) / "gallery_images"
    upload_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for file in files:
        ext = Path(file.filename).suffix or ".png"
        filename = f"img_{_uuid.uuid4().hex[:8]}{ext}"
        filepath = upload_dir / filename
        with open(filepath, "wb") as f:
            f.write(await file.read())
        paths.append(str(filepath.resolve()))
    return {"images": paths, "ok": True}


@app.post("/video-api/upload/bgm")
async def api_upload_bgm(file: UploadFile = File(...)):
    """上传背景音乐"""
    import uuid as _uuid
    ext = Path(file.filename).suffix or ".mp3"
    filename = f"bgm_{_uuid.uuid4().hex[:8]}{ext}"
    bgm_dir = Path(config.BGM_DIR)
    bgm_dir.mkdir(parents=True, exist_ok=True)
    filepath = bgm_dir / filename
    with open(filepath, "wb") as f:
        f.write(await file.read())
    return {"url": f"/static/bgm/{filename}", "path": str(filepath.resolve()), "ok": True}


@app.get("/video-api/bgm-list")
async def api_list_bgm():
    """列出可用背景音乐"""
    bgm_dir = Path(config.BGM_DIR)
    if not bgm_dir.exists():
        return {"bgm": []}
    files = []
    for f in sorted(bgm_dir.iterdir()):
        if f.suffix.lower() in (".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"):
            files.append({"name": f.name, "path": str(f.resolve()),
                          "url": f"/static/bgm/{f.name}"})
    return {"bgm": files}


@app.post("/video-api/generate/narration")
async def api_narration(req: Request, bg: BackgroundTasks):
    d = await req.json()
    tid = uuid.uuid4().hex[:12]
    tasks[tid] = {"id": tid, "status": "starting", "detail": "启动中...", "type": "narration",
                  "topic": d.get("topic",""), "created": datetime.now().isoformat()}
    bg.add_task(_generate_narration_video, tid,
                d.get("topic",""), int(d.get("sentences",5)), d.get("voice",""),
                d.get("name","AI主播"), d.get("avatar",""), d.get("company",""), d.get("slogan",""),
                d.get("voice_id","") or d.get("voice_type",""), int(d.get("voice_api_type", 1)),
                d.get("bg_preset",""), d.get("content",""), d.get("profile_id",""))
    return {"task_id": tid}


@app.post("/video-api/generate/doc-agent")
async def api_doc_agent(req: Request, bg: BackgroundTasks):
    d = await req.json()
    tid = uuid.uuid4().hex[:12]
    tasks[tid] = {"id": tid, "status": "starting", "detail": "启动中...", "type": "doc-agent",
                  "topic": d.get("topic", "") or d.get("source", ""), "created": datetime.now().isoformat()}
    bg.add_task(_prepare_doc_agent_review, tid,
                d.get("topic", ""), d.get("source", ""), d.get("audience", "beginner"),
                d.get("style", "tech_explainer"), d.get("visual_style", "bright_unified"),
                int(d.get("duration", 90)),
                d.get("focus", ""), d.get("voice", "") or d.get("voice_id", ""),
                int(d.get("voice_api_type", 1)),
                d.get("name", ""), d.get("avatar", ""), d.get("company", ""), d.get("slogan", ""),
                d.get("profile_id", ""))
    return {"task_id": tid}

@app.post("/video-api/generate/doc-agent/{task_id}/revise")
async def api_doc_agent_revise(task_id: str, req: Request, bg: BackgroundTasks):
    if task_id not in tasks:
        return JSONResponse({"error": "not found"}, 404)
    d = await req.json()
    feedback = (d.get("feedback") or "").strip()
    if not feedback:
        return JSONResponse({"error": "feedback required"}, 400)
    bg.add_task(_revise_doc_agent_review, task_id, feedback)
    return {"task_id": task_id, "ok": True}

@app.post("/video-api/generate/doc-agent/{task_id}/continue")
async def api_doc_agent_continue(task_id: str, bg: BackgroundTasks):
    if task_id not in tasks:
        return JSONResponse({"error": "not found"}, 404)
    if tasks[task_id].get("status") in {"audio", "recording", "done"}:
        return {"task_id": task_id, "ok": True}
    bg.add_task(_continue_doc_agent_video, task_id)
    return {"task_id": task_id, "ok": True}

@app.get("/video-api/status/{task_id}")
async def api_status(task_id: str):
    if task_id not in tasks: return JSONResponse({"error":"not found"}, 404)
    t = tasks[task_id]
    return {"status": t["status"], "detail": t.get("detail",""), "video": t.get("video",""),
            "title": t.get("title",""), "error": t.get("error",""),
            "images": t.get("images", []), "content": t.get("content", ""),
            "script": t.get("script")}

@app.get("/video-api/videos")
async def api_videos():
    from modules.db import list_videos
    records = list_videos()
    by_filename = {v["filename"]: v for v in records}
    vids = []
    for f in sorted(VIDEO_OUTPUT.glob("*.mp4"), key=os.path.getmtime, reverse=True):
        record = by_filename.get(f.name, {})
        vids.append({
            **record,
            "name": f.name,
            "filename": f.name,
            "voice_type": record.get("voice_type", 1),
            "size": f.stat().st_size,
            "time": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            "url": f"/output/{f.name}",
        })
    return {"videos": vids}

app.mount("/output", StaticFiles(directory=str(VIDEO_OUTPUT)), name="output")

# BGM 静态目录（必须在 /static 之前挂载）
_bgm_dir = Path(config.BGM_DIR)
_bgm_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/bgm", StaticFiles(directory=str(_bgm_dir)), name="bgm")

app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8888)

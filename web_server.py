"""
视频生成智能体 - Web 服务
"""

import os, sys, json, uuid, re as regex
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

app = FastAPI(title="AI Video Agent", docs_url="/docs")

# CORS：允许前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

VIDEO_OUTPUT = Path(config.VIDEO_OUTPUT_DIR).resolve()
VIDEO_OUTPUT.mkdir(parents=True, exist_ok=True)

tasks: dict = {}


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


def _generate_science_video(task_id, topic, voice, theme, name, avatar, company, slogan):
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
        if voice: config.TTS_VOICE = voice
        if theme: config.VIDEO_THEME = theme
        from modules.script_generator import generate_script
        script = generate_script(topic, ctx)

        _set_task(task_id, "audio", "🔊 生成配音...")
        from modules.tts import generate_audio
        audio_path, _, _ = generate_audio(script)

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


def _generate_narration_video(task_id, topic, n_sentences, voice, name, avatar, company, slogan, voice_type, bg_preset, content):
    try:
        # 独立临时目录
        work_dir = Path(config.TEMP_DIR) / task_id
        work_dir.mkdir(parents=True, exist_ok=True)
        orig_temp = config.TEMP_DIR
        config.TEMP_DIR = str(work_dir)

        # 动态应用 voice_type
        orig_voice_type = config.DOUBAO_TTS_VOICE_TYPE
        if voice_type:
            config.DOUBAO_TTS_VOICE_TYPE = voice_type
        if voice:
            config.TTS_VOICE = voice
        from modules.search import search_web, search_to_context

        # 如果提供了直接内容，跳过搜索和 LLM，直接按行拆分
        if content and content.strip():
            lines = [l.strip() for l in content.strip().split("\n") if l.strip()]
            if not lines:
                raise ValueError("内容为空")
            title = topic.strip() if topic and topic.strip() else lines[0]
            text = "。".join(lines)
            n_sentences = len(lines)
            console.print(f"   使用直接内容: {len(lines)} 行")
        else:
            results = search_web(topic)
            search_ctx = search_to_context(results) if results else ""

            _set_task(task_id, "scripting", "📝 LLM 生成口播文案...")
            from openai import OpenAI
            if voice: config.TTS_VOICE = voice

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
        tasks[task_id]["title"] = title

        _set_task(task_id, "audio", "🔊 生成配音...")
        from modules.narration_video import split_sentences, generate_narration_audio
        sentences = split_sentences(text)
        audio_data = generate_narration_audio(sentences)

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
        config.DOUBAO_TTS_VOICE_TYPE = orig_voice_type


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
                d.get("topic",""), d.get("voice",""), d.get("theme","dark"),
                d.get("name",""), d.get("avatar",""), d.get("company",""), d.get("slogan",""))
    return {"task_id": tid}

@app.post("/video-api/generate/narration")
async def api_narration(req: Request, bg: BackgroundTasks):
    d = await req.json()
    tid = uuid.uuid4().hex[:12]
    tasks[tid] = {"id": tid, "status": "starting", "detail": "启动中...", "type": "narration",
                  "topic": d.get("topic",""), "created": datetime.now().isoformat()}
    bg.add_task(_generate_narration_video, tid,
                d.get("topic",""), int(d.get("sentences",5)), d.get("voice",""),
                d.get("name","AI主播"), d.get("avatar",""), d.get("company",""), d.get("slogan",""),
                d.get("voice_type",""), d.get("bg_preset",""), d.get("content",""))
    return {"task_id": tid}

@app.get("/video-api/status/{task_id}")
async def api_status(task_id: str):
    if task_id not in tasks: return JSONResponse({"error":"not found"}, 404)
    t = tasks[task_id]
    return {"status": t["status"], "detail": t.get("detail",""), "video": t.get("video",""),
            "title": t.get("title",""), "error": t.get("error",""),
            "images": t.get("images", [])}

@app.get("/video-api/videos")
async def api_videos():
    vids = []
    for f in sorted(VIDEO_OUTPUT.glob("*.mp4"), key=os.path.getmtime, reverse=True):
        vids.append({"name": f.name, "size": f.stat().st_size,
                     "time": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                     "url": f"/output/{f.name}"})
    return {"videos": vids}

app.mount("/output", StaticFiles(directory=str(VIDEO_OUTPUT)), name="output")
app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8888)

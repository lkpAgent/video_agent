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

from fastapi import FastAPI, Request, BackgroundTasks
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
        tasks[task_id].update({"status": "error", "detail": f"❌ {e}"})
    finally:
        config.TEMP_DIR = orig_temp


def _generate_narration_video(task_id, topic, n_sentences, voice, name, avatar, company, slogan):
    try:
        # 独立临时目录
        work_dir = Path(config.TEMP_DIR) / task_id
        work_dir.mkdir(parents=True, exist_ok=True)
        orig_temp = config.TEMP_DIR
        config.TEMP_DIR = str(work_dir)
        _set_task(task_id, "searching", "🔍 搜索资料...")
        from modules.search import search_web, search_to_context
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
            console.print(f"[red]LLM 空响应，finish_reason: {resp.choices[0].finish_reason}[/red]")
            raise ValueError("LLM 返回空响应")
        raw = regex.sub(r'^```(?:json)?\s*', '', raw)
        raw = regex.sub(r'\s*```$', '', raw)
        # 从混合文本中提取 JSON
        json_match = regex.search(r'\{[\s\S]*\}', raw)
        if json_match:
            raw = json_match.group()
        try:
            data = json.loads(raw)
            title = data.get("title", topic[:15])
            text = data.get("text", "")
        except (json.JSONDecodeError, ValueError):
            # JSON 解析失败，尝试从文本中提取
            console.print(f"[yellow]JSON 解析失败，尝试提取纯文本[/yellow]")
            title = topic[:15]
            # 按句号拆分当作文案
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

        bg_image = ""
        if config.IMAGE_GEN_ENABLED:
            _set_task(task_id, "images", "🎨 生成背景图...")
            from modules.image_gen import generate_scene_images
            try:
                imgs = generate_scene_images({"scenes":[{"image_prompt":"professional studio, cinematic, 16:9"}]})
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
        tasks[task_id].update({"status": "error", "detail": f"❌ {e}"})
    finally:
        config.TEMP_DIR = orig_temp


# ====== API ======

@app.get("/video-api/health")
async def health(): return {"status": "ok"}

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
                d.get("name","AI主播"), d.get("avatar",""), d.get("company",""), d.get("slogan",""))
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

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8888)

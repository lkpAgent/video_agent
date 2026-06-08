"""
视频构建模块：生成动态 HTML 网页 → 用 Playwright 录制为 MP4 视频

核心思路：
1. 根据脚本生成一个精美的 HTML 页面
2. 页面包含 CSS 动画、文字动画、背景图切换
3. 嵌入 TTS 配音音频
4. 用 Playwright 打开页面并录制视频
"""

import os
import json
import time
import base64
import shutil
import subprocess
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.progress import Progress

from config import config

console = Console()

# ====== 主题色方案 ======
THEMES = {
    "dark": {
        "bg": "#0a0a0f", "overlay": "rgba(0,0,0,0.55)",
        "accent": "#6366f1", "accent2": "#a855f7",
        "text": "#ffffff", "subtext": "rgba(255,255,255,0.8)",
        "progress": "linear-gradient(90deg, #6366f1, #a855f7, #ec4899)",
        "glow": "rgba(99,102,241,0.3)",
        "card_bg": "rgba(255,255,255,0.06)", "card_border": "rgba(255,255,255,0.1)",
    },
    "light": {
        "bg": "#f8fafc", "overlay": "rgba(255,255,255,0.3)",
        "accent": "#2563eb", "accent2": "#7c3aed",
        "text": "#0f172a", "subtext": "rgba(15,23,42,0.75)",
        "progress": "linear-gradient(90deg, #2563eb, #7c3aed, #db2777)",
        "glow": "rgba(37,99,235,0.15)",
        "card_bg": "rgba(0,0,0,0.03)", "card_border": "rgba(0,0,0,0.08)",
    },
    "warm": {
        "bg": "#1a0f0a", "overlay": "rgba(0,0,0,0.5)",
        "accent": "#f59e0b", "accent2": "#ef4444",
        "text": "#fffbeb", "subtext": "rgba(255,251,235,0.8)",
        "progress": "linear-gradient(90deg, #f59e0b, #ef4444, #f97316)",
        "glow": "rgba(245,158,11,0.25)",
        "card_bg": "rgba(255,255,255,0.05)", "card_border": "rgba(255,255,255,0.08)",
    }
}


def build_video(
    script: dict,
    audio_path: str,
    image_paths: list[str],
    output_filename: str = None,
    record: bool = True
) -> str:
    """
    构建动态网页并录制为视频

    Args:
        script: 视频脚本
        audio_path: 配音文件路径
        image_paths: 每个场景的背景图路径（空字符串表示用纯色）
        output_filename: 输出文件名（不含扩展名）
        record: 是否录制视频（False 表示只生成 HTML）

    Returns:
        输出视频文件路径
    """
    console.print("\n🎬 [bold cyan]正在构建视频...[/bold cyan]")

    # 1. 生成 HTML
    html_path = _generate_html(script, image_paths)
    console.print(f"📄 HTML 页面已生成: {html_path}")

    if not record:
        console.print("[yellow]跳过视频录制（仅生成 HTML）[/yellow]")
        return html_path

    # 2. 录制视频（无声）→ ffmpeg 合成音频
    video_path = _record_video(html_path, script, audio_path, output_filename)
    console.print(f"🎥 [bold green]视频已生成: {video_path}[/bold green]")

    return video_path


def _generate_html(script: dict, image_paths: list[str]) -> str:
    """生成电影级动态 HTML 页面"""
    scenes = script.get("scenes", [])
    title = script.get("title", "视频")
    theme_name = config.VIDEO_THEME
    t = THEMES.get(theme_name, THEMES["dark"])
    total = len(scenes)

    image_b64_list = []
    for path in image_paths:
        if path and os.path.exists(path):
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
                ext = Path(path).suffix.lower()
                mime = "image/png" if ext == ".png" else "image/jpeg"
                image_b64_list.append(f"data:{mime};base64,{b64}")
        else:
            image_b64_list.append("")

    total_duration = sum(s.get("duration", 5) for s in scenes)

    # 生成每个场景 HTML
    scenes_html_parts = []
    for i, scene in enumerate(scenes):
        stype = scene.get("type", "content")
        overlay = scene.get("text_overlay", "")
        narration = scene.get("narration", "")
        num = f"{i+1:02d}"

        bg = image_b64_list[i] if i < len(image_b64_list) else ""
        if bg:
            bg_div = f'<div class="bg-img" style="background-image:url(\'{bg}\')"></div>'
        else:
            bg_div = '<div class="bg-gradient"></div>'

        if stype == "opening":
            inner = f'''<div class="scene-num">{num}</div>
            <div class="title-main">{overlay or narration}</div>
            <div class="accent-line"></div>
            <div class="title-sub">{narration if overlay else ""}</div>'''
        elif stype == "closing":
            inner = f'''<div class="scene-num">{num}</div>
            <div class="title-main end-title">{overlay or narration}</div>
            <div class="accent-line"></div>
            <div class="title-sub">{narration if overlay else "感谢观看"}</div>'''
        else:
            inner = f'''<div class="scene-num">{num}</div>
            <div class="title-main content-title">{overlay}</div>
            <div class="accent-line"></div>
            <div class="narration-text">{narration if narration != overlay else ""}</div>'''

        scenes_html_parts.append(
            f'<div class="scene" id="sc-{i}">{bg_div}<div class="scene-inner">{inner}</div></div>'
        )
    scenes_html = "\n".join(scenes_html_parts)

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:{config.VIDEO_WIDTH}px;height:{config.VIDEO_HEIGHT}px;overflow:hidden;
  font-family:"Microsoft YaHei","PingFang SC",sans-serif;
  background:{t["bg"]};color:{t["text"]}}}
#app{{width:100%;height:100%;position:relative}}

/* 粒子画布 */
#particles{{position:absolute;top:0;left:0;width:100%;height:100%;z-index:0;opacity:0.6}}

/* 场景 */
.scene{{position:absolute;top:0;left:0;width:100%;height:100%;
  opacity:0;transform:scale(1.02);transition:opacity 0.8s,transform 0.8s;pointer-events:none;z-index:1}}
.scene.active{{opacity:1;transform:scale(1);pointer-events:auto}}
.scene.exit{{opacity:0;transform:scale(0.98);transition:opacity 0.4s,transform 0.4s}}

/* 背景 */
.bg-img{{position:absolute;top:0;left:0;width:100%;height:100%;background-size:cover;background-position:center}}
.bg-img::after{{content:"";position:absolute;inset:0;background:rgba(0,0,0,0.65)}}
.bg-gradient{{position:absolute;inset:0;background:linear-gradient(135deg,{t["bg"]},#1a1a2e 50%,#16213e)}}

/* 所有文字强制白色+强阴影，确保在任意背景上都清晰 */
.scene-inner *{{color:#fff!important}}

/* 内层 */
.scene-inner{{position:relative;z-index:2;display:flex;flex-direction:column;
  align-items:center;justify-content:center;height:100%;padding:80px 120px}}

/* 场景编号 */
.scene-num{{font-size:18px;font-weight:300;letter-spacing:6px;
  margin-bottom:40px;text-transform:uppercase;opacity:0;text-shadow:0 2px 10px rgba(0,0,0,0.8)}}
.scene.active .scene-num{{animation:numIn 0.6s 0.1s both}}

/* 主标题 */
.title-main{{font-size:68px;font-weight:900;letter-spacing:6px;text-align:center;
  text-shadow:0 0 80px {t["glow"]},0 6px 30px rgba(0,0,0,0.9),0 2px 4px rgba(0,0,0,0.8);line-height:1.3;max-width:80%;opacity:0}}
.scene.active .title-main{{animation:titleIn 0.8s 0.3s cubic-bezier(.16,1,.3,1) both}}
.content-title{{font-size:56px}}
.end-title{{font-size:52px}}

/* 装饰线 */
.accent-line{{width:80px;height:3px;background:{t["accent"]};margin:30px 0;border-radius:2px;
  box-shadow:0 0 20px {t["accent"]};opacity:0}}
.scene.active .accent-line{{animation:lineIn 0.6s 0.5s both}}

/* 副标题 */
.title-sub{{font-size:30px;font-weight:300;letter-spacing:3px;
  text-align:center;max-width:70%;line-height:1.5;opacity:0;
  text-shadow:0 3px 15px rgba(0,0,0,0.8)}}
.scene.active .title-sub{{animation:fadeUp 0.7s 0.7s both}}

/* 旁白文本 */
.narration-text{{font-size:28px;font-weight:400;letter-spacing:2px;
  text-align:center;max-width:75%;line-height:1.7;opacity:0;
  text-shadow:0 2px 12px rgba(0,0,0,0.8)}}
.scene.active .narration-text{{animation:fadeUp 0.7s 0.7s both}}

/* 关键帧 */
@keyframes numIn{{from{{opacity:0;transform:translateY(-10px)}}to{{opacity:1;transform:translateY(0)}}}}
@keyframes titleIn{{from{{opacity:0;transform:translateY(30px);filter:blur(8px)}}to{{opacity:1;transform:translateY(0);filter:blur(0)}}}}
@keyframes lineIn{{from{{width:0;opacity:0}}to{{width:80px;opacity:1}}}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(20px)}}to{{opacity:1;transform:translateY(0)}}}}
@keyframes float{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-20px)}}}}
@keyframes pulse-glow{{0%,100%{{box-shadow:0 0 20px {t["glow"]}}}50%{{box-shadow:0 0 40px {t["glow"]},0 0 60px {t["glow"]}}}}}

/* 进度条 */
#progress{{position:absolute;bottom:0;left:0;height:3px;background:{t["progress"]};
  z-index:999;width:0;transition:width 0.5s;box-shadow:0 0 10px {t["accent"]}}}

/* 角标 */
#badge{{position:absolute;bottom:30px;right:40px;font-size:14px;
  color:{t["subtext"]};z-index:999;letter-spacing:3px;opacity:0.5}}
</style>
</head>
<body>
<div id="app">
<canvas id="particles"></canvas>
{scenes_html}
<div id="progress"></div>
<div id="badge">{title}</div>
</div>
<script>
const scenes={json.dumps(scenes,ensure_ascii=False)};
const total={total_duration};let cur=-1;
window.__READY=false;
const starts=[];let acc=0;
scenes.forEach(s=>{{starts.push(acc);acc+=s.duration||5}});

function show(i){{
  if(i===cur)return;
  const p=document.querySelector('.scene.active');
  if(p){{p.classList.add('exit');setTimeout(()=>p.classList.remove('active','exit'),400)}}
  const e=document.getElementById('sc-'+i);
  if(e){{e.classList.add('active');cur=i}}
  document.getElementById('progress').style.width=((starts[i]||0)/total*100)+'%';
}}

// 粒子背景
const cv=document.getElementById('particles');
const ctx=cv.getContext('2d');
cv.width={config.VIDEO_WIDTH};cv.height={config.VIDEO_HEIGHT};
const pts=[];
for(let i=0;i<60;i++){{
  pts.push({{x:Math.random()*cv.width,y:Math.random()*cv.height,
    r:Math.random()*1.5+0.5,vx:(Math.random()-0.5)*0.3,vy:(Math.random()-0.5)*0.3,o:Math.random()*0.5+0.2}});
}}
function anim(){{
  ctx.clearRect(0,0,cv.width,cv.height);
  pts.forEach(p=>{{
    p.x+=p.vx;p.y+=p.vy;
    if(p.x<0)p.x=cv.width;if(p.x>cv.width)p.x=0;
    if(p.y<0)p.y=cv.height;if(p.y>cv.height)p.y=0;
    ctx.beginPath();ctx.arc(p.x,p.y,p.r,0,Math.PI*2);
    ctx.fillStyle=`rgba(255,255,255,${{p.o}})`;ctx.fill();
  }});
  requestAnimationFrame(anim);
}}
anim();

// 时间线
function start(){{
  scenes.forEach((s,i)=>{{setTimeout(()=>show(i),starts[i]*1000)}});
  setTimeout(()=>document.getElementById('progress').style.width='100%',total*1000);
}}
window.addEventListener('DOMContentLoaded',()=>{{
  show(0);
  // 等 Selenium 设置 __READY=true 再启动时间线
  var waitReady=setInterval(()=>{{
    if(window.__READY){{
      clearInterval(waitReady);
      start();
    }}
  }},200);
}});
setTimeout(()=>{{if(!window.__READY)window.__READY=true;}},3000);
</script>
</body>
</html>'''

    html_path = os.path.join(config.TEMP_DIR, "video.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    return html_path


def _convert_to_mp4(webm_path: str, mp4_path: str, audio_path: str = "") -> Optional[str]:
    """
    使用 FFmpeg 将 WebM 转换为 MP4，并合成音频

    Playwright 录制的 WebM 不含音频，此函数将 TTS 生成的配音
    合并到最终视频中。

    Args:
        webm_path: 输入的 .webm 文件路径（无声视频）
        mp4_path: 输出的 .mp4 文件路径
        audio_path: TTS 生成的 .mp3 音频文件路径（可选）

    Returns:
        MP4 文件路径，失败返回 None
    """
    # 规范化为绝对路径
    webm_path = str(Path(webm_path).resolve())
    mp4_path = str(Path(mp4_path).resolve())
    if audio_path:
        audio_path = str(Path(audio_path).resolve())

    # 确保输出路径以 .mp4 结尾
    if not mp4_path.endswith(".mp4"):
        mp4_path = mp4_path.replace(".webm", ".mp4")

    # 检查输入文件是否存在
    if not os.path.exists(webm_path):
        console.print(f"[red]源视频文件不存在: {webm_path}[/red]")
        return None

    if audio_path and not os.path.exists(audio_path):
        console.print(f"[yellow]⚠️  音频文件不存在: {audio_path}，生成无声视频[/yellow]")
        audio_path = ""
    if audio_path and os.path.getsize(audio_path) < 100:
        console.print(f"[yellow]⚠️  音频文件太小（{os.path.getsize(audio_path)}字节），生成无声视频[/yellow]")
        audio_path = ""

    # 检查 ffmpeg 是否可用
    if not shutil.which("ffmpeg"):
        console.print("[yellow]⚠️  未找到 ffmpeg，跳过 MP4 转换[/yellow]")
        console.print("[dim]  安装: winget install ffmpeg  或  choco install ffmpeg[/dim]")
        return None

    has_audio = bool(audio_path)
    if has_audio:
        console.print(f"🔄 [cyan]正在合成视频 + 配音 → MP4...[/cyan]")
    else:
        console.print(f"🔄 [cyan]正在转换 WebM → MP4（无声）...[/cyan]")

    console.print(f"   [dim]视频: {webm_path}[/dim]")
    if has_audio:
        console.print(f"   [dim]音频: {audio_path}[/dim]")
    console.print(f"   [dim]输出: {mp4_path}[/dim]")

    try:
        if has_audio:
            cmd = [
                "ffmpeg",
                "-i", webm_path,
                "-i", audio_path,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "22",
                "-c:a", "aac",
                "-b:a", "192k",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-map", "0:v:0",       # 取第一个文件的视频流
                "-map", "1:a:0",       # 取第二个文件的音频流
                "-filter:a", "apad",   # 音频不够长时自动填充静音
                "-shortest",           # 视频流结束时停止
                "-y",
                mp4_path
            ]
        else:
            cmd = [
                "ffmpeg",
                "-i", webm_path,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "22",
                "-c:a", "aac",
                "-b:a", "192k",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-y",
                mp4_path
            ]

        # 调试：显示完整命令
        console.print(f"   [dim]命令: {' '.join(cmd)}[/dim]")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600
        )

        if result.returncode == 0 and os.path.exists(mp4_path):
            # 删除原始 WebM
            os.remove(webm_path)
            console.print(f"✅ [green]MP4 生成完成: {mp4_path}[/green]")
            if has_audio:
                console.print(f"   [green]🔊 已合成配音[/green]")
            return mp4_path
        else:
            console.print(f"[red]FFmpeg 转换失败 (exit code: {result.returncode})[/red]")
            if result.stderr:
                lines = result.stderr.strip().split("\n")
                for line in lines[-20:]:
                    console.print(f"[dim]  {line}[/dim]")
            return None

    except subprocess.TimeoutExpired:
        console.print("[red]FFmpeg 转换超时 (>10分钟)[/red]")
        return None
    except Exception as e:
        console.print(f"[red]转换异常: {e}[/red]")
        return None


def convert_webm_to_mp4(webm_path: str, mp4_path: str = None, audio_path: str = "") -> Optional[str]:
    """
    独立的 WebM → MP4 转换函数（可在外部调用）

    Args:
        webm_path: .webm 文件路径
        mp4_path: 输出路径（可选，默认替换扩展名）
        audio_path: 配音 .mp3 路径（可选，用于合成音频）

    Returns:
        MP4 文件路径，失败返回 None
    """
    if mp4_path is None:
        mp4_path = webm_path.replace(".webm", ".mp4")
    return _convert_to_mp4(webm_path, mp4_path, audio_path)


def _record_video(html_path: str, script: dict, audio_path: str, output_filename: str = None) -> str:
    """录制视频（支持 Playwright 或 Selenium）"""
    engine = config.RECORD_ENGINE.lower()
    if engine == "selenium":
        return _record_with_selenium(html_path, script, audio_path, output_filename)
    return _record_with_playwright(html_path, script, audio_path, output_filename)


def _record_with_selenium(html_path: str, script: dict, audio_path: str, output_filename: str = None) -> str:
    """Selenium + Xvfb 录制"""
    from modules.selenium_recorder import record_with_selenium

    total_duration = sum(s.get("duration", 5) for s in script["scenes"])
    video_dir = str(Path(config.VIDEO_OUTPUT_DIR).resolve())
    os.makedirs(video_dir, exist_ok=True)

    if output_filename is None:
        safe_title = "".join(c if c.isalnum() or c in "._- " else "_" for c in script.get("title", "video"))[:30]
        output_filename = f"{safe_title}.mp4"

    webm_result = record_with_selenium(html_path, video_dir, total_duration + 3)
    if not webm_result:
        return html_path

    mp4_target = os.path.join(video_dir, output_filename)
    # -ss 1 裁掉开头 1 秒，和音频对齐
    mp4_result = _convert_to_mp4(webm_result, mp4_target, audio_path)
    return mp4_result if mp4_result else webm_result


def _record_with_playwright(html_path: str, script: dict, audio_path: str, output_filename: str = None) -> str:
    from playwright.sync_api import sync_playwright

    if output_filename is None:
        safe_title = "".join(
            c if c.isalnum() or c in "._- " else "_"
            for c in script.get("title", "video")
        )[:30]
        output_filename = f"{safe_title}.mp4"

    video_dir = str(Path(config.VIDEO_OUTPUT_DIR).resolve())
    os.makedirs(video_dir, exist_ok=True)
    video_path = os.path.join(video_dir, output_filename)

    # 计算总时长
    total_duration = sum(s.get("duration", 5) for s in script["scenes"])

    console.print(f"⏱️  预计视频时长: {total_duration:.0f} 秒")
    console.print(f"🎥 正在录制视频... (此过程将持续 {total_duration:.0f}+ 秒)")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                f"--window-size={config.VIDEO_WIDTH},{config.VIDEO_HEIGHT}",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-blink-features=AutomationControlled",
            ]
        )

        context = browser.new_context(
            viewport={"width": config.VIDEO_WIDTH, "height": config.VIDEO_HEIGHT},
            record_video_dir=video_dir,
            record_video_size={"width": config.VIDEO_WIDTH, "height": config.VIDEO_HEIGHT},
        )

        page = context.new_page()

        # 加载 HTML
        file_url = f"file:///{html_path.replace(chr(92), '/')}"
        page.goto(file_url, wait_until="networkidle")

        # 启动 JS 时间线
        page.evaluate("window.__READY = true;")

        # 等待整个动画完成
        wait_ms = int((total_duration + 1) * 1000)
        with Progress() as progress:
            task = progress.add_task("[cyan]录制中...[/cyan]", total=wait_ms // 1000)
            for _ in range(wait_ms // 1000):
                time.sleep(1)
                progress.advance(task)

        # 停止录制
        context.close()
        browser.close()

    # Playwright 默认生成 .webm，查找生成的文件
    output_files = list(Path(video_dir).glob("*.webm"))
    if output_files:
        latest = max(output_files, key=os.path.getmtime)
        webm_path = video_path.replace(".mp4", ".webm")
        if latest.resolve() != Path(webm_path):
            if os.path.exists(webm_path):
                os.remove(webm_path)
            os.rename(str(latest), webm_path)
        console.print(f"✅ [green]WebM 录制完成: {webm_path}[/green]")

        # 自动转换为 MP4（并合成音频）
        mp4_path = _convert_to_mp4(str(webm_path), video_path, audio_path)
        return mp4_path if mp4_path else str(webm_path)

    console.print("[red]未找到录制的视频文件[/red]")
    return html_path

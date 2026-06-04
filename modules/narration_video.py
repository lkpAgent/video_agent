"""
口播叙述视频模式：用户输入一段话 → 逐句拆分 → TTS配音 → 口播风格视频

页面布局：
┌──────────────────────────────┐
│         视频标题              │
├──────────────────────────────┤
│                              │
│    "当前正在念的句子..."     │
│    ▁▂▃▄▅▆▇ 音波动画         │
│                              │
├──────────────────────────────┤
│  [头像]  用户名              │
│           公司 · Slogan      │
└──────────────────────────────┘
"""

import os
import re
import json
import time
import base64
import asyncio
import shutil
from pathlib import Path
from rich.console import Console
from rich.progress import Progress

from config import config

console = Console()


def split_sentences(text: str) -> list[str]:
    """
    智能拆句：按中英文标点拆分
    """
    # 先按常见标点拆分
    raw = re.split(r'(?<=[。！？；\n\.\!\?;])', text)
    sentences = []
    for s in raw:
        s = s.strip()
        if len(s) >= 2:  # 过滤太短的
            sentences.append(s)

    # 合并过短的句子到前一句
    merged = []
    for s in sentences:
        if merged and len(s) < 6:
            merged[-1] += s
        else:
            merged.append(s)

    console.print(f"📝 拆分为 [cyan]{len(merged)}[/cyan] 个句子")
    for i, s in enumerate(merged, 1):
        preview = s[:50] + "..." if len(s) > 50 else s
        console.print(f"   [dim]{i}. {preview}[/dim]")

    return merged


async def _generate_sentence_audio(text: str, output_path: str, voice: str):
    """为单个句子生成 TTS 配音"""
    import edge_tts
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=config.TTS_RATE,
        pitch=config.TTS_PITCH
    )
    await communicate.save(output_path)


def generate_narration_audio(sentences: list[str]) -> list[dict]:
    """
    逐句生成音频 + ffprobe 测真实时长 → 精准同步
    """
    from modules.tts import tts_generate

    provider = config.TTS_PROVIDER.lower()
    provider_name = {"elevenlabs": "ElevenLabs 克隆", "doubao": "豆包声音复刻"}.get(provider, "Edge TTS")
    console.print(f"\n🔊 [bold green]正在生成口播配音 ({provider_name})...[/bold green]")

    audio_dir = os.path.join(config.TEMP_DIR, "narration_audio")
    os.makedirs(audio_dir, exist_ok=True)

    audio_data = []
    audio_files = []
    for i, s in enumerate(sentences):
        path = os.path.join(audio_dir, f"s_{i+1:02d}.mp3")
        tts_generate(s, path)

        dur = _get_mp3_duration(path)
        console.print(f"   [dim]ffprobe 实测: {dur:.2f}s, 字数估算: {len(s)/4:.1f}s[/dim]")
        if dur <= 0:
            dur = len(s) / 4.0
            console.print(f"   [yellow]ffprobe 失败，用字数估算: {dur:.1f}s[/yellow]")
        dur = max(1.5, round(dur + 0.5, 1))  # +0.5秒缓冲，对齐实际播放

        audio_data.append({"path": path, "text": s, "duration": dur})
        audio_files.append(path)
        console.print(f"   [{i+1}/{len(sentences)}] {dur:.1f}s | {s[:30]}...")

    full_path = os.path.join(audio_dir, "narration_full.mp3")
    _merge_narration_audio(audio_files, full_path)

    total = sum(d["duration"] for d in audio_data)
    console.print(f"✅ [green]配音完成，总时长 {total:.1f} 秒[/green]\n")
    return audio_data


def _get_mp3_duration(path: str) -> float:
    """用 ffprobe 获取 MP3 时长"""
    import subprocess
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path
        ], capture_output=True, text=True, timeout=10)
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def _merge_narration_audio(audio_paths: list[str], output_path: str):
    """用 ffmpeg 合并所有句子音频"""
    import subprocess

    valid = [p for p in audio_paths if os.path.exists(p)]
    if not valid:
        console.print("[red]没有有效的音频文件可合并[/red]")
        return
    if len(valid) == 1:
        import shutil
        shutil.copy(valid[0], output_path)
        console.print(f"   音频合并（单段）: {output_path}")
        return

    console.print(f"   正在合并 {len(valid)} 段音频...")

    list_content = ""
    for p in valid:
        escaped = p.replace("\\", "/").replace("'", "\\'")
        list_content += f"file '{escaped}'\n"

    list_file = valid[0] + ".narration.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        f.write(list_content)

    try:
        result = subprocess.run([
            "ffmpeg", "-f", "concat", "-safe", "0",
            "-i", list_file, "-c:a", "libmp3lame", "-q:a", "2",
            "-y", output_path
        ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)

        if result.returncode != 0:
            console.print(f"[red]音频合并失败: {result.stderr[:300]}[/red]")
        else:
            console.print(f"   音频合并完成: {output_path}")
    except Exception as e:
        console.print(f"[red]音频合并异常: {e}[/red]")
    finally:
        if os.path.exists(list_file):
            os.remove(list_file)


def generate_narration_html(
    title: str,
    audio_data: list[dict],
    background_image: str,
    narrator_name: str,
    narrator_avatar: str,
    company: str,
    slogan: str
) -> str:
    """
    生成口播风格的动态 HTML 页面
    """
    # 总时长精确匹配音频时长（不要多余缓冲）
    total = round(sum(a["duration"] for a in audio_data), 1)
    audio_json = json.dumps(audio_data, ensure_ascii=False)

    # 头像处理
    avatar_b64 = ""
    if narrator_avatar and os.path.exists(narrator_avatar):
        with open(narrator_avatar, "rb") as f:
            ext = Path(narrator_avatar).suffix.lower()
            mime = "image/png" if ext == ".png" else "image/jpeg"
            avatar_b64 = f"data:{mime};base64,{base64.b64encode(f.read()).decode()}"

    # 背景图
    bg_b64 = ""
    if background_image and os.path.exists(background_image):
        with open(background_image, "rb") as f:
            ext = Path(background_image).suffix.lower()
            mime = "image/png" if ext == ".png" else "image/jpeg"
            bg_b64 = f"data:{mime};base64,{base64.b64encode(f.read()).decode()}"

    # 默认头像 SVG
    if not avatar_b64:
        avatar_b64 = f"data:image/svg+xml," + (
            "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E"
            "%3Ccircle cx='50' cy='50' r='50' fill='%236366f1'/%3E"
            "%3Ctext x='50' y='65' text-anchor='middle' fill='white' font-size='40' font-family='sans-serif'%3E"
            f"{narrator_name[0] if narrator_name else 'U'}"
            "%3C/text%3E%3C/svg%3E"
        )

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:{config.VIDEO_WIDTH}px;height:{config.VIDEO_HEIGHT}px;overflow:hidden;
  font-family:"Microsoft YaHei","PingFang SC",sans-serif;
  background:#0a0a14;color:#fff}}

#app{{width:100%;height:100%;position:relative;display:flex;flex-direction:column}}

/* 背景 */
#bg{{position:absolute;inset:0;background-size:cover;background-position:center;z-index:0}}
#bg::after{{content:"";position:absolute;inset:0;
  background:linear-gradient(180deg,rgba(10,10,20,0.75) 0%,rgba(10,10,20,0.5) 50%,rgba(10,10,20,0.85) 100%)}}

/* 内容层 */
#content{{position:relative;z-index:1;flex:1;display:flex;flex-direction:column;
  align-items:center;justify-content:center;padding:60px 100px}}

/* 标题 */
#title{{font-size:28px;font-weight:400;letter-spacing:6px;color:rgba(255,255,255,0.6);
  text-align:center;margin-bottom:60px;text-transform:uppercase}}

/* 句子区 */
#sentence-area{{text-align:center;min-height:180px;display:flex;flex-direction:column;
  align-items:center;justify-content:center;margin-bottom:40px}}
#sentence{{font-size:42px;font-weight:600;letter-spacing:3px;line-height:1.5;
  max-width:80%;transition:opacity 0.4s;text-shadow:0 0 40px rgba(255,255,255,0.15)}}
.sentence-enter{{animation:senIn 0.5s ease-out}}
@keyframes senIn{{from{{opacity:0;transform:translateY(15px)}}to{{opacity:1;transform:translateY(0)}}}}

/* 音波 */
#waveform{{display:flex;align-items:flex-end;justify-content:center;gap:4px;height:50px;margin-top:30px}}
.wave-bar{{width:5px;border-radius:3px;background:linear-gradient(180deg,#6366f1,#a855f7);
  transition:height 0.15s ease;min-height:6px}}
.wave-bar.active{{animation:wavy 0.6s ease-in-out infinite}}
.wave-bar:nth-child(odd){{animation-delay:0.1s}}
.wave-bar:nth-child(even){{animation-delay:0.3s}}
@keyframes wavy{{0%,100%{{height:10px}}50%{{height:40px}}}}

/* 底部个人信息 */
#profile{{display:flex;align-items:center;gap:20px;padding:30px 80px;flex-shrink:0;
  background:rgba(0,0,0,0.3);backdrop-filter:blur(10px);
  border-top:1px solid rgba(255,255,255,0.08)}}
#avatar{{width:60px;height:60px;border-radius:50%;overflow:hidden;
  border:2px solid rgba(255,255,255,0.3);flex-shrink:0}}
#avatar img{{width:100%;height:100%;object-fit:cover}}
#profile-info{{display:flex;flex-direction:column;gap:4px}}
#profile-name{{font-size:20px;font-weight:600;letter-spacing:2px}}
#profile-company{{font-size:14px;color:rgba(255,255,255,0.5);letter-spacing:2px;
  display:flex;align-items:center;gap:10px}}
#profile-company .dot{{width:4px;height:4px;border-radius:50%;background:rgba(255,255,255,0.3)}}

/* 进度条 */
#progress{{position:absolute;top:0;left:0;height:2px;
  background:linear-gradient(90deg,#6366f1,#a855f7,#ec4899);
  z-index:99;width:0;transition:width 0.3s}}
</style>
</head>
<body>
<div id="app">
<div id="bg" style="background-image:url('{bg_b64}')"></div>
<div id="progress"></div>

<div id="content">
  <div id="title">{title}</div>
  <div id="sentence-area">
    <div id="sentence"></div>
    <div id="waveform"></div>
  </div>
</div>

<div id="profile">
  <div id="avatar"><img src="{avatar_b64}" alt="avatar"></div>
  <div id="profile-info">
    <div id="profile-name">{narrator_name}</div>
    <div id="profile-company">
      {company}<span class="dot"></span>{slogan}
    </div>
  </div>
</div>
</div>

<script>
const data={audio_json};
const total={total};
const barCount=50;
window.__READY=false;

// 生成音波条
const wf=document.getElementById('waveform');
for(let i=0;i<barCount;i++){{
  const bar=document.createElement('div');
  bar.className='wave-bar';
  bar.style.animationDelay=(Math.random()*0.5)+'s';
  wf.appendChild(bar);
}}

// 时间线
let times=[];
let acc=0;
data.forEach(d=>{{times.push(acc);acc+=d.duration}});

const senEl=document.getElementById('sentence');
const bars=document.querySelectorAll('.wave-bar');
const prog=document.getElementById('progress');

function showSentence(idx){{
  if(idx>=data.length)return;
  if(idx===window._curScene)return;
  window._curScene=idx;
  senEl.textContent=data[idx].text;
  senEl.classList.remove('sentence-enter');
  void senEl.offsetWidth;
  senEl.classList.add('sentence-enter');
  prog.style.width=((times[idx]/total)*100)+'%';

  // 音波动起来
  bars.forEach(b=>b.classList.add('active'));
}}

function stopWave(){{
  bars.forEach(b=>b.classList.remove('active'));
}}

// 初始显示第一句
showSentence(0);

// 等 Selenium 设 __READY=true 再启动切换
var _waitReady=setInterval(()=>{{
  if(window.__READY){{
    clearInterval(_waitReady);
    data.forEach((d,i)=>{{
      setTimeout(()=>showSentence(i),times[i]*1000);
      setTimeout(()=>stopWave(),(times[i]+d.duration)*1000-200);
    }});
    setTimeout(()=>prog.style.width='100%',total*1000);
  }}
}},200);
// 兜底：2 秒后还没收到标志就自动启动（防止录制器 bug 导致永远卡住）
setTimeout(()=>{{if(!window.__READY)window.__READY=true;}},2000);
</script>
</body>
</html>'''

    html_path = os.path.join(config.TEMP_DIR, "narration_video.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    return html_path


def record_narration_video(html_path: str, output_filename: str = None) -> str:
    """录制口播视频（自动选择引擎）"""
    engine = config.RECORD_ENGINE.lower()
    # Windows 没有 Xvfb，强制 Playwright
    if engine == "selenium" and not shutil.which("Xvfb"):
        console.print("[yellow]Windows 不支持 Selenium 录制，回退 Playwright[/yellow]")
        engine = "playwright"
    if engine == "selenium":
        return _record_narration_selenium(html_path, output_filename)
    else:
        return _record_narration_playwright(html_path, output_filename)


def _record_narration_selenium(html_path: str, output_filename: str = None) -> str:
    """Selenium + Xvfb 录制口播，用 ffmpeg filter 直接拼多段音频"""
    from modules.selenium_recorder import record_with_selenium
    import subprocess

    if output_filename is None:
        output_filename = "narration.mp4"

    video_dir = str(Path(config.VIDEO_OUTPUT_DIR).resolve())
    os.makedirs(video_dir, exist_ok=True)
    video_path = os.path.join(video_dir, output_filename)

    total_duration = 30
    console.print("📹 [cyan]Selenium 录制口播视频...[/cyan]")
    webm_result = record_with_selenium(html_path, video_dir, total_duration + 5)
    if not webm_result:
        return html_path

    # 找所有逐句音频
    audio_dir = Path(config.TEMP_DIR).resolve() / "narration_audio"
    audio_files = sorted(audio_dir.glob("s_*.mp3"))

    if audio_files:
        console.print(f"🔊 找到 {len(audio_files)} 个音频片段，用 ffmpeg filter 合并...")
        mp4_result = os.path.join(video_dir, output_filename)

        # 用 filter_complex concat 代替 concat demuxer，更可靠
        inputs = []
        filters = []
        for f in audio_files:
            inputs.extend(["-i", str(f)])
            filters.append(f"[{len(inputs)//2}:a]")

        filter_str = "".join(filters) + f"concat=n={len(audio_files)}:v=0:a=1[outa]"

        cmd = [
            "ffmpeg", "-i", webm_result,
            *inputs,
            "-filter_complex", filter_str,
            "-map", "0:v", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-shortest", "-y", mp4_result
        ]
        console.print(f"   [dim]ffmpeg filter concat {len(audio_files)} 段音频[/dim]")

        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=600)
        if result.returncode == 0 and os.path.exists(mp4_result):
            os.remove(webm_result)
            console.print(f"✅ [green]MP4 生成完成（有声音）: {mp4_result}[/green]")
            return mp4_result
        else:
            console.print(f"[red]ffmpeg 合并失败: {result.stderr[-300:]}[/red]")

    else:
        console.print("[yellow]⚠️ 未找到逐句音频文件，生成无声视频[/yellow]")

    return str(webm_result)


def _record_narration_playwright(html_path: str, output_filename: str = None) -> str:
    """录制口播视频 + 合成音频"""
    from playwright.sync_api import sync_playwright
    import subprocess

    if output_filename is None:
        # 用标题做文件名
        safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in title)[:30]
        output_filename = f"{safe}.mp4"

    video_dir = str(Path(config.VIDEO_OUTPUT_DIR).resolve())
    os.makedirs(video_dir, exist_ok=True)
    video_path = os.path.join(video_dir, output_filename)

    # 从 HTML 中估算时长（通过读取 audio_data）
    # 这里用简单方式：从 HTML 文件名推断时长
    total_duration = 30  # 默认，实际由 audio_data 控制

    console.print(f"🎥 正在录制口播视频...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                f"--window-size={config.VIDEO_WIDTH},{config.VIDEO_HEIGHT}",
                "--autoplay-policy=no-user-gesture-required",
            ]
        )
        context = browser.new_context(
            viewport={"width": config.VIDEO_WIDTH, "height": config.VIDEO_HEIGHT},
            record_video_dir=video_dir,
            record_video_size={"width": config.VIDEO_WIDTH, "height": config.VIDEO_HEIGHT},
        )
        page = context.new_page()
        file_url = f"file:///{html_path.replace(chr(92), '/')}"
        page.goto(file_url, wait_until="networkidle")

        # 设 __READY 启动 JS 时间线
        page.evaluate("window.__READY = true;")

        # 从页面获取总时长
        try:
            total_duration = page.evaluate("() => total") + 2
        except Exception:
            total_duration = 30

        console.print(f"⏱️  预计时长: {total_duration:.0f} 秒")

        wait_ms = int((total_duration + 2) * 1000)
        with Progress() as progress:
            task = progress.add_task("[cyan]录制中...[/cyan]", total=wait_ms // 1000)
            for _ in range(wait_ms // 1000):
                time.sleep(1)
                progress.advance(task)

        context.close()
        browser.close()

    # 找到录制的 webm
    output_files = list(Path(video_dir).glob("*.webm"))
    if output_files:
        latest = max(output_files, key=os.path.getmtime)
        webm_path = str(Path(video_path.replace(".mp4", ".webm")).resolve())
        if latest.resolve() != Path(webm_path):
            # Windows 下用 replace 覆盖已有文件
            if os.path.exists(webm_path):
                os.remove(webm_path)
            os.rename(str(latest), webm_path)
        console.print(f"✅ WebM 录制完成: {webm_path}")

        # 合成音频：用逐句 s_*.mp3 直接合并，不再依赖 narration_full.mp3
        audio_dir = Path(config.TEMP_DIR).resolve() / "narration_audio"
        audio_files = sorted(audio_dir.glob("s_*.mp3"))

        if audio_files:
            mp4_path = str(Path(video_path).resolve())

            # 检查 ffmpeg 是否可用
            if not shutil.which("ffmpeg"):
                console.print("[red]❌ 找不到 ffmpeg！请安装: winget install ffmpeg[/red]")
                return str(webm_path)

            console.print(f"🔄 正在合成视频 + {len(audio_files)} 段配音 → MP4...")

            inputs = []
            filters = []
            for f in audio_files:
                inputs.extend(["-i", str(f)])
                filters.append(f"[{len(inputs)//2}:a]")
            filter_str = "".join(filters) + f"concat=n={len(audio_files)}:v=0:a=1[outa]"

            cmd = [
                "ffmpeg", "-i", webm_path,
                *inputs,
                "-filter_complex", filter_str,
                "-map", "0:v", "-map", "[outa]",
                "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-shortest", "-y", mp4_path
            ]

            result = subprocess.run(cmd, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=600)
            if result.returncode == 0 and os.path.exists(mp4_path):
                os.remove(webm_path)
                console.print(f"✅ [green]MP4 生成完成: {mp4_path}[/green]")
                return mp4_path
            else:
                console.print(f"[red]合并失败: {result.stderr[-300:]}[/red]")

        else:
            console.print("[yellow]⚠️ 未找到逐句音频，生成无声视频[/yellow]")

        return str(webm_path)

    console.print("[red]未找到录制文件[/red]")
    return html_path

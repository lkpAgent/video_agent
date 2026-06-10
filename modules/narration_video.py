"""
口播叙述视频模式：用户输入一段话 → 逐句拆分 → TTS配音 → 口播风格视频

页面布局：
┌──────────────────────────────┐
│         视频标题              │
├──────────────────────────────┤
│                              │
│    "当前正在念的句子..."     │
│                              │
├──────────────────────────────┤
│  [头像]  用户名              │
│           Slogan             │
│           ▁▂▃▄▅▆▇ 音波动画  │
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
    raw = re.split(r'(?<=[。！？\n\.\!\?])', text)
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


def generate_narration_audio(sentences: list[str], voice_id: str = "", voice_type: int = 1) -> list[dict]:
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
        tts_generate(s, path, voice_id, voice_type)

        dur = _get_mp3_duration(path)
        console.print(f"   [dim]ffprobe 实测: {dur:.2f}s, 字数估算: {len(s)/4:.1f}s[/dim]")
        if dur <= 0:
            dur = len(s) / 4.0
            console.print(f"   [yellow]ffprobe 失败，用字数估算: {dur:.1f}s[/yellow]")
        dur = max(1.5, round(dur, 3))

        audio_data.append({"path": path, "text": s, "duration": dur})
        audio_files.append(path)
        console.print(f"   [{i+1}/{len(sentences)}] {dur:.1f}s | {s[:30]}...")

    full_path = os.path.join(audio_dir, "narration_full.mp3")
    _merge_narration_audio(audio_files, full_path)

    # 完整合并音频仅用于校验总时长。页面切换必须使用每句音频的实测时长，
    # 不能按字数比例重新分配，否则语速、停顿差异会造成逐页累计误差。
    real_total = _get_mp3_duration(full_path)
    if real_total <= 0:
        real_total = sum(d["duration"] for d in audio_data)
    measured_total = sum(d["duration"] for d in audio_data)
    console.print(
        f"   [dim]逐句实测合计: {measured_total:.3f}s，合并音频: {real_total:.3f}s[/dim]"
    )

    console.print(f"✅ [green]配音完成，真实总时长 {real_total:.1f} 秒[/green]\n")
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
    # 加 2 秒缓冲，确保视频不早于音频结束
    total = round(sum(a["duration"] for a in audio_data) + 2, 1)
    audio_json = json.dumps(audio_data, ensure_ascii=False)

    # 头像处理
    avatar_b64 = ""
    if narrator_avatar:
        # 兼容 URL 路径和文件路径
        av_path = narrator_avatar
        if av_path.startswith("/static/"):
            av_path = str(Path(av_path.lstrip("/")))
        if os.path.exists(av_path):
            with open(av_path, "rb") as f:
                ext = Path(av_path).suffix.lower()
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

#app{{width:100%;height:100%;position:relative}}

/* 背景 */
#bg{{position:absolute;inset:0;background-size:cover;background-position:center;z-index:0}}
#bg::after{{content:"";position:absolute;inset:0;
  background:linear-gradient(180deg,rgba(10,10,20,0.75) 0%,rgba(10,10,20,0.5) 50%,rgba(10,10,20,0.85) 100%)}}

/* 内容层 */
#content{{position:relative;z-index:1;width:100%;height:100%;
  padding:0 60px}}

/* 标题：向页面中部靠拢 */
#title{{position:absolute;top:29%;left:50%;transform:translate(-50%,-50%);
  font-size:48px;font-weight:700;letter-spacing:4px;color:rgba(255,255,255,0.7);
  text-align:center;width:calc(100% - 200px);max-width:880px;line-height:1.35;
  white-space:normal;overflow-wrap:anywhere;word-break:break-word}}

/* 句子区：1/2 处 */
#sentence-area{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
  text-align:center;display:flex;flex-direction:column;align-items:center;width:100%}}
#sentence{{font-size:52px;font-weight:700;letter-spacing:3px;line-height:1.4;
  width:100%;max-width:100%;
  transition:opacity 0.4s;text-shadow:0 0 40px rgba(255,255,255,0.15)}}
.sentence-line{{display:block;width:100%;white-space:normal;overflow-wrap:normal;
  word-break:normal;text-wrap:balance}}
.sentence-enter{{animation:senIn 0.5s ease-out}}
.deterministic-render #sentence{{animation:none!important;opacity:1!important;transform:none!important}}
@keyframes senIn{{from{{opacity:0;transform:translateY(15px)}}to{{opacity:1;transform:translateY(0)}}}}

/* 音波 */
#waveform{{display:flex;align-items:flex-end;justify-content:flex-start;gap:4px;height:50px;margin-top:16px}}
.wave-bar{{width:5px;border-radius:3px;background:linear-gradient(180deg,#6366f1,#a855f7);
  transition:height 0.15s ease;min-height:6px}}
.wave-bar.active{{animation:wavy 0.6s ease-in-out infinite}}
.wave-bar:nth-child(odd){{animation-delay:0.1s}}
.wave-bar:nth-child(even){{animation-delay:0.3s}}
@keyframes wavy{{0%,100%{{height:10px}}50%{{height:40px}}}}

/* 个人信息区：向页面中部靠拢 */
#profile{{position:absolute;top:70%;left:50%;transform:translate(-50%,-50%);
  display:flex;align-items:center;justify-content:center;gap:40px;width:100%;text-align:center}}
#profile-left{{display:flex;flex-direction:column;align-items:center;gap:10px;flex-shrink:0}}
#avatar{{width:100px;height:100px;border-radius:50%;overflow:hidden;
  border:3px solid rgba(255,255,255,0.4);box-shadow:0 0 30px rgba(99,102,241,0.3)}}
#avatar img{{width:100%;height:100%;object-fit:cover}}
#profile-name{{font-size:26px;font-weight:600;letter-spacing:2px;text-align:center;color:rgba(255,255,255,0.9)}}
#profile-right{{display:flex;flex-direction:column;align-items:center;gap:8px;flex:none}}
#profile-slogan{{font-size:28px;font-weight:500;color:rgba(255,255,255,0.82);letter-spacing:2px}}

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
  </div>
  <div id="profile">
    <div id="profile-left">
      <div id="avatar"><img src="{avatar_b64}" alt="avatar"></div>
      <div id="profile-name">{narrator_name}</div>
    </div>
    <div id="profile-right">
      <div id="profile-slogan">{slogan}</div>
      <div id="waveform"></div>
    </div>
  </div>
</div>
</div>

<script>
const data={audio_json};
const total={total};
const barCount=50;
const visualSwitchDelay=0.35;
window.__READY=false;
window.__timelineData=data;
window.__timelineTotal=total;
window.__visualSwitchDelay=visualSwitchDelay;

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
const timelineTimers=[];

function setSentenceText(text){{
  const rawText=String(text ?? '');
  senEl.replaceChildren();
  rawText.split('\\n').forEach(line=>{{
    const lineEl=document.createElement('div');
    lineEl.className='sentence-line';
    lineEl.textContent=line || '\\u00a0';
    senEl.appendChild(lineEl);
  }});
  senEl.dataset.rawText=rawText;
  return rawText;
}}
window.__setSentenceText=setSentenceText;
window.__getSentenceText=()=>senEl.dataset.rawText || '';

function showSentence(idx){{
  if(idx>=data.length)return;
  if(idx===window._curScene)return;
  window._curScene=idx;
  setSentenceText(data[idx].text);
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

// 等录制器设 __READY=true 再启动切换
let timelineStarted=false;
function startTimeline(){{
  if(timelineStarted)return;
  timelineStarted=true;
  data.forEach((d,i)=>{{
    timelineTimers.push(setTimeout(()=>showSentence(i),(times[i]+(i===0?0:visualSwitchDelay))*1000));
    timelineTimers.push(setTimeout(()=>stopWave(),(times[i]+d.duration)*1000-200));
  }});
  timelineTimers.push(setTimeout(()=>prog.style.width='100%',total*1000));
}}

window.__stopTimeline=()=>{{
  timelineTimers.forEach(clearTimeout);
  timelineTimers.length=0;
  clearInterval(_waitReady);
  timelineStarted=true;
  window.__READY=false;
}};

window.__renderAt=(seconds)=>{{
  document.body.classList.add('deterministic-render');
  let idx=0;
  for(let i=1;i<times.length;i++){{
    if(seconds>=times[i]+visualSwitchDelay)idx=i;
    else break;
  }}
  showSentence(idx);
  return idx;
}};

window.__renderSentence=(idx)=>{{
  document.body.classList.add('deterministic-render');
  window._curScene=idx;
  setSentenceText(data[idx].text);
  senEl.classList.remove('sentence-enter');
  senEl.style.animation='none';
  senEl.style.opacity='1';
  senEl.style.transform='none';
  prog.style.width=((times[idx]/total)*100)+'%';
  return window.__getSentenceText();
}};

window.__renderWave=(phase)=>{{
  bars.forEach((bar,i)=>{{
    bar.style.animation='none';
    const wave=Math.sin(phase+i*0.72);
    const pulse=Math.sin(phase*1.7+i*0.31);
    bar.style.height=(10+Math.abs(wave)*22+Math.abs(pulse)*8)+'px';
  }});
}};

var _waitReady=setInterval(()=>{{
  if(window.__READY){{
    clearInterval(_waitReady);
    startTimeline();
  }}
}},200);
// 仅用于手动打开 HTML 预览；服务器录制器会更早设置 __READY。
setTimeout(()=>{{if(!window.__READY){{window.__READY=true;startTimeline();}}}},15000);
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

    total_duration = _read_narration_total_duration(html_path)
    console.print("📹 [cyan]Selenium 录制口播视频...[/cyan]")
    console.print(f"⏱️  预计时长: {total_duration:.1f} 秒")
    webm_result = record_with_selenium(
        html_path, video_dir, total_duration + config.VIDEO_END_HOLD_SECONDS
    )
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
            "-y", mp4_result
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


def _read_narration_total_duration(html_path: str) -> float:
    """从生成的口播 HTML 中读取真实总时长，供服务器 Selenium 录制使用。"""
    try:
        html = Path(html_path).read_text(encoding="utf-8")
        match = re.search(r"const total=([0-9]+(?:\.[0-9]+)?);", html)
        if match:
            return float(match.group(1))
    except (OSError, ValueError):
        pass
    console.print("[yellow]⚠️ 无法读取口播真实时长，回退为 30 秒[/yellow]")
    return 30.0


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
            total_duration = page.evaluate("() => total")
        except Exception:
            total_duration = 30

        console.print(f"⏱️  预计时长: {total_duration:.0f} 秒")

        wait_ms = int((total_duration + config.VIDEO_END_HOLD_SECONDS) * 1000)
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
                "-y", mp4_path
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

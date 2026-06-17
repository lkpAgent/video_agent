"""
图文展示视频模式：用户上传图片 + 文字 → LLM 拆解成场景 → TTS配音 → 图片动效HTML → 录制视频

页面布局（竖屏 1080x1920）：
┌──────────────────────────────┐
│         场景标题              │
├──────────────────────────────┤
│                              │
│      图片（Ken Burns 动效）   │
│                              │
├──────────────────────────────┤
│      口播文字 / 旁白          │
└──────────────────────────────┘

背景音乐：用户可选 BGM，全程低音量循环播放
"""

import os
import re
import json
import time
import base64
import asyncio
import shutil
import subprocess
import html as html_lib
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress
from openai import OpenAI

from config import config

console = Console()
_HYPERFRAMES_CLI = ""
_HYPERFRAMES_CHECKED = False


def _escape_html(value: object) -> str:
    """转义用户和大模型生成的文本，避免破坏视频 HTML。"""
    return html_lib.escape(str(value or ""), quote=True)


def _split_caption_phrases(text: str, max_parts: int = 3) -> list[str]:
    """把旁白拆成适合动态排版的短语，而不是整段字幕。"""
    parts = [
        part.strip()
        for part in re.split(r"[，。！？；、：,.!?;:\n]+", str(text or ""))
        if part.strip()
    ]
    if not parts:
        return [str(text or "").strip()]
    if len(parts) <= max_parts:
        return parts
    return parts[:max_parts - 1] + ["，".join(parts[max_parts - 1:])]


def _hyperframes_font_css(work_dir: str) -> tuple[str, str]:
    """为 HyperFrames 显式加载中文字体，避免确定性渲染时中文变成问号。"""
    candidates = [
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
        Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
    ]
    font_path = next((p for p in candidates if p.exists()), None)
    if not font_path:
        return "", '"Microsoft YaHei","Noto Sans CJK SC",sans-serif'
    target_dir = Path(work_dir or config.TEMP_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"gallery-cjk{font_path.suffix.lower()}"
    if not target.exists() or target.stat().st_size != font_path.stat().st_size:
        shutil.copy2(font_path, target)
    css = f'@font-face{{font-family:"Gallery CJK";src:url("./{target.name}");font-display:block;}}'
    return css, '"Gallery CJK",sans-serif'


# ==================== LLM 文案拆解 ====================

def llm_breakdown_gallery_text(
    text_content: str,
    image_count: int,
    title: str = ""
) -> list[dict]:
    """
    调用 LLM 将用户输入的文字 + 图片数量拆解为场景列表
    
    Args:
        text_content: 用户输入的原始文字内容
        image_count: 图片数量
        title: 视频总标题
        
    Returns:
        [{"scene_title": "本页标题", "narration": "口播文案", "image_index": 0}, ...]
    """
    console.print("\n📝 [bold magenta]LLM 智能拆解文案...[/bold magenta]")
    
    client = OpenAI(
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_BASE_URL
    )
    
    prompt = f"""你是一个专业的短视频文案策划师。用户提供了 {image_count} 张图片和一些文字素材，
你需要将这些文字内容拆解成恰好 {image_count} 个场景，每个场景对应一张图片。

视频总标题：{title or '精彩展示'}

原始文字内容：
{text_content}

要求：
1. 拆解成恰好 {image_count} 个场景
2. 每个场景包含：
   - scene_title：场景小标题（4~9字，要像短视频中的观点钩子，不要只是概括）
   - narration：口播旁白文案（18~40字，自然口语化，有节奏、有态度）
3. 保持原文的核心信息和情感，不要编造新内容
4. 场景之间有逻辑递进关系
5. 避免“让我们来看看、首先、其次、总而言之”等模板化表达
6. 优先使用反问、对比、短句停顿、意外转折，让每页都像在讲一个观点
7. 不要重复视频总标题，不要写成说明书或新闻播报

输出格式（严格 JSON，不要 markdown）：
{{
  "scenes": [
    {{"scene_title": "标题1", "narration": "口播文案1"}},
    {{"scene_title": "标题2", "narration": "口播文案2"}}
  ]
}}"""

    try:
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
            temperature=0.8
        )
        
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        
        # 尝试提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if json_match:
            raw = json_match.group()
        
        data = json.loads(raw)
        scenes = data.get("scenes", [])
        
        # 确保场景数量匹配图片数量
        if len(scenes) != image_count:
            console.print(f"[yellow]LLM 返回 {len(scenes)} 个场景，但图片有 {image_count} 张，将自动调整[/yellow]")
            while len(scenes) < image_count:
                scenes.append({"scene_title": f"第{len(scenes)+1}页", "narration": ""})
            scenes = scenes[:image_count]
        
        # 补充 image_index
        for i, s in enumerate(scenes):
            s["image_index"] = i
            s["narration"] = s.get("narration", "").strip()
            if not s["narration"]:
                s["narration"] = f"让我们来看看第{i+1}张图片"
        
        console.print(f"✅ 拆解完成: [cyan]{len(scenes)}[/cyan] 个场景\n")
        console.print(Panel.fit(
            "\n".join(
                f"[bold cyan]场景{i}[/bold cyan] [yellow]| {s['scene_title']}[/yellow]\n"
                f"   [white]{s['narration']}[/white]"
                for i, s in enumerate(scenes, 1)
            ),
            title="📋 LLM 拆解文案",
            border_style="magenta"
        ))
        
        return scenes
        
    except Exception as e:
        console.print(f"[red]LLM 拆解失败: {e}[/red]")
        # 兜底：简单按图片数量均分
        console.print("[yellow]使用兜底方案：按图片数量均分文字[/yellow]")
        sentences = re.split(r'[。！？\n]', text_content)
        sentences = [s.strip() for s in sentences if len(s.strip()) >= 2]
        
        scenes = []
        per_image = max(1, len(sentences) // image_count)
        for i in range(image_count):
            start = i * per_image
            end = start + per_image if i < image_count - 1 else len(sentences)
            chunk = "。".join(sentences[start:end])
            if not chunk:
                chunk = f"第{i+1}张图片"
            scenes.append({
                "scene_title": f"第{i+1}页",
                "narration": chunk[:50],
                "image_index": i
            })
        return scenes


# ==================== 配音生成 ====================

def generate_gallery_audio(
    scenes: list[dict],
    voice_id: str = "",
    voice_type: int = 1
) -> list[dict]:
    """
    逐场景生成 TTS 配音
    
    Returns:
        scenes 列表（增强版，增加 path, duration 字段）
    """
    from modules.tts import tts_generate
    
    console.print(f"\n🔊 [bold green]逐场景生成配音...[/bold green]")
    
    audio_dir = os.path.join(config.TEMP_DIR, "gallery_audio")
    os.makedirs(audio_dir, exist_ok=True)
    
    for i, scene in enumerate(scenes):
        narration = scene.get("narration", "").strip()
        if not narration:
            narration = " "
        
        path = os.path.join(audio_dir, f"scene_{i+1:02d}.mp3")
        tts_generate(narration, path, voice_id, voice_type)
        
        dur = _get_mp3_duration(path)
        if dur <= 0:
            dur = max(1.5, len(narration) / 3.5)  # 估算
        
        scene["audio_path"] = path
        scene["duration"] = round(dur + 0.5, 2)  # 加 0.5 秒缓冲
        console.print(f"   [{i+1}/{len(scenes)}] {dur:.1f}s | {narration[:35]}...")
    
    console.print(f"✅ 配音完成\n")
    return scenes


def _get_mp3_duration(path: str) -> float:
    """用 ffprobe 获取音频时长"""
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path
        ], capture_output=True, text=True, timeout=10)
        return float(result.stdout.strip())
    except Exception:
        return 0.0


# ==================== HTML 生成 ====================

def generate_gallery_html(
    scenes: list[dict],
    images: list[str],
    title: str,
    bgm_path: str = ""
) -> str:
    """
    生成图文展示的动态 HTML 页面
    
    每页布局：标题 → 图片（Ken Burns） → 口播文字
    """
    total_duration = sum(s.get("duration", 3) for s in scenes)
    scenes_json = json.dumps(scenes, ensure_ascii=False)
    title_json = json.dumps(title, ensure_ascii=False)
    
    # 图片转 base64
    image_b64_list = []
    for img_path in images:
        if img_path and os.path.exists(img_path):
            with open(img_path, "rb") as f:
                ext = Path(img_path).suffix.lower()
                mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                            ".webp": "image/webp", ".gif": "image/gif"}
                mime = mime_map.get(ext, "image/jpeg")
                b64 = base64.b64encode(f.read()).decode()
                image_b64_list.append(f"data:{mime};base64,{b64}")
        else:
            image_b64_list.append("")
    
    images_json = json.dumps(image_b64_list, ensure_ascii=False)
    
    # BGM 处理
    bgm_b64 = ""
    if bgm_path and os.path.exists(bgm_path):
        with open(bgm_path, "rb") as f:
            ext = Path(bgm_path).suffix.lower()
            mime_map = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
                        ".m4a": "audio/mp4", ".aac": "audio/aac"}
            mime = mime_map.get(ext, "audio/mpeg")
            bgm_b64 = f"data:{mime};base64,{base64.b64encode(f.read()).decode()}"
    
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{
  width:{config.VIDEO_WIDTH}px;height:{config.VIDEO_HEIGHT}px;overflow:hidden;
  font-family:"Microsoft YaHei","PingFang SC","Noto Sans SC",sans-serif;
  background:#0a0a14;color:#fff;
}}

#app{{width:100%;height:100%;position:relative}}

/* ====== 场景容器 ====== */
.scene{{
  position:absolute;top:0;left:0;width:100%;height:100%;
  display:flex;flex-direction:column;
  opacity:0;transition:opacity 0.7s ease;
  pointer-events:none;z-index:1;
}}
.scene.active{{opacity:1;pointer-events:auto}}
.scene.exit{{opacity:0;transition:opacity 0.3s ease}}

/* ====== 标题区 ====== */
.scene-title{{
  padding:36px 70px 0;text-align:center;height:10%;
  display:flex;flex-direction:column;align-items:center;justify-content:flex-end;
}}
.scene-title .title-text{{
  font-size:38px;font-weight:700;letter-spacing:3px;
  color:#fff;text-shadow:0 2px 16px rgba(0,0,0,0.7);
  opacity:0;transform:translateY(-12px);
  transition:all 0.5s cubic-bezier(.16,1,.3,1);
}}
.scene.active .scene-title .title-text{{
  opacity:1;transform:translateY(0);
  transition-delay:0.15s;
}}
.scene-title .accent-dot{{
  width:6px;height:6px;border-radius:50%;
  background:linear-gradient(135deg,#818cf8,#c084fc);
  margin-top:10px;opacity:0;transform:scale(0);
  transition:all 0.4s ease;
}}
.scene.active .scene-title .accent-dot{{
  opacity:1;transform:scale(1);
  transition-delay:0.35s;
}}

/* ====== 图片区 ====== */
.scene-image{{
  flex:1;margin:16px 40px;position:relative;overflow:hidden;
  border-radius:24px;background:#101221;
  box-shadow:0 24px 80px rgba(0,0,0,0.55),0 0 0 1px rgba(255,255,255,0.06);
}}
.scene-image .image-backdrop{{
  position:absolute;inset:-8%;width:116%;height:116%;object-fit:cover;
  filter:blur(38px) saturate(1.15) brightness(.48);opacity:.8;
}}
.scene-image .image-main{{
  position:absolute;inset:0;width:100%;height:100%;object-fit:contain;
  filter:drop-shadow(0 16px 24px rgba(0,0,0,.36));
  transform:scale(1.06);
  transition:transform var(--scene-duration,5s) ease-out;
}}
/* Ken Burns 效果 */
.scene.active .scene-image .image-main{{
  transform:scale(1.16) translate(-1.5%,-1.5%);
}}
.scene:nth-child(even) .scene.active .scene-image .image-main{{
  transform:scale(1.16) translate(1.5%,1.5%);
}}

/* 图片装饰光晕 */
.scene-image::after{{
  content:"";position:absolute;inset:0;
  background:linear-gradient(180deg,transparent 60%,rgba(6,6,16,0.55) 100%);
  pointer-events:none;
}}

/* ====== 口播文字区 ====== */
.scene-narration{{
  padding:0 70px 0;height:18%;
  display:flex;align-items:flex-start;justify-content:center;
}}
.scene-narration .narration-inner{{
  display:inline-block;padding:18px 36px;
  background:linear-gradient(180deg,rgba(15,15,30,0.85),rgba(10,10,20,0.9));
  border-radius:12px;
  border:1px solid rgba(255,255,255,0.06);
  max-width:90%;
}}
.scene-narration .narration-text{{
  font-size:29px;font-weight:500;letter-spacing:1.5px;line-height:1.55;
  color:#f0f0f8;text-shadow:0 1px 8px rgba(0,0,0,0.5);
  text-align:center;opacity:0;transform:translateY(10px);
  transition:all 0.45s ease;
}}
.scene.active .scene-narration .narration-text{{
  opacity:1;transform:translateY(0);transition-delay:0.45s;
}}

/* ====== 进度条 ====== */
#progress{{
  position:absolute;bottom:0;left:0;height:3px;
  background:linear-gradient(90deg,#6366f1,#a855f7,#ec4899);
  z-index:999;width:0;transition:width 0.4s;
  box-shadow:0 0 10px rgba(99,102,241,0.4);
}}

/* ====== 页脚标识 ====== */
#footer-badge{{
  position:absolute;bottom:12px;right:30px;font-size:11px;
  color:rgba(255,255,255,0.2);z-index:999;letter-spacing:2px;
}}

/* ====== 确定性渲染 ====== */
.deterministic-render .scene{{transition:none!important}}
.deterministic-render .scene *{{transition:none!important;animation:none!important}}
.deterministic-render .scene-image img{{transition:none!important}}
</style>
</head>
<body>
<div id="app">
<div id="progress"></div>
<div id="footer-badge">{title}</div>
<div id="scenes-container"></div>
</div>

<!-- BGM -->
{'<audio id="bgm" src="' + bgm_b64 + '" loop preload="auto"></audio>' if bgm_b64 else ''}

<script>
const scenesData = {scenes_json};
const imagesData = {images_json};
const titleText = {title_json};
const total = {total_duration};
const sceneCount = scenesData.length;

const container = document.getElementById('scenes-container');
const progressBar = document.getElementById('progress');
let curScene = -1;
let sceneEls = [];
let timelineTimers = [];
let starts = [];
window.__READY = false;

// 累积时间点
let acc = 0;
scenesData.forEach(s => {{
  starts.push(acc);
  acc += s.duration || 3;
}});

// 构建场景 DOM
function buildScenes() {{
  scenesData.forEach((scene, i) => {{
    const el = document.createElement('div');
    el.className = 'scene';
    el.id = 'sc-' + i;
    el.style.setProperty('--scene-duration', Math.max(2.5, (scene.duration || 3) - .15) + 's');
    
    const imgSrc = imagesData[scene.image_index] || imagesData[i] || '';
    
    el.innerHTML = `
      <div class="scene-page-num">${{i+1}} / ${{sceneCount}}</div>
      <div class="scene-title">
        <div class="title-text">${{scene.scene_title || ''}}</div>
        <div class="accent-dot"></div>
      </div>
      <div class="scene-image">
        <img class="image-backdrop" src="${{imgSrc}}" alt="">
        <img class="image-main" src="${{imgSrc}}" alt="scene ${{i+1}}">
      </div>
      <div class="scene-narration">
        <div class="narration-inner">
          <div class="narration-text">${{scene.narration || ''}}</div>
        </div>
      </div>
    `;
    
    container.appendChild(el);
    sceneEls.push(el);
  }});
}}

// 切换场景
function showScene(idx) {{
  if (idx === curScene) return;
  if (idx >= scenesData.length) return;
  
  // 退出当前场景
  const prevEl = sceneEls[curScene];
  if (prevEl) {{
    prevEl.classList.add('exit');
    setTimeout(() => prevEl.classList.remove('active', 'exit'), 300);
  }}
  
  // 进入新场景
  const el = sceneEls[idx];
  if (el) {{
    el.classList.add('active');
    curScene = idx;
  }}
  
  // 进度条
  progressBar.style.width = ((starts[idx] || 0) / total * 100) + '%';
}}

// 时间线
function startTimeline() {{
  scenesData.forEach((s, i) => {{
    timelineTimers.push(setTimeout(() => showScene(i), starts[i] * 1000));
  }});
  // 末尾进度条
  timelineTimers.push(setTimeout(() => progressBar.style.width = '100%', total * 1000));
}}

// BGM 控制
const bgmEl = document.getElementById('bgm');
if (bgmEl) {{
  bgmEl.volume = 0.3;
  bgmEl.addEventListener('canplaythrough', () => {{
    if (window.__READY) bgmEl.play().catch(() => {{}});
  }});
}}

// 录制器 API
window.__stopTimeline = () => {{
  timelineTimers.forEach(clearTimeout);
  timelineTimers.length = 0;
  window.__READY = false;
  if (bgmEl) bgmEl.pause();
}};

window.__renderAt = (seconds) => {{
  document.body.classList.add('deterministic-render');
  let idx = 0;
  for (let i = 1; i < starts.length; i++) {{
    if (seconds >= starts[i]) idx = i;
    else break;
  }}
  showScene(idx);
  return idx;
}};

window.__renderScene = (idx) => {{
  document.body.classList.add('deterministic-render');
  showScene(idx);
  // 强制图片处于动画结束状态
  const el = sceneEls[idx];
  if (el) {{
    const img = el.querySelector('.scene-image .image-main');
    if (img) {{
      img.style.transition = 'none';
      img.style.transform = idx % 2 === 0 
        ? 'scale(1.15) translate(-2%,-2%)' 
        : 'scale(1.15) translate(2%,2%)';
    }}
  }}
  return idx;
}};

// 初始化
buildScenes();
showScene(0);

// 等待录制器就绪
var _waitReady = setInterval(() => {{
  if (window.__READY) {{
    clearInterval(_waitReady);
    startTimeline();
  }}
}}, 200);

// 预览模式自动启动
setTimeout(() => {{
  if (!window.__READY) {{ window.__READY = true; startTimeline(); }}
}}, 15000);
</script>
</body>
</html>'''

    html_path = os.path.join(config.TEMP_DIR, "gallery_video.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    
    console.print(f"📄 HTML 已生成: {html_path}")
    return html_path


def generate_hyperframes_html(
    scenes: list[dict],
    images: list[str],
    title: str,
    bgm_path: str = "",
    work_dir: str = ""
) -> str:
    """
    生成 HyperFrames 兼容的声明式 HTML
    使用 data-composition-id / data-start / data-duration / data-track-index
    替代 JS setTimeout 驱动，由 HyperFrames 引擎逐帧 seek 渲染
    """
    # 图片转 base64
    image_b64_list = []
    for img_path in images:
        if img_path and os.path.exists(img_path):
            with open(img_path, "rb") as f:
                ext = Path(img_path).suffix.lower()
                mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                            ".webp": "image/webp", ".gif": "image/gif"}
                mime = mime_map.get(ext, "image/jpeg")
                b64 = base64.b64encode(f.read()).decode()
                image_b64_list.append(f"data:{mime};base64,{b64}")
        else:
            image_b64_list.append("")
    
    # BGM base64
    bgm_b64 = ""
    if bgm_path and os.path.exists(bgm_path):
        with open(bgm_path, "rb") as f:
            ext = Path(bgm_path).suffix.lower()
            mime_map = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
                        ".m4a": "audio/mp4", ".aac": "audio/aac"}
            mime = mime_map.get(ext, "audio/mpeg")
            bgm_b64 = f"data:{mime};base64,{base64.b64encode(f.read()).decode()}"
    
    # 音频文件写入磁盘
    audio_dir = os.path.join(work_dir or config.TEMP_DIR, "hf_audio")
    os.makedirs(audio_dir, exist_ok=True)
    audio_srcs = []
    for i, scene in enumerate(scenes):
        audio_path = scene.get("audio_path", "")
        if audio_path and os.path.exists(audio_path):
            dest = os.path.join(audio_dir, f"scene_{i+1:02d}.mp3")
            if audio_path != dest:
                shutil.copy2(audio_path, dest)
            audio_srcs.append(dest)
        else:
            audio_srcs.append("")
    
    total_duration = sum(s.get("duration", 3) for s in scenes)
    font_face_css, font_family = _hyperframes_font_css(work_dir or config.TEMP_DIR)
    
    # 构建场景和音频 HTML
    scenes_html_parts = []
    audio_html_parts = []
    timeline_js_parts = []
    acc_time = 0.0
    
    for i, scene in enumerate(scenes):
        dur = scene.get("duration", 3)
        img_idx = scene.get("image_index", i)
        img_src = image_b64_list[img_idx] if img_idx < len(image_b64_list) else ""
        layout = ("wipe", "tilt", "stack", "spotlight")[i % 4]
        scene_title = str(scene.get("scene_title", "") or "")
        title_chars = "".join(
            f'<span class="title-char">{_escape_html(char)}</span>'
            for char in scene_title
        )
        phrases = _split_caption_phrases(scene.get("narration", ""))
        phrases_html = "".join(
            f'<span class="phrase {"phrase-accent" if j == 0 else ""}">{_escape_html(phrase)}</span>'
            for j, phrase in enumerate(phrases)
        )
        
        scenes_html_parts.append(f'''
    <section id="gallery-scene-{i + 1}" class="clip scene-block layout-{layout}" data-start="{acc_time:.2f}" data-duration="{dur:.2f}" data-track-index="{i}">
      <div class="scene-wash"></div>
      <div class="scene-counter"><b>{i + 1:02d}</b><span>{len(scenes):02d}</span></div>
      <div class="scene-heading">
        <div class="eyebrow">{_escape_html(title)}</div>
        <h2 class="kinetic-title">{title_chars}</h2>
      </div>
      <div class="image-stage">
        <div class="photo-shadow"></div>
        <div class="photo-shell">
          <img class="photo-blur" src="{img_src}" alt="">
          <img class="photo-main" src="{img_src}" alt="scene {i+1}">
          <div class="photo-glare"></div>
          <div class="image-caption">
            {phrases_html}
          </div>
        </div>
        <div class="orbit orbit-a"></div><div class="orbit orbit-b"></div>
        <div class="slide-label">FRAME / {i + 1:02d}</div>
      </div>
    </section>''')

        selector = f"#gallery-scene-{i + 1}"
        start = acc_time
        move_duration = max(1.2, dur - 0.35)
        if layout == "wipe":
            image_from = "{clipPath:'inset(0 100% 0 0)',x:-140,scale:.94,rotation:-4,filter:'blur(5px)'}"
            image_to = "{clipPath:'inset(0 0% 0 0)',x:0,scale:1,rotation:0,filter:'blur(0px)',duration:1.05,ease:'expo.out'}"
            drift_to = "{scale:1.16,x:30,y:-18,duration:" + f"{move_duration:.2f}" + ",ease:'none'}"
        elif layout == "tilt":
            image_from = "{clipPath:'inset(12% 12% 12% 12%)',rotationY:-58,rotationZ:-7,scale:.78,x:-90}"
            image_to = "{clipPath:'inset(0% 0% 0% 0%)',rotationY:0,rotationZ:-2,scale:1,x:0,duration:.9,ease:'back.out(1.25)'}"
            drift_to = "{scale:1.1,x:-24,y:10,duration:" + f"{move_duration:.2f}" + ",ease:'none'}"
        elif layout == "stack":
            image_from = "{clipPath:'polygon(0 0,100% 12%,88% 100%,8% 88%)',rotation:9,scale:.68,y:110}"
            image_to = "{clipPath:'polygon(0 0,100% 0,100% 100%,0 100%)',rotation:-2,scale:1,y:0,duration:.85,ease:'back.out(1.35)'}"
            drift_to = "{scale:1.09,x:14,y:-18,duration:" + f"{move_duration:.2f}" + ",ease:'none'}"
        else:
            image_from = "{clipPath:'circle(0% at 50% 50%)',scale:1.38,filter:'blur(14px)'}"
            image_to = "{clipPath:'circle(75% at 50% 50%)',scale:1,filter:'blur(0px)',duration:.9,ease:'expo.out'}"
            drift_to = "{scale:1.12,y:-16,duration:" + f"{move_duration:.2f}" + ",ease:'none'}"
        timeline_js_parts.append(f'''
tl.fromTo("{selector} .photo-shell",{image_from},{image_to},{start:.2f});
tl.fromTo("{selector} .photo-main",{{scale:1.01,x:0,y:0}},{drift_to},{start + .12:.2f});
tl.fromTo("{selector} .photo-blur",{{scale:1.08,x:0,y:0}},{{scale:1.22,x:-22,y:16,duration:{move_duration:.2f},ease:"none"}},{start + .05:.2f});
tl.fromTo("{selector} .title-char",{{opacity:0,y:70,rotationX:-80,filter:"blur(8px)"}},{{opacity:1,y:0,rotationX:0,filter:"blur(0px)",duration:.52,stagger:.055,ease:"back.out(1.7)"}},{start + .08:.2f});
tl.fromTo("{selector} .eyebrow",{{opacity:0,x:-35}},{{opacity:1,x:0,duration:.45,ease:"power3.out"}},{start + .06:.2f});
tl.fromTo("{selector} .image-caption",{{opacity:0,y:54,clipPath:"inset(0 0 100% 0)"}},{{opacity:1,y:0,clipPath:"inset(0 0 0% 0)",duration:.55,ease:"power3.out"}},{start + .52:.2f});
tl.fromTo("{selector} .phrase",{{opacity:0,y:30,scale:.92}},{{opacity:1,y:0,scale:1,duration:.48,stagger:.18,ease:"power3.out"}},{start + .62:.2f});
tl.fromTo("{selector} .orbit",{{opacity:0,scale:.5,rotation:-40}},{{opacity:.7,scale:1,rotation:18,duration:.9,stagger:.12,ease:"power3.out"}},{start + .22:.2f});
tl.fromTo("{selector} .scene-counter",{{opacity:0,y:-18}},{{opacity:1,y:0,duration:.4,ease:"power2.out"}},{start + .12:.2f});
''')
        
        audio_src = audio_srcs[i] if i < len(audio_srcs) else ""
        if audio_src:
            audio_file = Path(audio_src)
            audio_rel = Path("hf_audio") / audio_file.name
            audio_html_parts.append(
                f'    <audio id="scene-audio-{i + 1}" data-start="{acc_time:.2f}" data-duration="{dur:.2f}" '
                f'data-track-index="{100 + i}" src="./{audio_rel.as_posix()}"></audio>'
            )
        acc_time += dur
    
    # BGM
    bgm_html = ""
    if bgm_path and os.path.exists(bgm_path):
        bgm_src = Path(bgm_path)
        bgm_target = Path(work_dir or config.TEMP_DIR) / f"bgm{bgm_src.suffix.lower() or '.mp3'}"
        if bgm_src.resolve() != bgm_target.resolve():
            shutil.copy2(bgm_src, bgm_target)
        bgm_html = (
            f'    <audio id="bgm-track" data-start="0" data-duration="{total_duration:.2f}" '
            f'data-track-index="999" data-volume="0.25" src="./{bgm_target.name}" loop></audio>'
        )
    elif bgm_b64:
        bgm_html = (
            f'    <audio id="bgm-track" data-start="0" data-duration="{total_duration:.2f}" '
            f'data-track-index="999" data-volume="0.25" src="{bgm_b64}" loop></audio>'
        )
    
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>
{font_face_css}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{
  width:{config.VIDEO_WIDTH}px;height:{config.VIDEO_HEIGHT}px;overflow:hidden;
  font-family:{font_family};
  background:#08090d;color:#fff;
}}

#composition{{width:100%;height:100%;position:relative;overflow:hidden}}
#composition::before{{
  content:"";position:absolute;inset:0;pointer-events:none;opacity:.5;
  background:radial-gradient(circle at 14% 10%,#27317a 0,transparent 29%),radial-gradient(circle at 88% 74%,#401f68 0,transparent 24%);
}}

.clip.scene-block{{
  position:absolute;inset:0;width:100%;height:100%;perspective:1400px;overflow:hidden;
}}
.scene-wash{{position:absolute;inset:-20%;background:linear-gradient(130deg,rgba(74,85,230,.14),transparent 38%,rgba(232,72,151,.08));transform:rotate(-8deg)}}
.scene-counter{{position:absolute;top:74px;right:64px;z-index:12;display:flex;align-items:center;gap:9px;font-size:13px;letter-spacing:2px;color:#7f849e}}
.scene-counter b{{font-size:24px;color:#fff}}.scene-counter b::after{{content:"";display:inline-block;width:40px;height:1px;background:#6d62ff;margin:0 10px 6px}}
.scene-heading{{position:absolute;left:64px;top:70px;z-index:12;max-width:780px}}
.eyebrow{{font-size:14px;letter-spacing:5px;color:#9b95ff;margin-bottom:18px;font-weight:700}}
.kinetic-title{{display:flex;flex-wrap:wrap;font-size:66px;line-height:1.08;letter-spacing:2px;font-weight:900;text-shadow:0 12px 38px rgba(0,0,0,.45);perspective:700px}}
.title-char{{display:inline-block;transform-origin:50% 100%}}
.image-stage{{position:absolute;left:48px;right:48px;top:260px;bottom:300px;z-index:4;perspective:1400px}}
.photo-shadow{{position:absolute;inset:6% 2% -3%;border-radius:42px;background:#000;filter:blur(38px);opacity:.62}}
.photo-shell{{position:absolute;inset:0;overflow:hidden;border-radius:10px;background:#11131c;border:1px solid rgba(255,255,255,.16);box-shadow:0 28px 80px rgba(0,0,0,.46);transform-style:preserve-3d}}
.photo-blur{{position:absolute;inset:-7%;width:114%;height:114%;object-fit:cover;filter:blur(34px) brightness(.38) saturate(1.2)}}
.photo-main{{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;will-change:transform}}
.photo-glare{{position:absolute;inset:0;background:linear-gradient(120deg,rgba(255,255,255,.13),transparent 22%,transparent 72%,rgba(118,98,255,.12));pointer-events:none}}
.orbit{{position:absolute;border:1px solid rgba(144,133,255,.5);pointer-events:none}}
.orbit-a{{width:180px;height:180px;border-radius:50%;right:-48px;top:-54px;border-left-color:transparent}}
.orbit-b{{width:90px;height:90px;left:-26px;bottom:-38px;transform:rotate(45deg);border-color:rgba(255,84,171,.55)}}
.slide-label{{position:absolute;right:18px;bottom:-35px;font:700 12px/1 sans-serif;letter-spacing:4px;color:#72778f}}
.image-caption{{position:absolute;left:28px;right:28px;bottom:28px;z-index:8;display:flex;flex-wrap:wrap;align-items:center;gap:10px 12px;padding:18px 18px 20px;background:linear-gradient(90deg,rgba(4,5,12,.88),rgba(4,5,12,.52));border:1px solid rgba(255,255,255,.14);box-shadow:0 18px 42px rgba(0,0,0,.38);backdrop-filter:blur(18px)}}
.phrase{{display:inline-block;padding:8px 13px 10px;font-size:26px;line-height:1.18;font-weight:650;letter-spacing:.8px;color:#eef0fb;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.12);text-shadow:0 2px 12px rgba(0,0,0,.55)}}
.phrase-accent{{font-size:32px;color:#fff;background:#695cff;border-color:#897fff;box-shadow:8px 9px 0 rgba(255,74,166,.25)}}
.layout-tilt .image-stage{{left:72px;right:20px;top:278px;bottom:286px}}.layout-tilt .photo-shell{{border-radius:4px}}
.layout-stack .photo-shadow::before,.layout-stack .photo-shadow::after{{content:"";position:absolute;inset:0;background:#232535;border:1px solid rgba(255,255,255,.1)}}
.layout-stack .photo-shadow::before{{transform:rotate(-5deg)}}.layout-stack .photo-shadow::after{{transform:rotate(4deg)}}
.layout-spotlight .photo-shell{{border-radius:50%;inset:2% 5%}}.layout-spotlight .image-stage{{top:290px;bottom:310px}}

#progress{{
  position:absolute;bottom:0;left:0;height:3px;
  background:linear-gradient(90deg,#6366f1,#a855f7,#ec4899);z-index:999;
  box-shadow:0 0 12px rgba(99,102,241,0.5);
  animation:progressAnim {total_duration:.1f}s linear forwards;
}}
#footer-badge{{
  position:absolute;bottom:36px;right:50px;font-size:13px;
  color:rgba(255,255,255,0.35);z-index:999;letter-spacing:2px;
}}

@keyframes progressAnim{{from{{width:0}}to{{width:100%}}}}
</style>
</head>
<body>
<div id="composition" data-composition-id="gallery" data-start="0" data-duration="{total_duration:.2f}" data-width="{config.VIDEO_WIDTH}" data-height="{config.VIDEO_HEIGHT}">
  <div id="progress"></div>
  <div id="footer-badge">{_escape_html(title)}</div>
{''.join(scenes_html_parts)}
{''.join(audio_html_parts)}
{bgm_html}
</div>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{paused:true}});
{''.join(timeline_js_parts)}
window.__timelines.gallery = tl;
</script>
</body>
</html>'''

    # HyperFrames CLI 接收项目目录，并从目录中的 index.html 读取 composition。
    html_path = os.path.join(work_dir or config.TEMP_DIR, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    console.print(f"📄 HyperFrames HTML 已生成: {html_path}")
    return html_path


# ==================== HyperFrames 渲染 ====================

def _resolve_hyperframes_cli() -> str:
    """定位 HyperFrames 使用的 npx，可兼容 Windows 后端进程 PATH 差异。"""
    candidates = []
    configured = os.getenv("NPX_PATH", "").strip()
    if configured:
        candidates.append(configured)
    npx_name = "npx.cmd" if os.name == "nt" else "npx"
    found = shutil.which(npx_name) or shutil.which("npx")
    if found:
        candidates.append(found)
    if os.name == "nt":
        candidates.extend([
            r"D:\Program Files\nodejs\npx.cmd",
            r"C:\Program Files\nodejs\npx.cmd",
            str(Path(os.environ.get("APPDATA", "")) / "npm" / "npx.cmd"),
        ])
    return next((str(Path(path).resolve()) for path in candidates if path and Path(path).is_file()), "")


def _check_hyperframes_available(force: bool = False) -> bool:
    """检查 HyperFrames 是否可用，并输出可诊断的失败原因。"""
    global _HYPERFRAMES_CLI, _HYPERFRAMES_CHECKED
    if _HYPERFRAMES_CHECKED and not force:
        return bool(_HYPERFRAMES_CLI)

    _HYPERFRAMES_CHECKED = True
    cli = _resolve_hyperframes_cli()
    if not cli:
        console.print("[yellow]HyperFrames 检测失败: 找不到 npx，请设置 NPX_PATH[/yellow]")
        _HYPERFRAMES_CLI = ""
        return False
    try:
        result = subprocess.run(
            [cli, "--yes", "hyperframes", "--version"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, cwd=str(Path(__file__).resolve().parent.parent)
        )
        if result.returncode == 0:
            _HYPERFRAMES_CLI = cli
            console.print(f"[dim]HyperFrames 可用: {(result.stdout or '').strip()} ({cli})[/dim]")
            return True
        detail = (result.stderr or result.stdout or f"exit {result.returncode}").strip()
        console.print(f"[yellow]HyperFrames 检测失败: {detail[-500:]}[/yellow]")
    except Exception as exc:
        console.print(f"[yellow]HyperFrames 检测异常: {exc}[/yellow]")
    _HYPERFRAMES_CLI = ""
    return False


def _get_hyperframes_cli() -> str:
    if _check_hyperframes_available():
        return _HYPERFRAMES_CLI
    return ""


def _resolve_rendered_video_path(
    requested_output_path: str,
    process_output: str = "",
    started_at: float = 0.0
) -> str:
    """以 HyperFrames 实际落盘结果为准，兼容 CLI 对文件名的规范化。"""
    requested = Path(requested_output_path).resolve()
    if requested.exists() and requested.stat().st_size > 1000:
        return str(requested)

    if process_output:
        for raw_line in process_output.splitlines():
            line = raw_line.strip().lstrip("◇").strip()
            if not line.lower().endswith(".mp4"):
                continue
            candidate = Path(line)
            if candidate.exists() and candidate.stat().st_size > 1000:
                return str(candidate.resolve())

    output_dir = requested.parent
    if not output_dir.exists():
        return ""

    requested_stem = requested.stem
    requested_stem_fold = re.sub(r"[\s_]+", "", requested_stem).casefold()
    candidates = []
    for candidate in output_dir.glob("*.mp4"):
        try:
            stat = candidate.stat()
        except OSError:
            continue
        if stat.st_size <= 1000:
            continue
        if started_at and stat.st_mtime < started_at - 2:
            continue
        stem_fold = re.sub(r"[\s_]+", "", candidate.stem).casefold()
        score = 0
        if candidate == requested:
            score += 100
        if stem_fold == requested_stem_fold:
            score += 80
        elif requested_stem_fold and requested_stem_fold in stem_fold:
            score += 40
        score += int(stat.st_mtime)
        candidates.append((score, candidate))

    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0], reverse=True)
    return str(candidates[0][1].resolve())


def _record_hyperframes(
    scenes: list[dict],
    images: list[str],
    title: str,
    bgm_path: str = "",
    output_filename: str = None,
    work_dir: str = ""
) -> str:
    """使用 HyperFrames 渲染视频"""
    console.print("🎬 [cyan]HyperFrames 渲染中...[/cyan]")
    
    hf_html = generate_hyperframes_html(scenes, images, title, bgm_path, work_dir)
    
    video_dir = str(Path(config.VIDEO_OUTPUT_DIR).resolve())
    os.makedirs(video_dir, exist_ok=True)
    
    if output_filename is None:
        output_filename = "gallery.mp4"
    output_path = os.path.join(video_dir, output_filename)
    
    total_duration = sum(s.get("duration", 3) for s in scenes)
    console.print(f"   ⏱️  总时长: {total_duration:.1f}s")
    
    try:
        cli = _get_hyperframes_cli()
        if not cli:
            console.print("[red]HyperFrames CLI 不可用[/red]")
            return ""
        project_dir = str(Path(hf_html).resolve().parent)
        cmd = [cli, "--yes", "hyperframes", "render", project_dir, "-o", output_path]
        console.print(f"   [dim]命令: {' '.join(cmd)}[/dim]")
        timeout_seconds = int(os.getenv(
            "HYPERFRAMES_TIMEOUT_SECONDS",
            str(min(1800, max(300, int(total_duration * 20) + 180)))
        ))
        console.print(f"   [dim]超时保护: {timeout_seconds}s[/dim]")
        started_at = time.time()
        
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=timeout_seconds,
            cwd=work_dir or os.getcwd()
        )

        actual_output_path = _resolve_rendered_video_path(
            output_path,
            (result.stdout or "") + "\n" + (result.stderr or ""),
            started_at,
        )

        if result.returncode == 0 and actual_output_path:
            console.print(f"✅ [green]HyperFrames 渲染完成: {actual_output_path}[/green]")
            return actual_output_path
        else:
            console.print(f"[red]HyperFrames 渲染失败 (exit: {result.returncode})[/red]")
            if result.stdout:
                for line in result.stdout.strip().split("\n")[-12:]:
                    console.print(f"[dim]  {line}[/dim]")
            if result.stderr:
                for line in result.stderr.strip().split("\n")[-15:]:
                    console.print(f"[dim]  {line}[/dim]")
            return ""
    except subprocess.TimeoutExpired:
        actual_output_path = _resolve_rendered_video_path(output_path, "", time.time() - timeout_seconds)
        if actual_output_path:
            console.print(f"[yellow]HyperFrames 进程超时，但检测到已生成视频: {actual_output_path}[/yellow]")
            return actual_output_path
        console.print("[red]HyperFrames 渲染超时[/red]")
        return ""
    except Exception as e:
        console.print(f"[red]HyperFrames 异常: {e}[/red]")
        return ""


# ==================== 录制 ====================

def record_gallery_video(
    html_path: str,
    scenes: list[dict],
    bgm_path: str = "",
    output_filename: str = None
) -> str:
    """录制图文展示视频（引擎由 RECORD_ENGINE 配置决定）"""
    engine = config.RECORD_ENGINE.lower()
    if engine == "selenium":
        return _record_gallery_selenium(html_path, scenes, bgm_path, output_filename)
    else:
        return _record_gallery_playwright(html_path, scenes, bgm_path, output_filename)


def _record_gallery_selenium(
    html_path: str,
    scenes: list[dict],
    bgm_path: str = "",
    output_filename: str = None
) -> str:
    """Selenium 录制图文展示视频"""
    from modules.selenium_recorder import record_with_selenium
    
    total_duration = sum(s.get("duration", 3) for s in scenes)
    video_dir = str(Path(config.VIDEO_OUTPUT_DIR).resolve())
    os.makedirs(video_dir, exist_ok=True)
    
    if output_filename is None:
        output_filename = "gallery.mp4"
    
    console.print(f"📹 [cyan]Selenium 录制图文展示视频...[/cyan]")
    console.print(f"⏱️  预计时长: {total_duration:.1f} 秒")
    
    webm_result = record_with_selenium(
        html_path, video_dir, total_duration + config.VIDEO_END_HOLD_SECONDS
    )
    if not webm_result:
        return html_path
    
    # 合成音频：逐场景 TTS + BGM
    mp4_result = os.path.join(video_dir, output_filename)
    result = _mux_gallery_audio(webm_result, mp4_result, scenes, bgm_path)
    return result if result else webm_result


def _record_gallery_playwright(
    html_path: str,
    scenes: list[dict],
    bgm_path: str = "",
    output_filename: str = None
) -> str:
    """Playwright 录制图文展示视频"""
    from playwright.sync_api import sync_playwright
    
    total_duration = sum(s.get("duration", 3) for s in scenes)
    video_dir = str(Path(config.VIDEO_OUTPUT_DIR).resolve())
    os.makedirs(video_dir, exist_ok=True)
    
    if output_filename is None:
        output_filename = "gallery.mp4"
    
    video_path = os.path.join(video_dir, output_filename)
    
    console.print(f"🎥 [cyan]Playwright 录制图文展示视频...[/cyan]")
    console.print(f"⏱️  预计时长: {total_duration:.0f} 秒")
    
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
        
        # 启动时间线
        page.evaluate("window.__READY = true;")
        
        wait_ms = int((total_duration + config.VIDEO_END_HOLD_SECONDS) * 1000)
        with Progress() as progress:
            task = progress.add_task("[cyan]录制中...[/cyan]", total=wait_ms // 1000)
            for _ in range(wait_ms // 1000):
                time.sleep(1)
                progress.advance(task)
        
        context.close()
        browser.close()
    
    # 找到录制文件
    output_files = list(Path(video_dir).glob("*.webm"))
    if output_files:
        latest = max(output_files, key=os.path.getmtime)
        webm_path = video_path.replace(".mp4", ".webm")
        if latest.resolve() != Path(webm_path):
            if os.path.exists(webm_path):
                os.remove(webm_path)
            os.rename(str(latest), webm_path)
        console.print(f"✅ WebM 录制完成: {webm_path}")
        
        # 合成音频
        mp4_result = _mux_gallery_audio(str(webm_path), video_path, scenes, bgm_path)
        return mp4_result if mp4_result else str(webm_path)
    
    console.print("[red]未找到录制文件[/red]")
    return html_path


def _mux_gallery_audio(
    webm_path: str,
    mp4_path: str,
    scenes: list[dict],
    bgm_path: str = ""
) -> str:
    """
    用 ffmpeg 合成：视频 + 逐场景 TTS 音频 + 背景音乐
    
    策略：
    1. 先拼接所有 TTS 音频片段（按时间轴放置）
    2. 与 BGM 混合（BGM 低音量）
    3. 合入视频
    """
    if not shutil.which("ffmpeg"):
        console.print("[red]❌ 找不到 ffmpeg[/red]")
        return ""
    
    # 收集音频片段和其起始时间
    audio_files = []
    audio_starts = []
    acc = 0.0
    for scene in scenes:
        audio_path = scene.get("audio_path", "")
        if audio_path and os.path.exists(audio_path):
            audio_files.append(audio_path)
            audio_starts.append(acc)
        acc += scene.get("duration", 3)
    
    if not audio_files:
        console.print("[yellow]没有 TTS 音频，仅合成 BGM[/yellow]")
        if bgm_path and os.path.exists(bgm_path):
            return _mix_bgm_only(webm_path, mp4_path, bgm_path, acc)
        # 纯视频转 MP4
        return _simple_convert(webm_path, mp4_path)
    
    total_dur = acc
    
    console.print(f"🔊 合成 {len(audio_files)} 段 TTS + BGM → MP4...")
    
    try:
        # 构建 ffmpeg 命令
        cmd = ["ffmpeg", "-i", webm_path]
        
        # 添加所有音频输入
        audio_inputs = []
        for f in audio_files:
            cmd.extend(["-i", str(Path(f).resolve())])
            audio_inputs.append(f)
        
        # 构建 filter_complex
        filter_parts = []
        
        # 1. 每个 TTS 片段添加延迟 + 结尾静音填充
        for i, (af, start) in enumerate(zip(audio_files, audio_starts)):
            idx = i + 1  # 0 是视频，TTS 从 1 开始
            delay_ms = int(start * 1000)
            # adelay + apad 确保对齐
            filter_parts.append(
                f"[{idx}:a]adelay={delay_ms}|{delay_ms},apad=whole_dur={total_dur * 1000}ms[a{i}]"
            )
        
        # 2. 混合所有 TTS 片段
        mix_inputs = "".join(f"[a{i}]" for i in range(len(audio_files)))
        filter_parts.append(f"{mix_inputs}amix=inputs={len(audio_files)}:duration=longest:dropout_transition=0[tts_mix]")
        
        # 3. BGM 处理
        if bgm_path and os.path.exists(bgm_path):
            bgm_idx = len(audio_files) + 1
            cmd.extend(["-i", str(Path(bgm_path).resolve())])
            
            filter_parts.append(
                f"[{bgm_idx}:a]atrim=0:{total_dur},volume=0.25,afade=t=in:d=1,afade=t=out:st={total_dur - 1}:d=1[bgm_fade]"
            )
            filter_parts.append(
                f"[tts_mix][bgm_fade]amix=inputs=2:duration=first:weights=1 0.35[aout]"
            )
        else:
            filter_parts.append(f"[tts_mix]volume=1.0[aout]")
        
        filter_str = ";".join(filter_parts)
        
        cmd.extend([
            "-filter_complex", filter_str,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-y", mp4_path
        ])
        
        console.print(f"   [dim]ffmpeg 合成中...[/dim]")
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=600
        )
        
        if result.returncode == 0 and os.path.exists(mp4_path):
            os.remove(webm_path)
            console.print(f"✅ [green]MP4 生成完成: {mp4_path}[/green]")
            return mp4_path
        else:
            console.print(f"[red]ffmpeg 合成失败[/red]")
            if result.stderr:
                for line in result.stderr.strip().split("\n")[-10:]:
                    console.print(f"[dim]  {line}[/dim]")
            return _simple_convert(webm_path, mp4_path)
            
    except Exception as e:
        console.print(f"[red]音频合成异常: {e}[/red]")
        return _simple_convert(webm_path, mp4_path)


def _mix_bgm_only(webm_path: str, mp4_path: str, bgm_path: str, duration: float) -> str:
    """仅 BGM + 视频合成"""
    try:
        cmd = [
            "ffmpeg", "-i", webm_path, "-i", bgm_path,
            "-filter_complex",
            f"[1:a]atrim=0:{duration},volume=0.3,afade=t=in:d=1,afade=t=out:st={duration-1}:d=1[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-y", mp4_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            os.remove(webm_path)
            console.print(f"✅ MP4 (BGM): {mp4_path}")
            return mp4_path
    except Exception as e:
        console.print(f"[red]BGM 合成失败: {e}[/red]")
    return _simple_convert(webm_path, mp4_path)


def _simple_convert(webm_path: str, mp4_path: str) -> str:
    """纯视频格式转换（无音频）"""
    try:
        cmd = [
            "ffmpeg", "-i", webm_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-y", mp4_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            os.remove(webm_path)
            return mp4_path
    except Exception:
        pass
    return webm_path


# ==================== 统一入口 ====================

def build_gallery_video(
    images: list[str],
    text_content: str,
    title: str = "",
    bgm_path: str = "",
    voice_id: str = "",
    voice_type: int = 1,
    output_filename: str = None,
    record: bool = True
) -> str:
    """
    图文展示视频统一入口
    
    Args:
        images: 图片文件路径列表
        text_content: 用户输入的文字内容
        title: 视频总标题
        bgm_path: 背景音乐文件路径（可选）
        voice_id: TTS 语音
        voice_type: TTS 类型
        output_filename: 输出文件名
        record: 是否录制
        
    Returns:
        输出文件路径
    """
    console.print("\n🖼️  [bold cyan]图文展示视频生成模式[/bold cyan]")
    console.print(f"   图片: [cyan]{len(images)}[/cyan] 张")
    console.print(f"   文字: [dim]{len(text_content)}[/dim] 字")
    console.print(f"   标题: [cyan]{title}[/cyan]")
    console.print(f"   BGM: [dim]{bgm_path or '无'}[/dim]")
    console.print(f"   TTS: [dim]{voice_id or config.TTS_VOICE}[/dim]\n")
    
    # Step 1: LLM 拆解文案
    console.print("[bold]━━━ Step 1/4: LLM 拆解文案 ━━━[/bold]")
    scenes = llm_breakdown_gallery_text(text_content, len(images), title)
    
    # Step 2: 生成配音
    console.print("[bold]━━━ Step 2/4: 生成配音 ━━━[/bold]")
    scenes = generate_gallery_audio(scenes, voice_id, voice_type)
    
    # Step 3-4: 渲染（引擎由 RECORD_ENGINE 决定）
    engine = config.RECORD_ENGINE.lower()

    if engine in ("hyperframes", "hf"):
        console.print("[bold]━━━ Step 3/4: HyperFrames 渲染 ━━━[/bold]")
        if not _check_hyperframes_available():
            console.print("[yellow]⚠️  HyperFrames 不可用，回退到 Selenium[/yellow]")
            html_path = generate_gallery_html(scenes, images, title, bgm_path)
            if not record:
                return html_path
            video_path = record_gallery_video(html_path, scenes, bgm_path, output_filename)
        else:
            video_path = _record_hyperframes(scenes, images, title, bgm_path, output_filename, config.TEMP_DIR)
            if not video_path:
                console.print("[yellow]⚠️  HyperFrames 失败，回退到 Selenium[/yellow]")
                html_path = generate_gallery_html(scenes, images, title, bgm_path)
                video_path = record_gallery_video(html_path, scenes, bgm_path, output_filename)
    else:
        console.print("[bold]━━━ Step 3/4: 生成 HTML 页面 ━━━[/bold]")
        html_path = generate_gallery_html(scenes, images, title, bgm_path)
        if not record:
            console.print("[yellow]跳过录制[/yellow]")
            return html_path
        console.print("[bold]━━━ Step 4/4: 录制视频 ━━━[/bold]")
        video_path = record_gallery_video(html_path, scenes, bgm_path, output_filename)
    
    return video_path

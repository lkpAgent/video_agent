"""
文案生成模块：使用 LLM 将搜索资料整理成结构化视频脚本

脚本格式：
{
  "title": "视频标题",
  "description": "视频简介",
  "scenes": [
    {
      "type": "opening",      # 开场
      "narration": "旁白文案",
      "text_overlay": "叠加文字",
      "image_prompt": "AI 图片生成提示词",
      "duration": 3           # 秒
    },
    {
      "type": "content",
      "narration": "...",
      "text_overlay": "...",
      "image_prompt": "...",
      "duration": 8
    },
    {
      "type": "closing",      # 结尾
      "narration": "...",
      "text_overlay": "...",
      "image_prompt": "...",
      "duration": 4
    }
  ]
}
"""

import json
import re
import os
from typing import Optional
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel

from config import config

console = Console()

# 脚本生成的系统提示词（中文）
SYSTEM_PROMPT = """你是一个专业的短视频文案创作专家。用户会给你一个主题和相关搜索资料，你需要：

1. 理解主题核心，提炼关键信息
2. 写成一篇知识科普类短视频脚本，共 5 个场景
3. 每个场景包含：旁白文案(生动有趣)、屏幕叠加文字(简练有力)、AI图片提示词(视觉化描述)
4. 所有内容用中文，image_prompt 用英文
5. 每个场景旁白 50~100 字（约 12~25 秒朗读时长）

5个场景结构：
- 场景1 opening：开场引入，制造悬念
- 场景2 content：第一个知识点
- 场景3 content：第二个知识点  
- 场景4 content：第三个知识点
- 场景5 closing：总结升华

输出格式：严格的 JSON，不要带 markdown 标记。
{
  "title": "一句话标题",
  "scenes": [
    {"type":"opening","narration":"开场旁白(50~100字)","text_overlay":"大字标题","image_prompt":"English image description, 16:9, cinematic","duration":10},
    {"type":"content","narration":"知识点1旁白(50~100字)","text_overlay":"核心观点","image_prompt":"English description","duration":12},
    {"type":"content","narration":"知识点2旁白(50~100字)","text_overlay":"核心观点","image_prompt":"English description","duration":12},
    {"type":"content","narration":"知识点3旁白(50~100字)","text_overlay":"核心观点","image_prompt":"English description","duration":12},
    {"type":"closing","narration":"总结升华旁白(50~100字)","text_overlay":"核心总结","image_prompt":"ending screen, cinematic","duration":8}
  ]
}

duration 按中文 4 字/秒计算。image_prompt 要详细描述画面内容、风格、色调、构图。
"""


def generate_script(topic: str, search_context: str, custom_instruction: str = None) -> dict:
    """
    使用 LLM 生成视频脚本

    Args:
        topic: 视频主题
        search_context: 搜索资料上下文
        custom_instruction: 用户额外指令

    Returns:
        结构化的脚本 dict
    """
    console.print("\n📝 [bold magenta]正在生成视频文案脚本...[/bold magenta]")

    client = OpenAI(
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_BASE_URL
    )

    user_prompt = f"""主题：{topic}

搜索资料：
{search_context}

请根据以上资料，生成一个短视频脚本。"""

    if custom_instruction:
        user_prompt += f"\n\n额外要求：{custom_instruction}"

    try:
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=config.LLM_MAX_TOKENS,
            temperature=0.8
        )

        raw_output = response.choices[0].message.content.strip()

        if not raw_output:
            raise ValueError("LLM 返回空响应")

        # 清理可能的 markdown 代码块标记
        raw_output = re.sub(r'^```(?:json)?\s*', '', raw_output)
        raw_output = re.sub(r'\s*```$', '', raw_output)

        # 尝试提取 JSON（DeepSeek 有时包在额外文字里）
        json_match = re.search(r'\{[\s\S]*\}', raw_output)
        if json_match:
            raw_output = json_match.group()

        script = json.loads(raw_output)

        _validate_script(script)
        _print_script_summary(script)
        _save_script(script, topic)

        console.print("✅ [green]文案脚本生成完成！[/green]\n")
        return script

    except json.JSONDecodeError as e:
        console.print(f"[red]LLM 返回的不是有效 JSON[/red]")
        console.print(f"[yellow]原始输出（前 500 字）:[/yellow]\n{raw_output[:500]}")
        raise
        console.print(f"[yellow]原始输出:[/yellow]\n{raw_output[:500]}...")
        raise
    except Exception as e:
        console.print(f"[red]脚本生成失败: {e}[/red]")
        raise


def _validate_script(script: dict):
    """验证脚本结构"""
    required_keys = ["title", "scenes"]
    for key in required_keys:
        if key not in script:
            raise ValueError(f"脚本缺少必要字段: {key}")

    if not isinstance(script["scenes"], list):
        raise ValueError("scenes 必须是数组")

    scene_types = {"opening", "content", "closing", "transition"}
    for i, scene in enumerate(script["scenes"]):
        if "narration" not in scene:
            raise ValueError(f"场景 {i+1} 缺少 narration 字段")


def _print_script_summary(script: dict):
    """打印脚本摘要"""
    panel_content = f"[bold yellow]标题：[/bold yellow]{script.get('title', 'N/A')}\n\n"

    for i, scene in enumerate(script["scenes"], 1):
        narration_preview = scene.get("narration", "")[:40]
        duration = scene.get("duration", "?")
        panel_content += f"  [cyan]场景{i}[/cyan] [{scene.get('type', '?')}] {narration_preview}... ({duration}s)\n"

    console.print(Panel(panel_content, title="🎬 脚本预览", border_style="magenta"))


def _save_script(script: dict, topic: str):
    """保存脚本到文件"""
    os.makedirs(config.TEMP_DIR, exist_ok=True)
    safe_topic = "".join(c if c.isalnum() or c in "._- " else "_" for c in topic)[:30]
    path = os.path.join(config.TEMP_DIR, f"script_{safe_topic}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
    console.print(f"📄 脚本已保存: {path}")

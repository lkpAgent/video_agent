"""Optional LangChain Deep Agents wiring.

The MVP keeps deterministic Python orchestration for file and video side effects.
This module records the intended multi-agent shape and can be used once the
`deepagents` package is installed in the runtime.
"""

from __future__ import annotations


ORCHESTRATOR_PROMPT = """你是 DocumentVideoAgent 总控智能体。
你负责协调内容采集、页面文案、HTML 页面设计、TTS 与视频渲染。
页面设计需要尊重用户选择的视觉主题，例如 bright_unified 或 dark_premium。
所有文件写入和视频合成都必须通过工具完成，不要自由编造文件路径。
"""


SUBAGENTS = [
    {
        "name": "content_collector",
        "description": "采集主题、URL、GitHub 或本地文档内容，并清洗成资料包。",
        "prompt": "你只负责内容采集和资料清洗，输出结构化资料包。",
    },
    {
        "name": "page_script_writer",
        "description": "把资料重组为适合一页一屏展示的页面文案。",
        "prompt": "你负责 PPT 式页面脚本，每页内容少、观点清晰、旁白自然。",
    },
    {
        "name": "html_designer",
        "description": "根据页面脚本选择 HTML/CSS 页面样式。",
        "prompt": "你负责生成可录制的单文件 HTML 页面设计。",
    },
    {
        "name": "render_agent",
        "description": "调用 TTS 和 hyperframes/浏览器录制合成视频。",
        "prompt": "你负责使用工具生成音频、渲染页面并合成 MP4。",
    },
]


def create_document_deep_agent(model, tools):
    try:
        from deepagents import create_deep_agent
    except ImportError as exc:
        raise RuntimeError("未安装 deepagents。请先安装 LangChain Deep Agents 相关依赖。") from exc
    return create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=ORCHESTRATOR_PROMPT,
        subagents=SUBAGENTS,
    )

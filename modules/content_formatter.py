"""口播文案智能排版。"""

import re
from difflib import SequenceMatcher

from openai import OpenAI

from config import config


def _compact_text(content: str) -> str:
    return re.sub(r"\s+", "", content)


def _is_safe_revision(original: str, formatted: str) -> bool:
    """允许少量纠错，但拒绝明显扩写、删减或重写。"""
    source = _compact_text(original)
    target = _compact_text(formatted)
    if not source or not target:
        return False
    length_ratio = len(target) / len(source)
    similarity = SequenceMatcher(None, source, target).ratio()
    return 0.9 <= length_ratio <= 1.1 and similarity >= 0.9


def _fallback_pages(content: str) -> list[str]:
    """保留用户已有分页；没有空行分页时，每条非空行独立成页。"""
    if re.search(r"\n\s*\n", content):
        pages = []
        for block in re.split(r"\n\s*\n+", content):
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if lines:
                pages.append("\n".join(lines))
        return pages
    return [line.strip() for line in content.splitlines() if line.strip()]


def format_narration_content(content: str) -> tuple[str, list[str], str]:
    """
    轻量纠错并将文案分组为视频页面。

    返回：(以空行分隔的优化文案, 每页文案列表, 排版来源)
    """
    original = content.strip()
    if not original:
        raise ValueError("口播内容为空")

    prompt = f"""请对下面的短视频口播文案进行智能排版。

要求：
1. 你需要理解上下文和表达节奏，再决定如何分页，不能简单地每行一页。
2. 每页一般不超过 25 个中文字符。只合并语义紧密相关的短句，合并后也尽量不超过 25 字。
3. 超过 15 个中文字符的独立句子通常单独作为一页，不要再与其他句子合并。
4. 如果某一个长句本身超过 25 字，可以在自然语义停顿处切成 2-3 行，但这些行必须放在同一个页面，不能分页。
5. 每一页应表达一个相对完整的小观点、因果关系、动作与对象，或一组紧密关联的信息。
6. 表示新步骤、新观点或新案例的开头必须另起一页，例如“第一个、第二个、第三个、首先、其次、最后、另外、还有、接下来”等，绝不能并入上一页。
7. 字数限制只能用于拆分内容，不能因为两句话较短就忽略语义边界强行合并。
8. 保留原有口语表达、语气词和连接词，例如“呢、然后、就是、其实、所以”等，不要为了书面化而删除或替换。
9. 允许纠正明显错别字、同音识别错误和重复字，但不要润色、扩写、删减观点或大幅改写。
10. 文字调整必须非常克制，主要任务仍然是理解内容后重新分行和分页。
11. 只返回排版后的纯文案，不要返回 JSON、Markdown、说明或解释。

输出格式：
- 同一个页面里的多行使用一个换行分隔。
- 不同页面之间使用一个空行分隔。
- 普通页面最多 2 行。
- 同一个长句为了视觉展示可以切成 2-3 行，但仍属于同一个页面。

输出示例：
两个语义紧密相关的短句
合并在一个页面

一个超过25字的长句
在自然停顿处切成两到三行
但仍属于同一个页面

原文：
{original}"""

    source = "llm"
    try:
        client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=config.LLM_MAX_TOKENS,
            temperature=0.2,
        )
        finish_reason = response.choices[0].finish_reason
        if finish_reason == "length":
            raise ValueError(
                f"大模型排版响应被截断，请增大 LLM_MAX_TOKENS（当前 {config.LLM_MAX_TOKENS}）"
            )
        raw = (response.choices[0].message.content or "").strip()
        if not raw:
            raise ValueError("大模型排版返回空内容")
        raw = re.sub(r"^```(?:text|plaintext)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        pages = []
        for block in re.split(r"\n\s*\n+", raw):
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if lines:
                pages.append("\n".join(lines))
        if not pages:
            raise ValueError("大模型未返回有效页面")
        if not _is_safe_revision(original, "\n".join(pages)):
            raise ValueError("大模型排版对原文改动过大")
    except Exception as exc:
        pages = _fallback_pages(original)
        source = f"fallback:{exc}"

    # 大模型已经完成语义分页，后端不再按字数或行数二次重组。
    return "\n\n".join(pages), pages, source

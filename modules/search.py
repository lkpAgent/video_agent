"""
搜索模块：根据主题自动搜索 + 抓取网页内容
支持 DuckDuckGo 搜索 + 网页内容提取，提供 LLM 更丰富的上下文
"""

import json
import re
import time
from typing import Optional
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup
from rich.console import Console
from rich.table import Table

from config import config

console = Console()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


class SearchResult:
    def __init__(self, title: str, url: str, snippet: str, content: str = ""):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.content = content  # 抓取的完整内容

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "content": self.content
        }

    def __repr__(self):
        return f"SearchResult(title={self.title[:40]}...)"


def _optimize_query(topic: str) -> list[str]:
    """生成多个搜索变体，提高命中率"""
    queries = []

    # 检测是否包含英文
    has_english = bool(re.search(r'[a-zA-Z]{2,}', topic))

    if has_english:
        # 中英混合词：去掉中文前缀单独搜英文
        cn_prefixes = ["什么是", "什么叫", "如何", "怎样", "怎么"]
        clean = topic
        for p in cn_prefixes:
            clean = clean.replace(p, "").strip()
        queries.append(clean)  # 纯英文/中英混合
        queries.append(f"{clean} 是什么")
        queries.append(f"{clean} explained")
        queries.append(topic)  # 原始词也保留
    else:
        queries.append(topic)
        queries.append(f"{topic} 是什么")
        queries.append(f"{topic} 科普")

    return queries


def _fetch_page_content(url: str, timeout: int = 5) -> str:
    """抓取网页正文内容"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # 移除脚本、样式等无关元素
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # 提取正文
        text = soup.get_text(separator="\n", strip=True)
        # 清理空行和多余空白
        lines = [line.strip() for line in text.split("\n") if len(line.strip()) > 20]
        content = "\n".join(lines[:80])  # 最多保留 80 行
        return content[:3000]  # 最多 3000 字

    except Exception:
        return ""


def _is_quality_result(result: SearchResult) -> bool:
    """过滤低质量结果"""
    title = result.title.lower()
    snippet = result.snippet.lower()
    # 过滤明显的广告、低质内容
    bad_keywords = ["广告", "推广", "sponsored", "下载app", "立即购买", "click here"]
    for kw in bad_keywords:
        if kw in title or kw in snippet:
            return False
    # 标题或摘要太短
    if len(result.title) < 4:
        return False
    return True


def search_web(topic: str, max_results: int = None, fetch_content: bool = True) -> list[SearchResult]:
    """搜索入口：根据 SEARCH_ENGINE 配置选择引擎"""
    engine = config.SEARCH_ENGINE.lower()
    # 如果 Tavily key 未配置或为占位符，自动回退
    if engine == "tavily" and config.TAVILY_API_KEY and "your-key" not in config.TAVILY_API_KEY:
        return _search_tavily(topic, max_results)
    else:
        if engine == "tavily":
            console.print("[yellow]⚠️  TAVILY_API_KEY 未配置，回退到 DuckDuckGo[/yellow]")
        return _search_duckduckgo(topic, max_results, fetch_content)


def _search_tavily(topic: str, max_results: int = None) -> list[SearchResult]:
    """Tavily Search API（更精准，自带内容摘要）"""
    from tavily import TavilyClient

    if max_results is None:
        max_results = config.SEARCH_MAX_RESULTS

    console.print(f"\n🔍 [bold cyan]正在搜索 (Tavily): {topic}[/bold cyan]")

    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=config.TAVILY_API_KEY)
        response = client.search(
            query=topic,
            search_depth="advanced",
            max_results=max_results,
            include_answer=True
        )

        results = []
        # Tavily 的答案摘要
        if response.get("answer"):
            results.append(SearchResult(
                title="AI 摘要",
                url="",
                snippet="",
                content=response["answer"]
            ))

        for r in response.get("results", [])[:max_results]:
            results.append(SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
                content=r.get("raw_content", "")
            ))

        table = Table(title=f"Tavily 搜索结果（共 {len(results)} 条）", show_lines=False)
        table.add_column("#", style="dim", width=3)
        table.add_column("标题", style="cyan", width=35)
        table.add_column("摘要", style="green", width=45)
        for i, r in enumerate(results, 1):
            table.add_row(str(i), r.title[:33], r.snippet[:43])
        console.print(table)

        console.print(f"✅ Tavily 搜索完成: [green]{len(results)}[/green] 条\n")
        return results

    except ImportError:
        console.print("[yellow]请安装 tavily-python: pip install tavily-python[/yellow]")
        return []
    except Exception as e:
        console.print(f"[red]Tavily 搜索出错: {e}[/red]")
        return []


def _search_duckduckgo(topic: str, max_results: int = None, fetch_content: bool = True) -> list[SearchResult]:
    """
    搜索 web 内容 + 抓取页面详情

    Args:
        topic: 搜索主题
        max_results: 最大结果数
        fetch_content: 是否抓取网页内容

    Returns:
        SearchResult 列表
    """
    if max_results is None:
        max_results = config.SEARCH_MAX_RESULTS

    console.print(f"\n🔍 [bold cyan]正在搜索：{topic}[/bold cyan]")

    all_results = []
    seen_urls = set()

    # 尝试多个搜索词变体
    queries = _optimize_query(topic)
    per_query = max(3, max_results // len(queries))

    for qi, query in enumerate(queries):
        if len(all_results) >= max_results:
            break
        if qi > 0:
            console.print(f"   [dim]补充搜索: {query}[/dim]")

        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                search_results = list(ddgs.text(
                    query,
                    region=config.SEARCH_REGION,
                    max_results=per_query,
                    safesearch="moderate"
                ))

                for r in search_results:
                    url = r.get("href", "")
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    result = SearchResult(
                        title=r.get("title", ""),
                        url=url,
                        snippet=r.get("body", "")
                    )
                    if _is_quality_result(result):
                        all_results.append(result)
                    if len(all_results) >= max_results:
                        break

        except Exception as e:
            console.print(f"[dim]  搜索 '{query}' 出错: {e}[/dim]")
            continue

    console.print(f"   获取 {len(all_results)} 条结果")

    # 抓取网页内容
    if fetch_content and all_results:
        console.print("   📄 正在抓取网页详情...")
        fetched = 0
        for r in all_results[:6]:  # 只抓前 6 条
            content = _fetch_page_content(r.url)
            if content:
                r.content = content
                fetched += 1
            time.sleep(0.3)  # 礼貌限速
        console.print(f"   成功抓取 {fetched} 个页面的详细内容")

    # 打印结果摘要
    table = Table(title=f"搜索结果（共 {len(all_results)} 条）", show_lines=False)
    table.add_column("#", style="dim", width=3)
    table.add_column("标题", style="cyan", width=35)
    table.add_column("摘要", style="green", width=45)
    table.add_column("详情", style="dim", width=8)

    for i, r in enumerate(all_results, 1):
        has_content = "✅" if r.content else "—"
        table.add_row(str(i), r.title[:33], r.snippet[:43], has_content)

    console.print(table)
    console.print(f"✅ 搜索完成: [green]{len(all_results)}[/green] 条结果\n")
    return all_results


def search_to_context(results: list[SearchResult]) -> str:
    """将搜索结果转换为 LLM 可用的上下文字符串"""
    context_parts = []

    for i, r in enumerate(results, 1):
        part = f"[资料{i}]\n标题：{r.title}\n来源：{r.url}\n摘要：{r.snippet}\n"
        if r.content:
            # 网页详细内容
            part += f"详细内容：\n{r.content[:1500]}\n"
        context_parts.append(part)

    return "\n---\n".join(context_parts)

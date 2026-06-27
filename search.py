"""
网页搜索模块 - 支持 DuckDuckGo 搜索和网页内容抓取
支持 AI 摘要搜索结果
"""

import requests
from typing import Optional, Callable

# bs4 是可选依赖，延迟导入避免启动崩溃
_bs4_available = None

def _get_bs4():
    """延迟导入 BeautifulSoup（可选依赖）"""
    global _bs4_available
    if _bs4_available is None:
        try:
            from bs4 import BeautifulSoup as _BS
            _bs4_available = _BS
        except ImportError:
            _bs4_available = False
    return _bs4_available


class WebSearch:
    """网页搜索工具"""

    def __init__(self, ai_summarizer: Optional[Callable] = None):
        """
        ai_summarizer: 可选，AI 摘要回调函数，签名 func(query, search_results) -> str
        """
        self._summarizer = ai_summarizer

    def set_summarizer(self, func: Callable):
        """设置 AI 摘要回调"""
        self._summarizer = func

    @staticmethod
    def search_duckduckgo(query: str, max_results: int = 5) -> list:
        """
        使用 DuckDuckGo 搜索（无需 API Key）
        返回搜索结果列表，每项包含 title, link, snippet
        """
        url = "https://html.duckduckgo.com/html/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        try:
            response = requests.post(
                url,
                data={"q": query},
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()

            BS = _get_bs4()
            if not BS:
                return []
            soup = BS(response.text, "html.parser")
            results = soup.select(".result")

            if not results:
                return []

            items = []
            for result in results[:max_results]:
                title_elem = result.select_one(".result__title")
                snippet_elem = result.select_one(".result__snippet")
                link_elem = result.select_one(".result__url")

                items.append({
                    "title": title_elem.get_text(strip=True) if title_elem else "无标题",
                    "link": link_elem.get_text(strip=True) if link_elem else "",
                    "snippet": snippet_elem.get_text(strip=True) if snippet_elem else "",
                })

            return items

        except (requests.RequestException, Exception):
            return []

    @staticmethod
    def format_results(query: str, items: list) -> str:
        """格式化搜索结果为可读文本"""
        if not items:
            return f"未找到关于 '{query}' 的搜索结果"

        lines = [f"[搜索] {query}", "=" * 50]
        for i, item in enumerate(items, 1):
            lines.append(f"\n{i}. {item['title']}")
            if item.get("link"):
                lines.append(f"   {item['link']}")
            lines.append(f"   {item['snippet']}")

        return "\n".join(lines)

    @staticmethod
    def fetch_webpage(url: str) -> str:
        """
        抓取网页内容并提取纯文本（支持自动跟随重定向）
        """
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        try:
            response = requests.get(
                url, headers=headers, timeout=15, allow_redirects=True
            )
            response.raise_for_status()
            response.encoding = response.apparent_encoding

            BS = _get_bs4()
            if not BS:
                return "网页内容抓取需要安装 beautifulsoup4: pip install beautifulsoup4"
            soup = BS(response.text, "html.parser")

            # 移除脚本和样式
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()

            text = soup.get_text(separator="\n", strip=True)

            # 清理多余空行
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            if len(lines) > 200:
                lines = lines[:200]
                lines.append("...(内容已截断)")

            return f"[网页] {url}\n{'='*50}\n" + "\n".join(lines)

        except requests.RequestException as e:
            return f"抓取网页失败: {e}"
        except Exception as e:
            return f"解析网页出错: {e}"

    def search_and_summarize(self, query: str, max_results: int = 3) -> str:
        """
        搜索并返回结果。如果有 AI 摘要回调则用 AI 总结，否则返回原始结果。
        """
        items = self.search_duckduckgo(query, max_results)

        if not items:
            return f"未找到关于 '{query}' 的搜索结果"

        # 如果有 AI 摘要器，生成智能摘要
        if self._summarizer:
            try:
                summary = self._summarizer(query, items)
                if summary:
                    links = "\n".join([
                        f"  {i+1}. {item['title']}: {item['link']}"
                        for i, item in enumerate(items[:3])
                    ])
                    return f"{summary}\n\n参考链接:\n{links}"
            except Exception:
                pass

        # 回退到格式化结果
        return self.format_results(query, items)

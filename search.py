"""
网页搜索模块 - 支持 DuckDuckGo 搜索和网页内容抓取
"""

import requests
from typing import Optional
from bs4 import BeautifulSoup


class WebSearch:
    """网页搜索工具"""

    @staticmethod
    def search_duckduckgo(query: str, max_results: int = 5) -> str:
        """
        使用 DuckDuckGo 搜索（无需 API Key）
        返回格式化的搜索结果
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

            soup = BeautifulSoup(response.text, "html.parser")
            results = soup.select(".result")

            if not results:
                return f"未找到关于 '{query}' 的搜索结果"

            lines = [f"[搜索] {query}", "=" * 50]
            for i, result in enumerate(results[:max_results], 1):
                title_elem = result.select_one(".result__title")
                snippet_elem = result.select_one(".result__snippet")
                link_elem = result.select_one(".result__url")

                title = title_elem.get_text(strip=True) if title_elem else "无标题"
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else "无摘要"
                link = link_elem.get_text(strip=True) if link_elem else ""

                lines.append(f"\n{i}. {title}")
                if link:
                    lines.append(f"   {link}")
                lines.append(f"   {snippet}")

            return "\n".join(lines)

        except requests.RequestException as e:
            return f"搜索请求失败: {e}"
        except Exception as e:
            return f"搜索出错: {e}"

    @staticmethod
    def fetch_webpage(url: str) -> str:
        """
        抓取网页内容并提取纯文本
        """
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            response.encoding = response.apparent_encoding

            soup = BeautifulSoup(response.text, "html.parser")

            # 移除脚本和样式
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()

            text = soup.get_text(separator="\n", strip=True)

            # 清理多余空行
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            # 限制长度
            if len(lines) > 200:
                lines = lines[:200]
                lines.append("...(内容已截断)")

            return f"[网页] {url}\n{'='*50}\n" + "\n".join(lines)

        except requests.RequestException as e:
            return f"抓取网页失败: {e}"
        except Exception as e:
            return f"解析网页出错: {e}"

    @staticmethod
    def search_and_summarize(query: str, max_results: int = 3) -> str:
        """搜索并返回简洁摘要"""
        result = WebSearch.search_duckduckgo(query, max_results)
        return result

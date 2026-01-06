"""Google News RSS Collector

從 Google News RSS 抓取候選新聞事件池。
"""

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus

import feedparser
import yaml

from ..storage.cache import FileCache
from ..utils.logging import get_logger
from ..utils.text import clean_html, normalize_whitespace
from ..utils.time import parse_datetime

logger = get_logger(__name__)


@dataclass
class CandidateEvent:
    """候選事件資料結構"""

    id: str
    title: str
    url: str
    published_at: Optional[str] = None
    publisher: Optional[str] = None
    related_tickers: list[str] = field(default_factory=list)
    related_themes: list[str] = field(default_factory=list)
    query: str = ""
    snippet: Optional[str] = None

    def to_dict(self) -> dict:
        """轉換為字典"""
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at,
            "publisher": self.publisher,
            "related_tickers": self.related_tickers,
            "related_themes": self.related_themes,
            "query": self.query,
            "snippet": self.snippet,
        }


class GoogleNewsCollector:
    """Google News RSS 收集器"""

    BASE_URL = "https://news.google.com/rss/search"

    def __init__(
        self,
        cache: Optional[FileCache] = None,
        cache_ttl: int = 600,
        request_delay: float = 1.0,
        language: str = "en",
        country: str = "US",
    ):
        """初始化收集器

        Args:
            cache: 快取實例
            cache_ttl: 快取 TTL (秒)
            request_delay: 請求間隔 (秒)
            language: 語言 (hl 參數)
            country: 國家 (gl 參數)
        """
        self.cache = cache or FileCache(cache_dir="data/cache/news", default_ttl=cache_ttl)
        self.cache_ttl = cache_ttl
        self.request_delay = request_delay
        self.language = language
        self.country = country
        self._last_request_time = 0.0

    def _build_url(self, query: str) -> str:
        """建構 RSS URL

        Args:
            query: 搜尋關鍵字

        Returns:
            完整的 RSS URL
        """
        encoded_query = quote_plus(query)
        ceid = f"{self.country}:{self.language}"
        return f"{self.BASE_URL}?q={encoded_query}&hl={self.language}&gl={self.country}&ceid={ceid}"

    def _rate_limit(self) -> None:
        """執行速率限制"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self._last_request_time = time.time()

    def _generate_event_id(self, title: str, url: str) -> str:
        """生成事件 ID

        Args:
            title: 標題
            url: URL

        Returns:
            唯一事件 ID
        """
        content = f"{title}:{url}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _parse_publisher(self, source_title: str) -> str:
        """從 source title 解析出版者

        Args:
            source_title: RSS 的 source title

        Returns:
            出版者名稱
        """
        # Google News 的 source 格式通常是 "Publisher Name"
        return source_title.strip() if source_title else "Unknown"

    def _parse_entry(
        self,
        entry: dict,
        query: str,
        ticker: Optional[str] = None,
        theme: Optional[str] = None,
    ) -> CandidateEvent:
        """解析 RSS entry

        Args:
            entry: feedparser entry
            query: 搜尋查詢
            ticker: 相關 ticker
            theme: 相關主題

        Returns:
            CandidateEvent 實例
        """
        title = clean_html(entry.get("title", ""))
        title = normalize_whitespace(title)

        url = entry.get("link", "")

        # 解析發布時間
        published_at = None
        if "published" in entry:
            dt = parse_datetime(entry["published"])
            if dt:
                published_at = dt.isoformat()

        # 解析出版者
        publisher = None
        if "source" in entry and "title" in entry["source"]:
            publisher = self._parse_publisher(entry["source"]["title"])

        # 解析摘要
        snippet = None
        if "summary" in entry:
            snippet = clean_html(entry["summary"])
            snippet = normalize_whitespace(snippet)[:500]

        # 建立事件
        event = CandidateEvent(
            id=self._generate_event_id(title, url),
            title=title,
            url=url,
            published_at=published_at,
            publisher=publisher,
            related_tickers=[ticker] if ticker else [],
            related_themes=[theme] if theme else [],
            query=query,
            snippet=snippet,
        )

        return event

    def fetch_query(
        self,
        query: str,
        limit: int = 10,
        ticker: Optional[str] = None,
        theme: Optional[str] = None,
    ) -> list[CandidateEvent]:
        """抓取單一查詢的新聞

        Args:
            query: 搜尋關鍵字
            limit: 最大數量
            ticker: 相關 ticker
            theme: 相關主題

        Returns:
            CandidateEvent 列表
        """
        # 檢查快取
        cache_key = f"gnews:{query}:{limit}"
        cached = self.cache.get(cache_key)
        if cached:
            logger.debug(f"Cache hit for query: {query}")
            return [CandidateEvent(**e) for e in cached]

        # 速率限制
        self._rate_limit()

        # 建構 URL 並抓取
        url = self._build_url(query)
        logger.info(f"Fetching: {query}")

        try:
            feed = feedparser.parse(url)

            if feed.bozo and feed.bozo_exception:
                logger.warning(f"Feed parse warning: {feed.bozo_exception}")

            events = []
            for entry in feed.entries[:limit]:
                event = self._parse_entry(entry, query, ticker, theme)
                events.append(event)

            # 存入快取
            self.cache.set(cache_key, [e.to_dict() for e in events], self.cache_ttl)

            logger.info(f"Fetched {len(events)} events for: {query}")
            return events

        except Exception as e:
            logger.error(f"Error fetching {query}: {e}")
            return []

    def collect_from_universe(
        self,
        universe_path: str = "config/universe.yaml",
        items_per_query: int = 10,
    ) -> list[CandidateEvent]:
        """從 universe 設定收集新聞

        Args:
            universe_path: universe.yaml 路徑
            items_per_query: 每個查詢的最大數量

        Returns:
            去重後的 CandidateEvent 列表
        """
        # 載入 universe
        with open(universe_path) as f:
            universe = yaml.safe_load(f)

        themes = universe.get("themes", {})
        all_events: dict[str, CandidateEvent] = {}

        # 對每個主題的 tickers 和 keywords 進行查詢
        for theme_id, theme_data in themes.items():
            theme_name = theme_data.get("name", theme_id)

            # 查詢 tickers
            for ticker in theme_data.get("tickers", []):
                query = f"{ticker} stock"
                events = self.fetch_query(
                    query,
                    limit=items_per_query,
                    ticker=ticker,
                    theme=theme_id,
                )
                for event in events:
                    if event.id not in all_events:
                        all_events[event.id] = event
                    else:
                        # 合併 tickers 和 themes
                        existing = all_events[event.id]
                        if ticker not in existing.related_tickers:
                            existing.related_tickers.append(ticker)
                        if theme_id not in existing.related_themes:
                            existing.related_themes.append(theme_id)

            # 查詢 keywords (只取前 2 個避免太多請求)
            for keyword in theme_data.get("keywords", [])[:2]:
                events = self.fetch_query(
                    keyword,
                    limit=items_per_query,
                    theme=theme_id,
                )
                for event in events:
                    if event.id not in all_events:
                        all_events[event.id] = event
                    else:
                        existing = all_events[event.id]
                        if theme_id not in existing.related_themes:
                            existing.related_themes.append(theme_id)

        # 轉換為列表並按發布時間排序
        events_list = list(all_events.values())
        events_list.sort(
            key=lambda e: e.published_at or "",
            reverse=True,
        )

        logger.info(f"Collected {len(events_list)} unique events from universe")
        return events_list


def main():
    """CLI demo"""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Google News RSS Collector")
    parser.add_argument("--query", "-q", help="Search query")
    parser.add_argument("--limit", "-n", type=int, default=10, help="Items per query")
    parser.add_argument("--universe", "-u", action="store_true", help="Collect from universe")
    parser.add_argument("--output", "-o", help="Output file path")
    args = parser.parse_args()

    from rich.console import Console
    from rich.table import Table

    console = Console()

    collector = GoogleNewsCollector()

    if args.universe:
        console.print("[bold]Collecting from universe...[/bold]")
        events = collector.collect_from_universe(items_per_query=args.limit)
    elif args.query:
        console.print(f"[bold]Searching: {args.query}[/bold]")
        events = collector.fetch_query(args.query, limit=args.limit)
    else:
        console.print("[yellow]Please specify --query or --universe[/yellow]")
        return

    # 顯示結果
    table = Table(title=f"Candidate Events ({len(events)} total)")
    table.add_column("#", style="dim")
    table.add_column("Title", max_width=50)
    table.add_column("Publisher", style="cyan")
    table.add_column("Tickers", style="yellow")
    table.add_column("Published", style="green")

    for i, event in enumerate(events[:20], 1):
        tickers = ", ".join(event.related_tickers[:3])
        pub_time = event.published_at[:10] if event.published_at else "N/A"
        table.add_row(
            str(i),
            event.title[:50] + "..." if len(event.title) > 50 else event.title,
            event.publisher or "N/A",
            tickers or "-",
            pub_time,
        )

    console.print(table)

    # 輸出到檔案
    if args.output:
        output_data = [e.to_dict() for e in events]
        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        console.print(f"\n[green]Saved to {args.output}[/green]")


if __name__ == "__main__":
    main()

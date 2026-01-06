"""Event Scoring Module

對候選事件進行評分與分類。
"""

import re
from dataclasses import dataclass, field
from typing import Optional

import yaml

from ..collectors.google_news_rss import CandidateEvent
from ..utils.logging import get_logger

logger = get_logger(__name__)


# 事件類型關鍵字
EVENT_TYPE_KEYWORDS = {
    "earnings": [
        "earnings", "quarterly results", "Q1", "Q2", "Q3", "Q4",
        "revenue", "profit", "EPS", "beat", "miss", "guidance",
        "財報", "盈餘", "營收",
    ],
    "guidance": [
        "guidance", "outlook", "forecast", "raises", "lowers",
        "expects", "projects", "targets", "full-year",
    ],
    "regulation": [
        "SEC", "FTC", "DOJ", "regulation", "antitrust", "investigation",
        "lawsuit", "fine", "penalty", "compliance", "approval",
        "FDA", "FAA",
    ],
    "macro": [
        "Fed", "interest rate", "inflation", "CPI", "GDP",
        "unemployment", "tariff", "trade war", "recession",
    ],
    "product": [
        "launch", "unveil", "announce", "new product", "release",
        "upgrade", "next-gen", "breakthrough",
    ],
    "partnership": [
        "partnership", "collaboration", "deal", "agreement",
        "acquisition", "merger", "M&A", "buyout", "invest",
    ],
    "rumor": [
        "rumor", "reportedly", "sources say", "may", "could",
        "speculation", "unconfirmed",
    ],
}


@dataclass
class ScoredEvent:
    """評分後的事件"""

    event: CandidateEvent
    event_type: str = "other"
    relevance_score: float = 0.0
    credibility_score: float = 0.0
    impact_score: float = 0.0
    total_score: float = 0.0
    is_rumor: bool = False
    matched_tickers: list[str] = field(default_factory=list)
    matched_themes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "event": self.event.to_dict(),
            "event_type": self.event_type,
            "relevance_score": self.relevance_score,
            "credibility_score": self.credibility_score,
            "impact_score": self.impact_score,
            "total_score": self.total_score,
            "is_rumor": self.is_rumor,
            "matched_tickers": self.matched_tickers,
            "matched_themes": self.matched_themes,
        }


class EventScorer:
    """事件評分器"""

    def __init__(
        self,
        universe_path: str = "config/universe.yaml",
        min_credibility_publishers: int = 2,
        rumor_penalty: float = 0.3,
    ):
        """初始化事件評分器

        Args:
            universe_path: universe.yaml 路徑
            min_credibility_publishers: 最低可信度 publisher 數量
            rumor_penalty: Rumor 降權係數
        """
        self.min_credibility_publishers = min_credibility_publishers
        self.rumor_penalty = rumor_penalty

        # 載入 universe
        with open(universe_path) as f:
            self.universe = yaml.safe_load(f)

        self.all_tickers = set(self.universe.get("all_tickers", []))
        self.themes = self.universe.get("themes", {})

        # 建立 ticker -> themes 映射
        self.ticker_to_themes = {}
        for theme_id, theme_data in self.themes.items():
            for ticker in theme_data.get("tickers", []):
                if ticker not in self.ticker_to_themes:
                    self.ticker_to_themes[ticker] = []
                self.ticker_to_themes[ticker].append(theme_id)

    def classify_event_type(self, text: str) -> tuple[str, bool]:
        """分類事件類型

        Args:
            text: 事件標題或內容

        Returns:
            (event_type, is_rumor)
        """
        text_lower = text.lower()
        is_rumor = False

        # 檢查是否為 rumor
        for keyword in EVENT_TYPE_KEYWORDS["rumor"]:
            if keyword.lower() in text_lower:
                is_rumor = True
                break

        # 依優先順序檢查事件類型
        priority_order = ["earnings", "guidance", "regulation", "macro", "product", "partnership"]

        for event_type in priority_order:
            keywords = EVENT_TYPE_KEYWORDS[event_type]
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    return event_type, is_rumor

        return "other", is_rumor

    def extract_tickers_from_text(self, text: str) -> list[str]:
        """從文字中提取 tickers

        Args:
            text: 文字內容

        Returns:
            匹配的 tickers 列表
        """
        matched = []
        text_upper = text.upper()

        for ticker in self.all_tickers:
            # 用 word boundary 匹配
            pattern = rf"\b{re.escape(ticker)}\b"
            if re.search(pattern, text_upper):
                matched.append(ticker)

        return matched

    def calculate_relevance(self, event: CandidateEvent) -> tuple[float, list[str], list[str]]:
        """計算相關性分數

        Args:
            event: 候選事件

        Returns:
            (relevance_score, matched_tickers, matched_themes)
        """
        matched_tickers = set(event.related_tickers)
        matched_themes = set(event.related_themes)

        # 從標題提取額外 tickers
        title_tickers = self.extract_tickers_from_text(event.title)
        matched_tickers.update(title_tickers)

        # 從 snippet 提取
        if event.snippet:
            snippet_tickers = self.extract_tickers_from_text(event.snippet)
            matched_tickers.update(snippet_tickers)

        # 根據 tickers 找對應 themes
        for ticker in matched_tickers:
            if ticker in self.ticker_to_themes:
                matched_themes.update(self.ticker_to_themes[ticker])

        # 計算分數
        ticker_count = len(matched_tickers)
        theme_count = len(matched_themes)

        # 基礎分數 (0-40)
        base_score = min(ticker_count * 10, 30) + min(theme_count * 5, 10)

        return base_score, list(matched_tickers), list(matched_themes)

    def calculate_credibility(self, event: CandidateEvent, publisher_count: int = 1) -> float:
        """計算可信度分數

        Args:
            event: 候選事件
            publisher_count: 報導此事件的出版者數量

        Returns:
            credibility_score (0-30)
        """
        # 知名出版者加分
        reputable_publishers = {
            "Reuters", "Bloomberg", "CNBC", "Wall Street Journal", "WSJ",
            "Financial Times", "Barron's", "Investor's Business Daily",
            "The Motley Fool", "Seeking Alpha", "Yahoo Finance",
            "MarketWatch", "TechCrunch", "The Verge", "Wired",
        }

        publisher = event.publisher or ""
        is_reputable = any(rp.lower() in publisher.lower() for rp in reputable_publishers)

        # 基礎分數
        score = min(publisher_count * 5, 15)

        # 知名出版者加分
        if is_reputable:
            score += 15
        else:
            score += 5

        return min(score, 30)

    def calculate_impact(self, event: CandidateEvent, event_type: str) -> float:
        """計算影響力分數

        Args:
            event: 候選事件
            event_type: 事件類型

        Returns:
            impact_score (0-30)
        """
        # 根據事件類型給予基礎分數
        type_scores = {
            "earnings": 25,
            "guidance": 20,
            "regulation": 20,
            "macro": 15,
            "product": 15,
            "partnership": 15,
            "rumor": 5,
            "other": 10,
        }

        score = type_scores.get(event_type, 10)

        # 標題包含強烈用語加分
        strong_words = [
            "surge", "plunge", "soar", "crash", "breakthrough",
            "record", "historic", "massive", "major",
        ]
        title_lower = event.title.lower()
        for word in strong_words:
            if word in title_lower:
                score += 5
                break

        return min(score, 30)

    def score_event(
        self,
        event: CandidateEvent,
        publisher_count: int = 1,
    ) -> ScoredEvent:
        """對單一事件評分

        Args:
            event: 候選事件
            publisher_count: 報導此事件的出版者數量

        Returns:
            ScoredEvent 實例
        """
        # 分類事件類型
        event_type, is_rumor = self.classify_event_type(event.title)

        # 計算各項分數
        relevance, matched_tickers, matched_themes = self.calculate_relevance(event)
        credibility = self.calculate_credibility(event, publisher_count)
        impact = self.calculate_impact(event, event_type)

        # 計算總分
        total = relevance + credibility + impact

        # Rumor 降權
        if is_rumor:
            total *= self.rumor_penalty

        # 低可信度降權
        if publisher_count < self.min_credibility_publishers:
            total *= 0.7

        return ScoredEvent(
            event=event,
            event_type=event_type,
            relevance_score=relevance,
            credibility_score=credibility,
            impact_score=impact,
            total_score=total,
            is_rumor=is_rumor,
            matched_tickers=matched_tickers,
            matched_themes=matched_themes,
        )

    def score_events(
        self,
        events: list[CandidateEvent],
    ) -> list[ScoredEvent]:
        """對多個事件評分並排序

        Args:
            events: 候選事件列表

        Returns:
            評分後的事件列表 (按分數降序)
        """
        # 統計 publisher 數量 (按 URL 去重)
        url_publishers: dict[str, set[str]] = {}
        for event in events:
            url = event.url
            publisher = event.publisher or "Unknown"
            if url not in url_publishers:
                url_publishers[url] = set()
            url_publishers[url].add(publisher)

        # 評分
        scored = []
        for event in events:
            publisher_count = len(url_publishers.get(event.url, {event.publisher or "Unknown"}))
            scored_event = self.score_event(event, publisher_count)
            scored.append(scored_event)

        # 按分數排序
        scored.sort(key=lambda e: e.total_score, reverse=True)

        return scored

    def select_primary(
        self,
        scored_events: list[ScoredEvent],
        min_score: float = 20.0,
    ) -> Optional[ScoredEvent]:
        """選擇主要事件

        Args:
            scored_events: 評分後的事件列表
            min_score: 最低分數閾值

        Returns:
            主要事件或 None
        """
        for event in scored_events:
            if event.total_score >= min_score and not event.is_rumor:
                return event

        # 如果沒有非 rumor 事件，選最高分
        if scored_events:
            return scored_events[0]

        return None


def main():
    """CLI demo"""
    import json
    from rich.console import Console
    from rich.table import Table

    from ..collectors.google_news_rss import GoogleNewsCollector

    console = Console()

    # 收集新聞
    console.print("[bold]Collecting news...[/bold]")
    collector = GoogleNewsCollector()
    events = collector.fetch_query("NVDA stock", limit=10)
    events += collector.fetch_query("AI chip", limit=5)

    # 評分
    console.print("[bold]Scoring events...[/bold]")
    scorer = EventScorer()
    scored = scorer.score_events(events)

    # 顯示結果
    table = Table(title="Scored Events")
    table.add_column("Score", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Title", max_width=40)
    table.add_column("Tickers", style="yellow")
    table.add_column("Rumor", style="red")

    for event in scored[:15]:
        table.add_row(
            f"{event.total_score:.1f}",
            event.event_type,
            event.event.title[:40] + "..." if len(event.event.title) > 40 else event.event.title,
            ", ".join(event.matched_tickers[:3]),
            "Yes" if event.is_rumor else "No",
        )

    console.print(table)

    # 選擇主要事件
    primary = scorer.select_primary(scored)
    if primary:
        console.print(f"\n[bold green]Primary Event:[/bold green] {primary.event.title}")
        console.print(f"Score: {primary.total_score:.1f}, Type: {primary.event_type}")


if __name__ == "__main__":
    main()

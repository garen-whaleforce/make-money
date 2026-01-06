"""Research Pack Builder

組建研究包，整合所有分析所需資料。
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import jsonschema
import yaml

from ..collectors.google_news_rss import CandidateEvent
from ..enrichers.base import CompanyData
from ..utils.logging import get_logger
from ..utils.time import get_run_id, format_datetime, get_now
from .event_scoring import ScoredEvent, EventScorer

logger = get_logger(__name__)


@dataclass
class ResearchPack:
    """研究包資料結構"""

    meta: dict
    primary_event: dict
    primary_theme: dict
    key_stocks: list[dict]
    candidate_events: list[dict] = field(default_factory=list)
    companies: dict[str, dict] = field(default_factory=dict)
    valuations: dict[str, dict] = field(default_factory=dict)
    peer_table: Optional[dict] = None
    sources: list[dict] = field(default_factory=list)
    selection_rationale: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "meta": self.meta,
            "primary_event": self.primary_event,
            "primary_theme": self.primary_theme,
            "key_stocks": self.key_stocks,
            "candidate_events": self.candidate_events,
            "companies": self.companies,
            "valuations": self.valuations,
            "peer_table": self.peer_table,
            "sources": self.sources,
            "selection_rationale": self.selection_rationale,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


class ResearchPackBuilder:
    """研究包建構器"""

    def __init__(
        self,
        universe_path: str = "config/universe.yaml",
        schema_path: str = "schemas/research_pack.schema.json",
        min_key_stocks: int = 2,
        max_key_stocks: int = 4,
    ):
        """初始化研究包建構器

        Args:
            universe_path: universe.yaml 路徑
            schema_path: JSON Schema 路徑
            min_key_stocks: 最少關鍵個股數
            max_key_stocks: 最多關鍵個股數
        """
        # 載入 universe
        with open(universe_path) as f:
            self.universe = yaml.safe_load(f)

        # 載入 schema
        self.schema_path = Path(schema_path)
        self.schema = None
        if self.schema_path.exists():
            with open(schema_path) as f:
                self.schema = json.load(f)

        self.themes = self.universe.get("themes", {})
        self.min_key_stocks = min_key_stocks
        self.max_key_stocks = max_key_stocks

    def _get_theme_info(self, theme_id: str) -> dict:
        """取得主題資訊"""
        theme = self.themes.get(theme_id, {})
        return {
            "id": theme_id,
            "name": theme.get("name", theme_id),
            "name_en": theme.get("name_en", theme_id),
        }

    def _build_primary_event(self, scored_event: ScoredEvent) -> dict:
        """建構主要事件資訊"""
        event = scored_event.event
        return {
            "id": event.id,
            "title": event.title,
            "event_type": scored_event.event_type,
            "summary": event.snippet or event.title,
            "url": event.url,
            "published_at": event.published_at,
            "publishers": [event.publisher] if event.publisher else [],
            "score": scored_event.total_score,
        }

    def _select_key_stocks(
        self,
        primary_event: ScoredEvent,
        companies: dict[str, CompanyData],
    ) -> list[dict]:
        """選擇關鍵個股

        Args:
            primary_event: 主要事件
            companies: 公司資料

        Returns:
            關鍵個股列表
        """
        key_stocks = []
        matched_tickers = primary_event.matched_tickers

        # 首先加入直接匹配的 tickers
        for i, ticker in enumerate(matched_tickers[:self.max_key_stocks]):
            role = "primary" if i == 0 else "peer"
            key_stocks.append({
                "ticker": ticker,
                "name": companies.get(ticker, CompanyData(ticker=ticker)).name,
                "role": role,
                "thesis": None,
                "catalysts": [],
                "risks": [],
            })

        # 如果不夠，從同業補充
        if len(key_stocks) < self.min_key_stocks and matched_tickers:
            primary_ticker = matched_tickers[0]
            if primary_ticker in companies:
                peers = companies[primary_ticker].peers
                for peer in peers:
                    if len(key_stocks) >= self.max_key_stocks:
                        break
                    if peer not in [ks["ticker"] for ks in key_stocks]:
                        key_stocks.append({
                            "ticker": peer,
                            "name": companies.get(peer, CompanyData(ticker=peer)).name,
                            "role": "peer",
                            "thesis": None,
                            "catalysts": [],
                            "risks": [],
                        })

        return key_stocks

    def _build_sources(
        self,
        scored_events: list[ScoredEvent],
        limit: int = 20,
    ) -> list[dict]:
        """建構來源列表

        Args:
            scored_events: 評分事件列表
            limit: 最大來源數

        Returns:
            來源列表
        """
        sources = []
        seen_urls = set()

        for scored in scored_events[:limit]:
            event = scored.event
            if event.url in seen_urls:
                continue
            seen_urls.add(event.url)

            sources.append({
                "title": event.title,
                "url": event.url,
                "publisher": event.publisher,
                "published_at": event.published_at,
                "type": "news",
            })

        return sources

    def build(
        self,
        scored_events: list[ScoredEvent],
        companies: dict[str, CompanyData],
        edition: str = "postclose",
        run_id: Optional[str] = None,
    ) -> ResearchPack:
        """建構研究包

        Args:
            scored_events: 評分後的事件列表
            companies: 公司資料字典
            edition: 版本 (premarket/postclose/intraday)
            run_id: 執行 ID

        Returns:
            ResearchPack 實例
        """
        run_id = run_id or get_run_id()
        now = get_now()

        # 選擇主要事件
        scorer = EventScorer()
        primary_scored = scorer.select_primary(scored_events)

        if not primary_scored:
            raise ValueError("No suitable primary event found")

        # 決定主要主題
        primary_theme_id = (
            primary_scored.matched_themes[0]
            if primary_scored.matched_themes
            else "other"
        )

        # 選擇關鍵個股
        key_stocks = self._select_key_stocks(primary_scored, companies)

        # 確保至少有 min_key_stocks 個
        if len(key_stocks) < self.min_key_stocks:
            logger.warning(
                f"Only {len(key_stocks)} key stocks found, "
                f"minimum is {self.min_key_stocks}"
            )

        # 建構研究包
        pack = ResearchPack(
            meta={
                "run_id": run_id,
                "created_at": format_datetime(now, "iso"),
                "edition": edition,
                "version": "0.1.0",
            },
            primary_event=self._build_primary_event(primary_scored),
            primary_theme=self._get_theme_info(primary_theme_id),
            key_stocks=key_stocks,
            candidate_events=[e.to_dict() for e in scored_events[:50]],
            companies={t: c.to_dict() for t, c in companies.items()},
            sources=self._build_sources(scored_events),
            selection_rationale={
                "reason": f"Highest scoring event with type '{primary_scored.event_type}'",
                "score_ranking": [
                    {"event_id": e.event.id, "score": e.total_score}
                    for e in scored_events[:10]
                ],
                "data_gaps": self._identify_data_gaps(key_stocks, companies),
            },
        )

        return pack

    def _identify_data_gaps(
        self,
        key_stocks: list[dict],
        companies: dict[str, CompanyData],
    ) -> list[str]:
        """識別資料缺口

        Args:
            key_stocks: 關鍵個股
            companies: 公司資料

        Returns:
            資料缺口列表
        """
        gaps = []

        for stock in key_stocks:
            ticker = stock["ticker"]
            if ticker not in companies:
                gaps.append(f"{ticker}: No company data")
                continue

            company = companies[ticker]
            if company.error:
                gaps.append(f"{ticker}: {company.error}")
                continue

            if not company.price:
                gaps.append(f"{ticker}: No price data")
            if not company.fundamentals:
                gaps.append(f"{ticker}: No fundamentals data")
            if not company.estimates:
                gaps.append(f"{ticker}: No estimates data")

        return gaps

    def validate(self, pack: ResearchPack) -> tuple[bool, list[str]]:
        """驗證研究包

        Args:
            pack: 研究包

        Returns:
            (is_valid, errors)
        """
        if not self.schema:
            logger.warning("No schema loaded, skipping validation")
            return True, []

        errors = []

        try:
            jsonschema.validate(pack.to_dict(), self.schema)
        except jsonschema.ValidationError as e:
            errors.append(f"Schema validation error: {e.message}")
        except jsonschema.SchemaError as e:
            errors.append(f"Schema error: {e.message}")

        # 額外檢查
        if len(pack.sources) < 5:
            errors.append(f"Insufficient sources: {len(pack.sources)} < 5")

        if len(pack.key_stocks) < self.min_key_stocks:
            errors.append(
                f"Insufficient key stocks: {len(pack.key_stocks)} < {self.min_key_stocks}"
            )

        return len(errors) == 0, errors

    def save(
        self,
        pack: ResearchPack,
        output_path: str = "out/research_pack.json",
    ) -> Path:
        """儲存研究包

        Args:
            pack: 研究包
            output_path: 輸出路徑

        Returns:
            輸出檔案路徑
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            f.write(pack.to_json())

        logger.info(f"Research pack saved to {output_path}")
        return output_path


def main():
    """CLI demo"""
    import argparse
    from rich.console import Console
    from rich.json import JSON

    from ..collectors.google_news_rss import GoogleNewsCollector
    from ..enrichers.fmp import FMPEnricher
    from .event_scoring import EventScorer

    parser = argparse.ArgumentParser(description="Research Pack Builder")
    parser.add_argument("--output", "-o", default="out/research_pack.json", help="Output path")
    parser.add_argument("--edition", "-e", default="postclose", help="Edition")
    args = parser.parse_args()

    console = Console()

    # 1. 收集新聞
    console.print("[bold cyan]Step 1: Collecting news...[/bold cyan]")
    collector = GoogleNewsCollector()
    events = collector.fetch_query("NVDA stock", limit=10)
    events += collector.fetch_query("AI chip semiconductor", limit=5)
    console.print(f"Collected {len(events)} events")

    # 2. 評分
    console.print("[bold cyan]Step 2: Scoring events...[/bold cyan]")
    scorer = EventScorer()
    scored = scorer.score_events(events)
    console.print(f"Scored {len(scored)} events")

    # 3. 補充資料 (只補主要 tickers)
    console.print("[bold cyan]Step 3: Enriching companies...[/bold cyan]")
    primary = scorer.select_primary(scored)
    tickers_to_enrich = primary.matched_tickers[:4] if primary else ["NVDA"]

    companies = {}
    with FMPEnricher() as enricher:
        for ticker in tickers_to_enrich:
            console.print(f"  Enriching {ticker}...")
            companies[ticker] = enricher.enrich(ticker)

    # 4. 建構研究包
    console.print("[bold cyan]Step 4: Building research pack...[/bold cyan]")
    builder = ResearchPackBuilder()
    pack = builder.build(scored, companies, edition=args.edition)

    # 5. 驗證
    console.print("[bold cyan]Step 5: Validating...[/bold cyan]")
    is_valid, errors = builder.validate(pack)

    if is_valid:
        console.print("[green]✓ Validation passed[/green]")
    else:
        console.print("[red]✗ Validation failed:[/red]")
        for error in errors:
            console.print(f"  - {error}")

    # 6. 儲存
    console.print("[bold cyan]Step 6: Saving...[/bold cyan]")
    output_path = builder.save(pack, args.output)
    console.print(f"[green]Saved to {output_path}[/green]")

    # 顯示摘要
    console.print("\n[bold]Research Pack Summary:[/bold]")
    console.print(f"  Run ID: {pack.meta['run_id']}")
    console.print(f"  Primary Event: {pack.primary_event['title'][:60]}...")
    console.print(f"  Primary Theme: {pack.primary_theme['name']}")
    console.print(f"  Key Stocks: {', '.join(s['ticker'] for s in pack.key_stocks)}")
    console.print(f"  Sources: {len(pack.sources)}")


if __name__ == "__main__":
    main()

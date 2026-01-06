"""Layer 2 Radar Fillers - 備援新聞來源

當 Google News 來源不足 8 條時，從以下來源補充：
1. SEC 8-K/Form 4/13D filings (高信號密度)
2. FMP Gainers/Losers (異常漲跌)
3. Macro Calendar (經濟日曆)

這些來源確保每日 News Radar 至少有 8 條新聞。
"""

import hashlib
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

import httpx

from ..storage.cache import FileCache
from ..utils.logging import get_logger
from ..utils.http import RateLimiter

logger = get_logger(__name__)


@dataclass
class RadarItem:
    """雷達項目資料結構"""

    id: str
    headline: str
    headline_zh: Optional[str] = None
    source: str = ""
    source_type: str = ""  # sec_filing, market_mover, macro_calendar
    url: Optional[str] = None
    timestamp: Optional[str] = None
    impact_score: int = 50  # 0-100
    affected_sectors: List[str] = field(default_factory=list)
    affected_tickers: List[str] = field(default_factory=list)
    direction: str = "mixed"  # positive, negative, mixed
    filler_rank: int = 99  # 填充優先順序

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "headline": self.headline,
            "headline_zh": self.headline_zh,
            "source": self.source,
            "source_type": self.source_type,
            "url": self.url,
            "timestamp": self.timestamp,
            "impact_score": self.impact_score,
            "affected_sectors": self.affected_sectors,
            "affected_tickers": self.affected_tickers,
            "direction": self.direction,
            "filler_rank": self.filler_rank,
        }

    def to_news_item(self) -> dict:
        """轉換為 news_items 格式"""
        return {
            "rank": self.filler_rank,
            "type": "mention",  # Layer 2 fillers 都是 mention 類型
            "headline": self.headline,
            "headline_zh": self.headline_zh,
            "source": self.source,
            "url": self.url,
            "timestamp": self.timestamp,
            "impact_score": self.impact_score,
            "catalyst_type": "company",
            "affected_sectors": self.affected_sectors,
            "affected_tickers": self.affected_tickers,
            "direction": self.direction,
            "source_type": self.source_type,
        }


class SECFilingsCollector:
    """SEC Filings Collector (8-K, Form 4, 13D)

    使用 SEC EDGAR API 抓取近期重要申報。
    """

    BASE_URL = "https://data.sec.gov"

    # 重要申報類型
    IMPORTANT_FORM_TYPES = [
        "8-K",      # 重大事件
        "4",        # 內部人交易
        "13D",      # 大股東持股變動
        "13G",      # 被動投資人持股
        "SC 13D",   # Schedule 13D
        "SC 13G",   # Schedule 13G
    ]

    # Universe ticker to CIK mapping (常見大型股)
    # 實際應從資料庫或 API 查詢
    TICKER_CIK_MAP = {
        "NVDA": "0001045810",
        "AMD": "0000002488",
        "AVGO": "0001649338",
        "TSM": "0001046179",
        "ASML": "0000937966",
        "MSFT": "0000789019",
        "GOOGL": "0001652044",
        "AMZN": "0001018724",
        "META": "0001326801",
        "AAPL": "0000320193",
        "TSLA": "0001318605",
        "PLTR": "0001321655",
    }

    def __init__(
        self,
        cache: Optional[FileCache] = None,
        cache_ttl: int = 600,
    ):
        self.cache = cache or FileCache(cache_dir="data/cache/sec", default_ttl=cache_ttl)
        self.cache_ttl = cache_ttl
        self._client = httpx.Client(
            timeout=httpx.Timeout(30.0),
            headers={
                "User-Agent": "DailyDeepBrief/0.1.0 (contact@example.com)",
                "Accept": "application/json",
            },
        )

    def _generate_id(self, content: str) -> str:
        """生成唯一 ID"""
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def get_recent_filings(
        self,
        tickers: List[str],
        days_back: int = 1,
        limit: int = 10,
    ) -> List[RadarItem]:
        """取得近期 SEC 申報

        Args:
            tickers: 要查詢的股票代碼
            days_back: 往回查幾天
            limit: 最大數量

        Returns:
            RadarItem 列表
        """
        items = []
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)

        for ticker in tickers:
            cik = self.TICKER_CIK_MAP.get(ticker.upper())
            if not cik:
                continue

            # 使用 SEC EDGAR submissions API
            cache_key = f"sec:filings:{cik}"
            cached = self.cache.get(cache_key)

            if cached:
                filings_data = cached
            else:
                try:
                    # SEC EDGAR Company Filings API
                    url = f"{self.BASE_URL}/submissions/CIK{cik}.json"
                    response = self._client.get(url)
                    response.raise_for_status()
                    filings_data = response.json()
                    self.cache.set(cache_key, filings_data, self.cache_ttl)
                except Exception as e:
                    logger.warning(f"Failed to fetch SEC filings for {ticker}: {e}")
                    continue

            # 解析 recent filings
            recent = filings_data.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accessions = recent.get("accessionNumber", [])
            descriptions = recent.get("primaryDocument", [])

            for i, (form, date_str, accession) in enumerate(zip(forms, dates, accessions)):
                if i >= 20:  # 只看最近 20 筆
                    break

                # 過濾申報類型
                if form not in self.IMPORTANT_FORM_TYPES:
                    continue

                # 過濾日期
                try:
                    filing_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    if filing_date < cutoff_date:
                        continue
                except ValueError:
                    continue

                # 建立 RadarItem
                accession_clean = accession.replace("-", "")
                filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession_clean}"

                # 根據 form 類型設定 headline
                if form == "8-K":
                    headline = f"{ticker} files 8-K (Material Event)"
                    headline_zh = f"{ticker} 提交 8-K 重大事件申報"
                    impact = 70
                elif form in ["4"]:
                    headline = f"{ticker} insider trading reported (Form 4)"
                    headline_zh = f"{ticker} 內部人交易申報 (Form 4)"
                    impact = 55
                elif form in ["13D", "SC 13D"]:
                    headline = f"{ticker} activist investor filing (13D)"
                    headline_zh = f"{ticker} 大股東持股變動申報 (13D)"
                    impact = 75
                else:
                    headline = f"{ticker} SEC filing: {form}"
                    headline_zh = f"{ticker} SEC 申報: {form}"
                    impact = 50

                item = RadarItem(
                    id=self._generate_id(f"{ticker}:{form}:{accession}"),
                    headline=headline,
                    headline_zh=headline_zh,
                    source="SEC EDGAR",
                    source_type="sec_filing",
                    url=filing_url,
                    timestamp=filing_date.isoformat(),
                    impact_score=impact,
                    affected_tickers=[ticker],
                    direction="mixed",
                    filler_rank=6,  # SEC filings 排在 #6
                )
                items.append(item)

                if len(items) >= limit:
                    return items

        return items[:limit]

    def close(self):
        self._client.close()


class FMPMarketMoversCollector:
    """FMP Gainers/Losers/Active Collector

    取得異常漲跌幅和成交量的股票。
    """

    BASE_URL = "https://financialmodelingprep.com/stable"

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache: Optional[FileCache] = None,
        cache_ttl: int = 300,
    ):
        self.api_key = api_key or os.getenv("FMP_API_KEY")
        self.cache = cache or FileCache(cache_dir="data/cache/fmp", default_ttl=cache_ttl)
        self.cache_ttl = cache_ttl
        self._client = httpx.Client(
            timeout=httpx.Timeout(30.0),
            headers={"User-Agent": "DailyDeepBrief/0.1.0"},
        )

    def _generate_id(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _request(self, endpoint: str, params: Optional[dict] = None) -> Optional[list]:
        """發送 FMP API 請求"""
        if not self.api_key:
            logger.warning("FMP_API_KEY not set")
            return None

        cache_key = f"fmp:{endpoint}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        url = f"{self.BASE_URL}/{endpoint}"
        params = params or {}
        params["apikey"] = self.api_key

        try:
            response = self._client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            self.cache.set(cache_key, data, self.cache_ttl)
            return data
        except Exception as e:
            logger.warning(f"FMP request failed for {endpoint}: {e}")
            return None

    def get_gainers(self, limit: int = 3) -> List[RadarItem]:
        """取得漲幅最大的股票"""
        data = self._request("biggest-gainers")
        if not data:
            return []

        items = []
        for i, stock in enumerate(data[:limit]):
            ticker = stock.get("symbol", "")
            change = stock.get("changesPercentage", 0)
            price = stock.get("price", 0)

            item = RadarItem(
                id=self._generate_id(f"gainer:{ticker}:{change}"),
                headline=f"{ticker} surges {change:+.1f}% to ${price:.2f}",
                headline_zh=f"{ticker} 大漲 {change:+.1f}%，股價 ${price:.2f}",
                source="FMP Market Data",
                source_type="market_mover",
                url=f"https://finance.yahoo.com/quote/{ticker}",
                timestamp=datetime.now(timezone.utc).isoformat(),
                impact_score=min(60 + int(abs(change) * 2), 90),
                affected_tickers=[ticker],
                direction="positive",
                filler_rank=7,
            )
            items.append(item)

        return items

    def get_losers(self, limit: int = 3) -> List[RadarItem]:
        """取得跌幅最大的股票"""
        data = self._request("biggest-losers")
        if not data:
            return []

        items = []
        for i, stock in enumerate(data[:limit]):
            ticker = stock.get("symbol", "")
            change = stock.get("changesPercentage", 0)
            price = stock.get("price", 0)

            item = RadarItem(
                id=self._generate_id(f"loser:{ticker}:{change}"),
                headline=f"{ticker} drops {change:.1f}% to ${price:.2f}",
                headline_zh=f"{ticker} 大跌 {change:.1f}%，股價 ${price:.2f}",
                source="FMP Market Data",
                source_type="market_mover",
                url=f"https://finance.yahoo.com/quote/{ticker}",
                timestamp=datetime.now(timezone.utc).isoformat(),
                impact_score=min(60 + int(abs(change) * 2), 90),
                affected_tickers=[ticker],
                direction="negative",
                filler_rank=7,
            )
            items.append(item)

        return items

    def get_most_active(self, limit: int = 3) -> List[RadarItem]:
        """取得成交量最大的股票"""
        data = self._request("most-actives")
        if not data:
            return []

        items = []
        for i, stock in enumerate(data[:limit]):
            ticker = stock.get("symbol", "")
            volume = stock.get("volume", 0)
            change = stock.get("changesPercentage", 0)

            # 格式化成交量
            if volume >= 1e9:
                vol_str = f"{volume/1e9:.1f}B"
            elif volume >= 1e6:
                vol_str = f"{volume/1e6:.1f}M"
            else:
                vol_str = f"{volume/1e3:.0f}K"

            direction = "positive" if change >= 0 else "negative"

            item = RadarItem(
                id=self._generate_id(f"active:{ticker}:{volume}"),
                headline=f"{ticker} sees heavy volume ({vol_str} shares), {change:+.1f}%",
                headline_zh=f"{ticker} 成交量暴增（{vol_str} 股），漲跌 {change:+.1f}%",
                source="FMP Market Data",
                source_type="market_mover",
                url=f"https://finance.yahoo.com/quote/{ticker}",
                timestamp=datetime.now(timezone.utc).isoformat(),
                impact_score=55,
                affected_tickers=[ticker],
                direction=direction,
                filler_rank=8,
            )
            items.append(item)

        return items

    def close(self):
        self._client.close()


class MacroCalendarCollector:
    """Macro Calendar Collector

    取得經濟日曆事件（CPI、FOMC、就業數據等）。
    使用 FMP Economic Calendar API。
    """

    BASE_URL = "https://financialmodelingprep.com/stable"

    # 重要經濟事件關鍵字
    HIGH_IMPACT_KEYWORDS = [
        "FOMC", "Fed", "Interest Rate", "CPI", "PPI", "NFP", "Non-Farm",
        "GDP", "Unemployment", "Retail Sales", "PMI", "ISM",
        "Consumer Confidence", "Housing Starts", "Durable Goods",
    ]

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache: Optional[FileCache] = None,
        cache_ttl: int = 1800,
    ):
        self.api_key = api_key or os.getenv("FMP_API_KEY")
        self.cache = cache or FileCache(cache_dir="data/cache/fmp", default_ttl=cache_ttl)
        self.cache_ttl = cache_ttl
        self._client = httpx.Client(
            timeout=httpx.Timeout(30.0),
            headers={"User-Agent": "DailyDeepBrief/0.1.0"},
        )

    def _generate_id(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _is_high_impact(self, event_name: str) -> bool:
        """判斷是否為高影響事件"""
        event_upper = event_name.upper()
        return any(kw.upper() in event_upper for kw in self.HIGH_IMPACT_KEYWORDS)

    def get_upcoming_events(
        self,
        days_ahead: int = 2,
        limit: int = 5,
    ) -> List[RadarItem]:
        """取得即將到來的經濟事件

        Args:
            days_ahead: 往前看幾天
            limit: 最大數量

        Returns:
            RadarItem 列表
        """
        if not self.api_key:
            logger.warning("FMP_API_KEY not set for macro calendar")
            return []

        today = datetime.now(timezone.utc).date()
        end_date = today + timedelta(days=days_ahead)

        cache_key = f"fmp:econ_calendar:{today}:{end_date}"
        cached = self.cache.get(cache_key)

        if cached:
            data = cached
        else:
            url = f"{self.BASE_URL}/economic-calendar"
            params = {
                "apikey": self.api_key,
                "from": today.isoformat(),
                "to": end_date.isoformat(),
            }

            try:
                response = self._client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                self.cache.set(cache_key, data, self.cache_ttl)
            except Exception as e:
                logger.warning(f"Failed to fetch economic calendar: {e}")
                return []

        items = []
        for event in data:
            event_name = event.get("event", "")

            # 過濾只保留高影響事件
            if not self._is_high_impact(event_name):
                continue

            date_str = event.get("date", "")
            country = event.get("country", "US")

            # 只保留美國事件
            if country != "US":
                continue

            # 建立 headline
            actual = event.get("actual")
            estimate = event.get("estimate")
            previous = event.get("previous")

            if actual is not None:
                headline = f"{event_name}: {actual} (est. {estimate}, prev. {previous})"
                headline_zh = f"{event_name}: 實際 {actual}（預期 {estimate}，前值 {previous}）"
                direction = "positive" if actual > estimate else "negative" if actual < estimate else "mixed"
            else:
                headline = f"Upcoming: {event_name} (est. {estimate})"
                headline_zh = f"即將公布: {event_name}（預期 {estimate}）"
                direction = "mixed"

            item = RadarItem(
                id=self._generate_id(f"macro:{event_name}:{date_str}"),
                headline=headline,
                headline_zh=headline_zh,
                source="Economic Calendar",
                source_type="macro_calendar",
                url=None,
                timestamp=date_str,
                impact_score=80,  # 宏觀事件影響分數高
                affected_sectors=["Market"],
                affected_tickers=[],
                direction=direction,
                filler_rank=5,  # 宏觀事件排在 #5
            )
            items.append(item)

            if len(items) >= limit:
                break

        return items

    def close(self):
        self._client.close()


class RadarFillersCollector:
    """Layer 2 Radar Fillers 整合收集器

    整合所有 Layer 2 來源，確保 news_items >= 8。
    """

    def __init__(
        self,
        fmp_api_key: Optional[str] = None,
        cache: Optional[FileCache] = None,
    ):
        self.sec_collector = SECFilingsCollector(cache=cache)
        self.market_movers = FMPMarketMoversCollector(api_key=fmp_api_key, cache=cache)
        self.macro_calendar = MacroCalendarCollector(api_key=fmp_api_key, cache=cache)

    def collect_fillers(
        self,
        universe_tickers: List[str],
        existing_count: int,
        target_count: int = 8,
    ) -> List[RadarItem]:
        """收集填充項目

        Args:
            universe_tickers: 宇宙中的股票代碼
            existing_count: 已有的新聞數量
            target_count: 目標數量

        Returns:
            RadarItem 列表
        """
        needed = target_count - existing_count
        if needed <= 0:
            logger.info(f"No fillers needed (existing: {existing_count})")
            return []

        logger.info(f"Need {needed} fillers (existing: {existing_count}, target: {target_count})")

        all_items = []

        # 1. Macro Calendar (高優先)
        try:
            macro_items = self.macro_calendar.get_upcoming_events(days_ahead=2, limit=2)
            all_items.extend(macro_items)
            logger.info(f"Collected {len(macro_items)} macro calendar events")
        except Exception as e:
            logger.warning(f"Failed to collect macro calendar: {e}")

        # 2. SEC Filings
        try:
            sec_items = self.sec_collector.get_recent_filings(
                tickers=universe_tickers[:20],  # 只查前 20 個
                days_back=1,
                limit=3,
            )
            all_items.extend(sec_items)
            logger.info(f"Collected {len(sec_items)} SEC filings")
        except Exception as e:
            logger.warning(f"Failed to collect SEC filings: {e}")

        # 3. Market Movers (Gainers + Losers + Active)
        try:
            gainers = self.market_movers.get_gainers(limit=2)
            losers = self.market_movers.get_losers(limit=2)
            active = self.market_movers.get_most_active(limit=2)

            all_items.extend(gainers)
            all_items.extend(losers)
            all_items.extend(active)
            logger.info(f"Collected {len(gainers) + len(losers) + len(active)} market movers")
        except Exception as e:
            logger.warning(f"Failed to collect market movers: {e}")

        # 排序：先按 filler_rank，再按 impact_score
        all_items.sort(key=lambda x: (x.filler_rank, -x.impact_score))

        # 去重（根據 ticker）
        seen_tickers = set()
        unique_items = []
        for item in all_items:
            ticker_key = tuple(item.affected_tickers) if item.affected_tickers else (item.id,)
            if ticker_key not in seen_tickers:
                seen_tickers.add(ticker_key)
                unique_items.append(item)

        return unique_items[:needed]

    def close(self):
        self.sec_collector.close()
        self.market_movers.close()
        self.macro_calendar.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def ensure_minimum_news_items(
    news_items: List[Dict],
    universe_tickers: List[str],
    min_count: int = 8,
) -> List[Dict]:
    """確保新聞項目至少有 min_count 條

    Args:
        news_items: 現有的 news_items 列表
        universe_tickers: 宇宙中的股票代碼
        min_count: 最少數量

    Returns:
        補充後的 news_items 列表
    """
    if len(news_items) >= min_count:
        return news_items

    with RadarFillersCollector() as collector:
        fillers = collector.collect_fillers(
            universe_tickers=universe_tickers,
            existing_count=len(news_items),
            target_count=min_count,
        )

        # 將 RadarItem 轉換為 news_item 格式並加入
        for i, filler in enumerate(fillers):
            filler.filler_rank = len(news_items) + i + 1
            news_items.append(filler.to_news_item())

    return news_items


def main():
    """CLI demo"""
    import argparse
    from rich.console import Console
    from rich.table import Table

    parser = argparse.ArgumentParser(description="Radar Fillers Collector")
    parser.add_argument("--source", "-s", choices=["all", "sec", "movers", "macro"], default="all")
    parser.add_argument("--limit", "-n", type=int, default=5)
    args = parser.parse_args()

    console = Console()

    console.print("[bold cyan]Layer 2 Radar Fillers[/bold cyan]\n")

    universe = ["NVDA", "AMD", "AVGO", "TSM", "MSFT", "GOOGL", "AMZN", "META", "AAPL", "TSLA"]

    with RadarFillersCollector() as collector:
        items = []

        if args.source in ["all", "macro"]:
            console.print("[yellow]Collecting macro calendar...[/yellow]")
            items.extend(collector.macro_calendar.get_upcoming_events(limit=args.limit))

        if args.source in ["all", "sec"]:
            console.print("[yellow]Collecting SEC filings...[/yellow]")
            items.extend(collector.sec_collector.get_recent_filings(universe, limit=args.limit))

        if args.source in ["all", "movers"]:
            console.print("[yellow]Collecting market movers...[/yellow]")
            items.extend(collector.market_movers.get_gainers(limit=2))
            items.extend(collector.market_movers.get_losers(limit=2))

    # 顯示結果
    table = Table(title=f"Radar Fillers ({len(items)} items)")
    table.add_column("Rank", style="dim")
    table.add_column("Type", style="cyan")
    table.add_column("Headline", max_width=50)
    table.add_column("Tickers", style="yellow")
    table.add_column("Impact", style="green")

    for item in items:
        table.add_row(
            str(item.filler_rank),
            item.source_type,
            item.headline[:50] + "..." if len(item.headline) > 50 else item.headline,
            ", ".join(item.affected_tickers) or "-",
            str(item.impact_score),
        )

    console.print(table)


if __name__ == "__main__":
    main()

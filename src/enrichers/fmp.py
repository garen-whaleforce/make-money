"""Financial Modeling Prep (FMP) Enricher

https://financialmodelingprep.com/
"""

import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Union

import httpx

from ..replay.recorder import ReplayMode, get_recorder
from ..storage.cache import FileCache
from ..utils.logging import get_logger
from ..utils.http import RateLimiter
from .base import (
    BaseEnricher,
    CompanyData,
    PriceData,
    Fundamentals,
    Estimates,
)

logger = get_logger(__name__)


class FMPEnricher(BaseEnricher):
    """FMP 資料補完器"""

    BASE_URL = "https://financialmodelingprep.com/stable"

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache: Optional[FileCache] = None,
        cache_ttl: int = 3600,
        timeout: float = 30.0,
        max_retries: int = 3,
        rate_limit_rpm: int = 300,
    ):
        """初始化 FMP Enricher

        Args:
            api_key: FMP API Key (預設從環境變數讀取)
            cache: 快取實例
            cache_ttl: 快取 TTL (秒)
            timeout: 請求超時 (秒)
            max_retries: 最大重試次數
            rate_limit_rpm: 每分鐘請求限制
        """
        self.api_key = api_key or os.getenv("FMP_API_KEY")
        if not self.api_key:
            logger.warning("FMP_API_KEY not set")

        self.cache = cache or FileCache(cache_dir="data/cache/fmp", default_ttl=cache_ttl)
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.max_retries = max_retries
        self.rate_limiter = RateLimiter(requests_per_minute=rate_limit_rpm)

        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": "DailyDeepBrief/0.1.0"},
        )

    @property
    def provider_name(self) -> str:
        return "fmp"

    def _request(self, endpoint: str, params: Optional[dict] = None) -> Optional[Union[dict, list]]:
        """發送 API 請求

        Args:
            endpoint: API endpoint
            params: 查詢參數

        Returns:
            JSON 回應或 None
        """
        # 檢查是否有 replay recorder
        recorder = get_recorder()
        request_params = {k: v for k, v in (params or {}).items() if k != "apikey"}

        if recorder:
            def make_request() -> tuple[Any, int, float]:
                return self._do_request(endpoint, params)

            response, status_code = recorder.get_or_call(
                provider="fmp",
                endpoint=endpoint,
                params=request_params,
                call_fn=make_request,
            )
            return response

        # 沒有 recorder，直接呼叫
        response, _, _ = self._do_request(endpoint, params)
        return response

    def _do_request(self, endpoint: str, params: Optional[dict] = None) -> tuple[Any, int, float]:
        """實際執行 API 請求

        Args:
            endpoint: API endpoint
            params: 查詢參數

        Returns:
            (response, status_code, response_time_ms)
        """
        if not self.api_key:
            logger.error("FMP API key not configured")
            return None, 401, 0

        url = f"{self.BASE_URL}/{endpoint}"
        params = params or {}
        params["apikey"] = self.api_key

        # 速率限制
        self.rate_limiter.wait()

        start_time = time.time()

        for attempt in range(self.max_retries):
            try:
                response = self._client.get(url, params=params)
                response_time = (time.time() - start_time) * 1000
                response.raise_for_status()
                return response.json(), response.status_code, response_time

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    wait_time = 2 ** attempt
                    logger.warning(f"Rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
                elif e.response.status_code == 401:
                    logger.error("Invalid FMP API key")
                    return None, 401, 0
                else:
                    logger.error(f"HTTP error: {e}")
                    if attempt == self.max_retries - 1:
                        return None, e.response.status_code, (time.time() - start_time) * 1000

            except httpx.RequestError as e:
                logger.error(f"Request error: {e}")
                if attempt == self.max_retries - 1:
                    return None, 500, (time.time() - start_time) * 1000
                time.sleep(2 ** attempt)

        return None, 500, (time.time() - start_time) * 1000

    def _cached_request(
        self,
        cache_key: str,
        endpoint: str,
        params: Optional[dict] = None,
    ) -> Optional[Union[dict, list]]:
        """帶快取的 API 請求"""
        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Cache hit: {cache_key}")
            return cached

        result = self._request(endpoint, params)
        if result is not None:
            self.cache.set(cache_key, result, self.cache_ttl)

        return result

    def get_quote(self, ticker: str) -> Optional[PriceData]:
        """取得即時報價

        Args:
            ticker: 股票代碼

        Returns:
            PriceData 或 None
        """
        cache_key = f"fmp:quote:{ticker}"
        data = self._cached_request(cache_key, "quote", {"symbol": ticker})

        if not data or not isinstance(data, list) or len(data) == 0:
            return None

        quote = data[0]
        current_price = quote.get("price")

        # B2: Get 52-week high/low and YTD data from key metrics
        high_52w = None
        low_52w = None
        change_ytd = None
        avg_volume = None

        # Try to get 52W data from key metrics
        cache_key_metrics = f"fmp:key_metrics_ttm:{ticker}"
        metrics = self._cached_request(cache_key_metrics, "key-metrics-ttm", {"symbol": ticker})
        if metrics and isinstance(metrics, list) and len(metrics) > 0:
            m = metrics[0]
            # FMP provides these in key metrics
            high_52w = m.get("yearHigh")
            low_52w = m.get("yearLow")

        # Get YTD change from stock price change endpoint
        try:
            cache_key_change = f"fmp:stock_price_change:{ticker}"
            change_data = self._cached_request(cache_key_change, "stock-price-change", {"symbol": ticker})
            if change_data and isinstance(change_data, list) and len(change_data) > 0:
                change_ytd = change_data[0].get("ytd")
        except Exception as e:
            logger.debug(f"Could not get YTD change for {ticker}: {e}")

        # Get average volume from quote (avgVolume field)
        avg_volume = quote.get("avgVolume")

        return PriceData(
            last=current_price,
            change_pct_1d=quote.get("changePercentage") or quote.get("changesPercentage"),
            volume=quote.get("volume"),
            market_cap=quote.get("marketCap"),
            as_of=datetime.now(timezone.utc).isoformat(),
            # B2: Additional fields for Deep Dive completeness
            change_ytd=change_ytd,
            high_52w=high_52w,
            low_52w=low_52w,
            avg_volume=avg_volume,
        )

    def get_fundamentals(self, ticker: str) -> Optional[Fundamentals]:
        """取得基礎財務

        Args:
            ticker: 股票代碼

        Returns:
            Fundamentals 或 None
        """
        # 取得 key metrics TTM
        cache_key = f"fmp:key_metrics_ttm:{ticker}"
        metrics = self._cached_request(cache_key, "key-metrics-ttm", {"symbol": ticker})

        if not metrics or not isinstance(metrics, list) or len(metrics) == 0:
            return None

        m = metrics[0]

        # 取得 ratios TTM
        cache_key_ratios = f"fmp:ratios_ttm:{ticker}"
        ratios = self._cached_request(cache_key_ratios, "ratios-ttm", {"symbol": ticker})
        r = ratios[0] if ratios and isinstance(ratios, list) and len(ratios) > 0 else {}

        # 取得最近 4 季 income statement 來計算 TTM
        cache_key_income = f"fmp:income_4q:{ticker}"
        income = self._cached_request(cache_key_income, "income-statement", {"symbol": ticker, "limit": 4, "period": "quarter"})

        # 計算 TTM 數值 (加總最近 4 季)
        revenue_ttm = None
        net_income_ttm = None
        ebitda_ttm = None

        if income and isinstance(income, list) and len(income) >= 4:
            # 確保有足夠的季度資料
            try:
                revenue_ttm = sum(q.get("revenue", 0) or 0 for q in income[:4])
                net_income_ttm = sum(q.get("netIncome", 0) or 0 for q in income[:4])
                ebitda_ttm = sum(q.get("ebitda", 0) or 0 for q in income[:4])
            except (TypeError, ValueError) as e:
                logger.warning(f"Error calculating TTM for {ticker}: {e}")
        elif income and isinstance(income, list) and len(income) > 0:
            # Fallback: 使用最近一季的年化數據
            latest = income[0]
            revenue_ttm = latest.get("revenue")
            net_income_ttm = latest.get("netIncome")
            ebitda_ttm = latest.get("ebitda")

        # 取得 cash flow
        cache_key_cf = f"fmp:cashflow_4q:{ticker}"
        cashflow = self._cached_request(cache_key_cf, "cash-flow-statement", {"symbol": ticker, "limit": 4, "period": "quarter"})

        fcf_ttm = None
        if cashflow and isinstance(cashflow, list) and len(cashflow) >= 4:
            try:
                fcf_ttm = sum(q.get("freeCashFlow", 0) or 0 for q in cashflow[:4])
            except (TypeError, ValueError):
                pass
        elif cashflow and isinstance(cashflow, list) and len(cashflow) > 0:
            fcf_ttm = cashflow[0].get("freeCashFlow")

        return Fundamentals(
            revenue_ttm=revenue_ttm,
            ebitda_ttm=ebitda_ttm,
            net_income_ttm=net_income_ttm,
            fcf_ttm=fcf_ttm,
            gross_margin=r.get("grossProfitMarginTTM"),
            operating_margin=r.get("operatingProfitMarginTTM"),
            net_margin=r.get("netProfitMarginTTM"),
            debt_to_equity=r.get("debtEquityRatioTTM"),
            current_ratio=r.get("currentRatioTTM"),
        )

    def get_company_profile(self, ticker: str) -> Optional[dict]:
        """取得公司基本資料

        Args:
            ticker: 股票代碼

        Returns:
            公司資料字典或 None
        """
        cache_key = f"fmp:profile:{ticker}"
        data = self._cached_request(cache_key, "profile", {"symbol": ticker})

        if not data or not isinstance(data, list) or len(data) == 0:
            return None

        profile = data[0]

        # 取得同業
        peers = self.get_peers(ticker)

        return {
            "name": profile.get("companyName"),
            "sector": profile.get("sector"),
            "industry": profile.get("industry"),
            "description": profile.get("description"),
            "ceo": profile.get("ceo"),
            "country": profile.get("country"),
            "exchange": profile.get("exchangeShortName"),
            "peers": peers,
        }

    def get_peers(self, ticker: str) -> list[str]:
        """取得同業

        Args:
            ticker: 股票代碼

        Returns:
            同業 ticker 列表
        """
        cache_key = f"fmp:peers:{ticker}"
        data = self._cached_request(cache_key, "stock-peers", {"symbol": ticker})

        if not data or not isinstance(data, list) or len(data) == 0:
            return []

        # Stable API returns list of peer objects with 'symbol' key
        # e.g., [{"symbol": "GOOGL", "companyName": "...", ...}, ...]
        return [peer.get("symbol") for peer in data[:10] if peer.get("symbol")]

    def get_market_snapshot(self) -> dict:
        """取得市場概況（v4 Market Snapshot）

        Returns:
            dict with keys: spy_change, qqq_change, us10y, dxy, vix
        """
        snapshot = {
            "spy_change": None,
            "qqq_change": None,
            "us10y": None,
            "dxy": None,
            "vix": None,
        }

        # 取得 SPY, QQQ 報價
        for etf, key in [("SPY", "spy_change"), ("QQQ", "qqq_change")]:
            quote = self.get_quote(etf)
            if quote and quote.change_pct_1d is not None:
                change = quote.change_pct_1d
                prefix = "+" if change >= 0 else ""
                snapshot[key] = f"{prefix}{change:.2f}%"

        # 取得 10Y Treasury (使用 ^TNX)
        cache_key = "fmp:quote:^TNX"
        tnx_data = self._cached_request(cache_key, "quote", {"symbol": "^TNX"})
        if tnx_data and isinstance(tnx_data, list) and len(tnx_data) > 0:
            tnx = tnx_data[0]
            if tnx.get("price"):
                snapshot["us10y"] = f"{tnx['price']:.2f}%"

        # 取得 DXY (美元指數)
        cache_key = "fmp:quote:DX-Y.NYB"
        dxy_data = self._cached_request(cache_key, "quote", {"symbol": "DX-Y.NYB"})
        if dxy_data and isinstance(dxy_data, list) and len(dxy_data) > 0:
            dxy = dxy_data[0]
            if dxy.get("price"):
                snapshot["dxy"] = f"{dxy['price']:.2f}"

        # 取得 VIX
        cache_key = "fmp:quote:^VIX"
        vix_data = self._cached_request(cache_key, "quote", {"symbol": "^VIX"})
        if vix_data and isinstance(vix_data, list) and len(vix_data) > 0:
            vix = vix_data[0]
            if vix.get("price"):
                snapshot["vix"] = f"{vix['price']:.2f}"

        return snapshot

    def get_earnings_calendar(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        tickers: Optional[list[str]] = None,
    ) -> list[dict]:
        """取得財報日曆

        Args:
            from_date: 起始日期 (YYYY-MM-DD)
            to_date: 結束日期 (YYYY-MM-DD)
            tickers: 篩選特定 tickers（可選）

        Returns:
            財報事件列表
        """
        from datetime import datetime, timedelta

        # 預設取得未來 14 天
        if not from_date:
            from_date = datetime.now().strftime("%Y-%m-%d")
        if not to_date:
            to_date = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")

        cache_key = f"fmp:earnings_calendar:{from_date}:{to_date}"
        data = self._cached_request(
            cache_key,
            "earning-calendar",
            {"from": from_date, "to": to_date}
        )

        if not data or not isinstance(data, list):
            return []

        # 轉換為標準格式
        results = []
        for item in data:
            ticker = item.get("symbol")

            # 如果指定 tickers，只保留這些
            if tickers and ticker not in tickers:
                continue

            results.append({
                "ticker": ticker,
                "date": item.get("date"),
                "time": item.get("time"),  # "bmo" (before market open) or "amc" (after market close)
                "eps_estimated": item.get("epsEstimated"),
                "eps_actual": item.get("eps"),
                "revenue_estimated": item.get("revenueEstimated"),
                "revenue_actual": item.get("revenue"),
                "fiscal_quarter": item.get("fiscalDateEnding"),
            })

        # 按日期排序
        results.sort(key=lambda x: x.get("date", ""))

        return results

    def get_upcoming_earnings_for_universe(
        self,
        universe_tickers: list[str],
        days_ahead: int = 7,
    ) -> list[dict]:
        """取得觀察清單中即將發布財報的公司

        Args:
            universe_tickers: 觀察清單 tickers
            days_ahead: 往後看幾天

        Returns:
            即將發布財報的公司列表
        """
        from datetime import datetime, timedelta

        from_date = datetime.now().strftime("%Y-%m-%d")
        to_date = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

        all_earnings = self.get_earnings_calendar(from_date, to_date)

        # 只保留 universe 中的
        universe_set = set(universe_tickers)
        return [e for e in all_earnings if e.get("ticker") in universe_set]

    def get_recent_earnings(self, ticker: str, limit: int = 4) -> list[dict]:
        """取得最近的財報數據（歷史實際數據）+ YoY 計算

        使用 income-statement 取得實際財務數據，而非 earnings calendar。
        這樣可以取得歷史已發布的財報，而不是未來預期。

        P0-2 改進：自動計算 YoY（同比）增長率
        - 取得 8 季數據以便計算 YoY
        - 每個季度與去年同期比較
        - 避免 LLM 自行推算導致錯誤

        Args:
            ticker: 股票代碼
            limit: 取幾筆（預設 4 = 最近 4 季）

        Returns:
            財報數據列表，包含 EPS、revenue、YoY 增長率等
        """
        # 取得 8 季數據以便計算 YoY（去年同期）
        fetch_limit = max(limit + 4, 8)
        cache_key = f"fmp:income_stmt:{ticker}:{fetch_limit}"
        income_data = self._cached_request(
            cache_key,
            "income-statement",
            {"symbol": ticker, "limit": fetch_limit, "period": "quarter"}
        )

        if not income_data or not isinstance(income_data, list):
            return []

        # 建立季度索引用於 YoY 查找
        # Key: (fiscal_period, fiscal_year) -> revenue, eps, etc.
        quarter_data = {}
        for item in income_data:
            period = item.get("period")  # Q1, Q2, Q3, Q4
            year = item.get("calendarYear")
            if period and year:
                quarter_data[(period, year)] = item

        results = []
        for item in income_data[:limit]:  # 只返回最近 limit 筆
            # 計算 EPS (使用 weighted average shares)
            net_income = item.get("netIncome")
            shares = item.get("weightedAverageShsOut") or item.get("weightedAverageShsOutDil")
            eps = None
            if net_income is not None and shares and shares > 0:
                eps = net_income / shares

            revenue = item.get("revenue")
            gross_profit = item.get("grossProfit")
            operating_income = item.get("operatingIncome")

            # ========== P0-2: 計算 YoY 增長率 ==========
            period = item.get("period")
            year = item.get("calendarYear")
            revenue_yoy = None
            eps_yoy = None
            net_income_yoy = None
            gross_profit_yoy = None

            if period and year:
                try:
                    prev_year = str(int(year) - 1)
                    prev_quarter = quarter_data.get((period, prev_year))
                    if prev_quarter:
                        # Revenue YoY
                        prev_revenue = prev_quarter.get("revenue")
                        if revenue and prev_revenue and prev_revenue > 0:
                            revenue_yoy = round(((revenue - prev_revenue) / prev_revenue) * 100, 1)

                        # EPS YoY (使用計算出的 EPS)
                        prev_net = prev_quarter.get("netIncome")
                        prev_shares = prev_quarter.get("weightedAverageShsOut") or prev_quarter.get("weightedAverageShsOutDil")
                        if prev_net and prev_shares and prev_shares > 0:
                            prev_eps = prev_net / prev_shares
                            if eps and prev_eps and prev_eps > 0:
                                eps_yoy = round(((eps - prev_eps) / abs(prev_eps)) * 100, 1)

                        # Net Income YoY
                        if net_income and prev_net and prev_net > 0:
                            net_income_yoy = round(((net_income - prev_net) / prev_net) * 100, 1)

                        # Gross Profit YoY
                        prev_gp = prev_quarter.get("grossProfit")
                        if gross_profit and prev_gp and prev_gp > 0:
                            gross_profit_yoy = round(((gross_profit - prev_gp) / prev_gp) * 100, 1)
                except (ValueError, TypeError):
                    pass  # 年份轉換失敗，跳過 YoY 計算

            results.append({
                "ticker": ticker,
                # IMPORTANT: Date field semantics (P0-4)
                # - date: 財報結算日 (fiscal period end), e.g., "2024-09-30" for Q3 2024
                # - announcement_date: 財報發布日 (filing date), e.g., "2024-10-30"
                "date": item.get("date"),  # 財報結算日 (fiscal_period_end)
                "announcement_date": item.get("fillingDate"),  # 財報發布日 (when SEC filing was submitted)
                "fiscal_period": period,  # e.g., "Q3"
                "fiscal_year": year,
                "eps_actual": round(eps, 3) if eps else None,
                "eps_diluted": item.get("epsdiluted"),
                "revenue_actual": revenue,
                "gross_profit": gross_profit,
                "operating_income": operating_income,
                "net_income": net_income,
                "gross_margin": self._calc_margin(gross_profit, revenue),
                "operating_margin": self._calc_margin(operating_income, revenue),
                "net_margin": self._calc_margin(net_income, revenue),
                # P0-2: YoY 增長率（已預先計算，避免 LLM 推算錯誤）
                "revenue_yoy_percent": revenue_yoy,
                "eps_yoy_percent": eps_yoy,
                "net_income_yoy_percent": net_income_yoy,
                "gross_profit_yoy_percent": gross_profit_yoy,
            })

        return results

    def _calc_margin(self, numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
        """計算 margin percentage"""
        if numerator is None or denominator is None or denominator == 0:
            return None
        return round((numerator / denominator) * 100, 2)

    def _calc_surprise(self, actual: Optional[float], estimated: Optional[float]) -> Optional[float]:
        """計算 surprise percentage"""
        if actual is None or estimated is None or estimated == 0:
            return None
        return ((actual - estimated) / abs(estimated)) * 100

    def get_analyst_estimates(self, ticker: str) -> Optional[Estimates]:
        """取得分析師預估

        使用 price-target-consensus 和 price-target-summary 端點。

        Args:
            ticker: 股票代碼

        Returns:
            Estimates 或 None
        """
        # 取得 price target consensus
        cache_key = f"fmp:price_target_consensus:{ticker}"
        consensus = self._cached_request(cache_key, "price-target-consensus", {"symbol": ticker})

        if not consensus or not isinstance(consensus, list) or len(consensus) == 0:
            return None

        pt = consensus[0]

        # 取得 price target summary for more details
        cache_key_summary = f"fmp:price_target_summary:{ticker}"
        summary = self._cached_request(cache_key_summary, "price-target-summary", {"symbol": ticker})
        pts = summary[0] if summary and isinstance(summary, list) and len(summary) > 0 else {}

        return Estimates(
            revenue_ntm=None,  # price target endpoints don't have revenue estimates
            eps_ntm=None,      # price target endpoints don't have EPS estimates
            ebitda_ntm=None,   # price target endpoints don't have EBITDA estimates
            price_target_high=pt.get("targetHigh"),
            price_target_low=pt.get("targetLow"),
            price_target_consensus=pt.get("targetConsensus"),
            price_target_median=pt.get("targetMedian"),
            analyst_count_last_quarter=pts.get("lastQuarterCount"),
        )

    def enrich(self, ticker: str) -> CompanyData:
        """完整補充單一 ticker 資料

        Args:
            ticker: 股票代碼

        Returns:
            CompanyData 實例
        """
        company = CompanyData(ticker=ticker)

        try:
            # 取得公司資料
            profile = self.get_company_profile(ticker)
            if profile:
                company.name = profile.get("name")
                company.sector = profile.get("sector")
                company.industry = profile.get("industry")
                company.peers = profile.get("peers", [])

            # 取得報價
            company.price = self.get_quote(ticker)

            # 取得財務
            company.fundamentals = self.get_fundamentals(ticker)

            # 取得預估
            company.estimates = self.get_analyst_estimates(ticker)

        except Exception as e:
            logger.error(f"Error enriching {ticker}: {e}")
            company.error = str(e)

        return company

    def enrich_multiple(self, tickers: list[str]) -> dict[str, CompanyData]:
        """補充多個 tickers 資料

        Args:
            tickers: 股票代碼列表

        Returns:
            {ticker: CompanyData} 字典
        """
        results = {}
        for ticker in tickers:
            logger.info(f"Enriching: {ticker}")
            results[ticker] = self.enrich(ticker)
        return results

    def close(self) -> None:
        """關閉 HTTP client"""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def main():
    """CLI demo"""
    import argparse
    import json

    from rich.console import Console
    from rich.table import Table

    parser = argparse.ArgumentParser(description="FMP Enricher")
    parser.add_argument("tickers", nargs="+", help="Stock tickers")
    parser.add_argument("--output", "-o", help="Output file path")
    args = parser.parse_args()

    console = Console()

    with FMPEnricher() as enricher:
        results = enricher.enrich_multiple(args.tickers)

    # 顯示結果
    table = Table(title="Company Data")
    table.add_column("Ticker", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Price", style="yellow")
    table.add_column("Chg%", style="magenta")
    table.add_column("Market Cap", style="blue")
    table.add_column("Sector")

    for ticker, data in results.items():
        if data.error:
            table.add_row(ticker, f"Error: {data.error}", "", "", "", "")
            continue

        price = f"${data.price.last:.2f}" if data.price and data.price.last else "N/A"
        chg = f"{data.price.change_pct_1d:.2f}%" if data.price and data.price.change_pct_1d else "N/A"
        mcap = f"${data.price.market_cap / 1e9:.1f}B" if data.price and data.price.market_cap else "N/A"

        table.add_row(
            ticker,
            data.name or "N/A",
            price,
            chg,
            mcap,
            data.sector or "N/A",
        )

    console.print(table)

    # 輸出到檔案
    if args.output:
        output_data = {t: d.to_dict() for t, d in results.items()}
        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        console.print(f"\n[green]Saved to {args.output}[/green]")


if __name__ == "__main__":
    main()

"""Alpha Vantage Enricher

https://www.alphavantage.co/
"""

import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

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


class AlphaVantageEnricher(BaseEnricher):
    """Alpha Vantage 資料補完器"""

    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache: Optional[FileCache] = None,
        cache_ttl: int = 3600,
        timeout: float = 30.0,
        max_retries: int = 3,
        rate_limit_rpm: int = 5,  # 免費版限制較嚴
    ):
        """初始化 Alpha Vantage Enricher

        Args:
            api_key: Alpha Vantage API Key
            cache: 快取實例
            cache_ttl: 快取 TTL (秒)
            timeout: 請求超時 (秒)
            max_retries: 最大重試次數
            rate_limit_rpm: 每分鐘請求限制
        """
        self.api_key = api_key or os.getenv("ALPHAVANTAGE_API_KEY")
        if not self.api_key:
            logger.warning("ALPHAVANTAGE_API_KEY not set")

        self.cache = cache or FileCache(cache_dir="data/cache/av", default_ttl=cache_ttl)
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
        return "alpha_vantage"

    def _request(self, function: str, **kwargs) -> Optional[dict]:
        """發送 API 請求

        Args:
            function: API function
            **kwargs: 額外參數

        Returns:
            JSON 回應或 None
        """
        if not self.api_key:
            logger.error("Alpha Vantage API key not configured")
            return None

        params = {
            "function": function,
            "apikey": self.api_key,
            **kwargs,
        }

        # 速率限制
        self.rate_limiter.wait()

        for attempt in range(self.max_retries):
            try:
                response = self._client.get(self.BASE_URL, params=params)
                response.raise_for_status()
                data = response.json()

                # 檢查 API 錯誤
                if "Error Message" in data:
                    logger.error(f"API error: {data['Error Message']}")
                    return None

                if "Note" in data:
                    # Rate limit warning
                    logger.warning(f"API note: {data['Note']}")
                    time.sleep(60)  # Wait a minute
                    continue

                return data

            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error: {e}")
                if attempt == self.max_retries - 1:
                    return None

            except httpx.RequestError as e:
                logger.error(f"Request error: {e}")
                if attempt == self.max_retries - 1:
                    return None
                time.sleep(2 ** attempt)

        return None

    def _cached_request(self, cache_key: str, function: str, **kwargs) -> Optional[dict]:
        """帶快取的 API 請求"""
        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Cache hit: {cache_key}")
            return cached

        result = self._request(function, **kwargs)
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
        cache_key = f"av:quote:{ticker}"
        data = self._cached_request(cache_key, "GLOBAL_QUOTE", symbol=ticker)

        if not data or "Global Quote" not in data:
            return None

        quote = data["Global Quote"]

        try:
            price = float(quote.get("05. price", 0))
            change_pct = quote.get("10. change percent", "0%")
            change_pct = float(change_pct.replace("%", "")) if change_pct else 0
            volume = int(quote.get("06. volume", 0))

            return PriceData(
                last=price,
                change_pct_1d=change_pct,
                volume=volume,
                market_cap=None,  # Alpha Vantage doesn't provide market cap in quote
                as_of=datetime.now(timezone.utc).isoformat(),
            )
        except (ValueError, TypeError) as e:
            logger.error(f"Error parsing quote: {e}")
            return None

    def get_fundamentals(self, ticker: str) -> Optional[Fundamentals]:
        """取得基礎財務

        Args:
            ticker: 股票代碼

        Returns:
            Fundamentals 或 None
        """
        cache_key = f"av:overview:{ticker}"
        data = self._cached_request(cache_key, "OVERVIEW", symbol=ticker)

        if not data or "Symbol" not in data:
            return None

        def safe_float(value) -> Optional[float]:
            try:
                if value and value != "None" and value != "-":
                    return float(value)
            except (ValueError, TypeError):
                pass
            return None

        return Fundamentals(
            revenue_ttm=safe_float(data.get("RevenueTTM")),
            ebitda_ttm=safe_float(data.get("EBITDA")),
            net_income_ttm=None,  # Not directly available
            fcf_ttm=None,  # Not directly available
            gross_margin=safe_float(data.get("GrossProfitTTM")) / safe_float(data.get("RevenueTTM"))
                if safe_float(data.get("GrossProfitTTM")) and safe_float(data.get("RevenueTTM"))
                else None,
            operating_margin=safe_float(data.get("OperatingMarginTTM")),
            net_margin=safe_float(data.get("ProfitMargin")),
            debt_to_equity=None,  # Not directly available in overview
            current_ratio=None,
        )

    def get_company_profile(self, ticker: str) -> Optional[dict]:
        """取得公司基本資料

        Args:
            ticker: 股票代碼

        Returns:
            公司資料字典或 None
        """
        cache_key = f"av:overview:{ticker}"
        data = self._cached_request(cache_key, "OVERVIEW", symbol=ticker)

        if not data or "Symbol" not in data:
            return None

        return {
            "name": data.get("Name"),
            "sector": data.get("Sector"),
            "industry": data.get("Industry"),
            "description": data.get("Description"),
            "country": data.get("Country"),
            "exchange": data.get("Exchange"),
            "peers": [],  # Alpha Vantage doesn't provide peers
        }

    def get_earnings(self, ticker: str) -> Optional[dict]:
        """取得盈餘資料

        Args:
            ticker: 股票代碼

        Returns:
            盈餘資料或 None
        """
        cache_key = f"av:earnings:{ticker}"
        data = self._cached_request(cache_key, "EARNINGS", symbol=ticker)

        if not data:
            return None

        return data

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

        except Exception as e:
            logger.error(f"Error enriching {ticker}: {e}")
            company.error = str(e)

        return company

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

    parser = argparse.ArgumentParser(description="Alpha Vantage Enricher")
    parser.add_argument("tickers", nargs="+", help="Stock tickers")
    parser.add_argument("--output", "-o", help="Output file path")
    args = parser.parse_args()

    console = Console()

    with AlphaVantageEnricher() as enricher:
        results = {}
        for ticker in args.tickers:
            console.print(f"Enriching: {ticker}")
            results[ticker] = enricher.enrich(ticker)

    # 顯示結果
    table = Table(title="Company Data (Alpha Vantage)")
    table.add_column("Ticker", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Price", style="yellow")
    table.add_column("Chg%", style="magenta")
    table.add_column("Sector")

    for ticker, data in results.items():
        if data.error:
            table.add_row(ticker, f"Error: {data.error}", "", "", "")
            continue

        price = f"${data.price.last:.2f}" if data.price and data.price.last else "N/A"
        chg = f"{data.price.change_pct_1d:.2f}%" if data.price and data.price.change_pct_1d else "N/A"

        table.add_row(
            ticker,
            data.name or "N/A",
            price,
            chg,
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

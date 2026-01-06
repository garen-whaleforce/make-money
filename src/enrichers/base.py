"""Base enricher interface"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class PriceData:
    """股價資料"""

    last: Optional[float] = None
    change_pct_1d: Optional[float] = None
    volume: Optional[int] = None
    market_cap: Optional[float] = None
    as_of: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "last": self.last,
            "change_pct_1d": self.change_pct_1d,
            "volume": self.volume,
            "market_cap": self.market_cap,
            "as_of": self.as_of,
        }


@dataclass
class Fundamentals:
    """基礎財務資料"""

    revenue_ttm: Optional[float] = None
    ebitda_ttm: Optional[float] = None
    net_income_ttm: Optional[float] = None
    fcf_ttm: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "revenue_ttm": self.revenue_ttm,
            "ebitda_ttm": self.ebitda_ttm,
            "net_income_ttm": self.net_income_ttm,
            "fcf_ttm": self.fcf_ttm,
            "gross_margin": self.gross_margin,
            "operating_margin": self.operating_margin,
            "net_margin": self.net_margin,
            "debt_to_equity": self.debt_to_equity,
            "current_ratio": self.current_ratio,
        }


@dataclass
class Estimates:
    """預估資料"""

    revenue_ntm: Optional[float] = None
    eps_ntm: Optional[float] = None
    ebitda_ntm: Optional[float] = None
    revenue_growth_ntm: Optional[float] = None
    # Price target fields (from FMP stable API)
    price_target_high: Optional[float] = None
    price_target_low: Optional[float] = None
    price_target_consensus: Optional[float] = None
    price_target_median: Optional[float] = None
    analyst_count_last_quarter: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "revenue_ntm": self.revenue_ntm,
            "eps_ntm": self.eps_ntm,
            "ebitda_ntm": self.ebitda_ntm,
            "revenue_growth_ntm": self.revenue_growth_ntm,
            "price_target_high": self.price_target_high,
            "price_target_low": self.price_target_low,
            "price_target_consensus": self.price_target_consensus,
            "price_target_median": self.price_target_median,
            "analyst_count_last_quarter": self.analyst_count_last_quarter,
        }


@dataclass
class CompanyData:
    """公司資料"""

    ticker: str
    name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    price: Optional[PriceData] = None
    fundamentals: Optional[Fundamentals] = None
    estimates: Optional[Estimates] = None
    peers: list[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "sector": self.sector,
            "industry": self.industry,
            "price": self.price.to_dict() if self.price else None,
            "fundamentals": self.fundamentals.to_dict() if self.fundamentals else None,
            "estimates": self.estimates.to_dict() if self.estimates else None,
            "peers": self.peers,
            "error": self.error,
        }


@dataclass
class EnricherError:
    """Enricher 錯誤資訊"""

    ticker: str
    provider: str
    error_type: str
    message: str

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "provider": self.provider,
            "error_type": self.error_type,
            "message": self.message,
        }


class BaseEnricher(ABC):
    """Enricher 基礎類別"""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider 名稱"""
        pass

    @abstractmethod
    def get_quote(self, ticker: str) -> Optional[PriceData]:
        """取得即時報價"""
        pass

    @abstractmethod
    def get_fundamentals(self, ticker: str) -> Optional[Fundamentals]:
        """取得基礎財務"""
        pass

    @abstractmethod
    def get_company_profile(self, ticker: str) -> Optional[dict]:
        """取得公司基本資料"""
        pass

    def enrich(self, ticker: str) -> CompanyData:
        """完整補充單一 ticker 資料"""
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
            company.error = str(e)

        return company

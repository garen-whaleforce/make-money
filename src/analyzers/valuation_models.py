"""Valuation Models

估值分析模組，計算合理價格區間。
"""

from dataclasses import dataclass, field
from typing import Optional

from ..enrichers.base import CompanyData
from ..utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ValuationResult:
    """估值結果"""

    ticker: str
    method: str
    current_price: Optional[float] = None
    fair_value_bear: Optional[float] = None
    fair_value_base: Optional[float] = None
    fair_value_bull: Optional[float] = None
    upside_bear: Optional[float] = None
    upside_base: Optional[float] = None
    upside_bull: Optional[float] = None
    assumptions: list[str] = field(default_factory=list)
    rationale: str = ""
    data_quality: str = "insufficient"  # complete, partial, insufficient

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "method": self.method,
            "current_price": self.current_price,
            "fair_value": {
                "bear": self.fair_value_bear,
                "base": self.fair_value_base,
                "bull": self.fair_value_bull,
            },
            "upside": {
                "bear": self.upside_bear,
                "base": self.upside_base,
                "bull": self.upside_bull,
            },
            "assumptions": self.assumptions,
            "rationale": self.rationale,
            "data_quality": self.data_quality,
        }


class ValuationAnalyzer:
    """估值分析器"""

    def __init__(
        self,
        bear_percentile: float = 0.25,
        base_percentile: float = 0.50,
        bull_percentile: float = 0.75,
    ):
        """初始化估值分析器

        Args:
            bear_percentile: 熊市情境百分位
            base_percentile: 基準情境百分位
            bull_percentile: 牛市情境百分位
        """
        self.bear_percentile = bear_percentile
        self.base_percentile = base_percentile
        self.bull_percentile = bull_percentile

    def _calculate_upside(
        self,
        current_price: Optional[float],
        fair_value: Optional[float],
    ) -> Optional[float]:
        """計算漲跌幅

        Args:
            current_price: 當前價格
            fair_value: 合理價值

        Returns:
            漲跌幅 (%)
        """
        if current_price and fair_value and current_price > 0:
            return ((fair_value / current_price) - 1) * 100
        return None

    def peer_multiple_valuation(
        self,
        target: CompanyData,
        peers: list[CompanyData],
        multiple_type: str = "ev_ebitda",
    ) -> ValuationResult:
        """同業倍數估值法

        Args:
            target: 目標公司
            peers: 同業公司列表
            multiple_type: 倍數類型 (ev_ebitda, pe, ps)

        Returns:
            ValuationResult 實例
        """
        result = ValuationResult(
            ticker=target.ticker,
            method=f"peer_multiple_{multiple_type}",
        )

        # 取得當前價格
        if target.price:
            result.current_price = target.price.last

        # 收集同業倍數
        peer_multiples = []
        assumptions = []

        for peer in peers:
            if not peer.price or not peer.fundamentals:
                continue

            market_cap = peer.price.market_cap
            if not market_cap or market_cap <= 0:
                continue

            multiple = None
            if multiple_type == "ev_ebitda" and peer.fundamentals.ebitda_ttm:
                if peer.fundamentals.ebitda_ttm > 0:
                    # 簡化：假設 EV ≈ Market Cap (忽略淨債務)
                    multiple = market_cap / peer.fundamentals.ebitda_ttm
            elif multiple_type == "pe" and peer.fundamentals.net_income_ttm:
                if peer.fundamentals.net_income_ttm > 0:
                    multiple = market_cap / peer.fundamentals.net_income_ttm
            elif multiple_type == "ps" and peer.fundamentals.revenue_ttm:
                if peer.fundamentals.revenue_ttm > 0:
                    multiple = market_cap / peer.fundamentals.revenue_ttm

            if multiple and multiple > 0 and multiple < 200:  # 合理範圍
                peer_multiples.append((peer.ticker, multiple))

        if not peer_multiples:
            result.rationale = "資料不足：無法取得足夠的同業倍數"
            result.data_quality = "insufficient"
            return result

        # 排序並計算各情境倍數
        sorted_multiples = sorted([m[1] for m in peer_multiples])
        n = len(sorted_multiples)

        bear_idx = max(0, int(n * self.bear_percentile) - 1)
        base_idx = max(0, int(n * self.base_percentile) - 1)
        bull_idx = min(n - 1, int(n * self.bull_percentile))

        bear_multiple = sorted_multiples[bear_idx]
        base_multiple = sorted_multiples[base_idx]
        bull_multiple = sorted_multiples[bull_idx]

        assumptions.append(f"使用 {multiple_type.upper()} 倍數")
        assumptions.append(f"同業樣本：{', '.join([p[0] for p in peer_multiples])}")
        assumptions.append(f"熊市倍數：{bear_multiple:.1f}x (P{int(self.bear_percentile*100)})")
        assumptions.append(f"基準倍數：{base_multiple:.1f}x (P{int(self.base_percentile*100)})")
        assumptions.append(f"牛市倍數：{bull_multiple:.1f}x (P{int(self.bull_percentile*100)})")

        # 計算目標公司的合理價值
        if not target.fundamentals:
            result.assumptions = assumptions
            result.rationale = "資料不足：目標公司缺少財務數據"
            result.data_quality = "partial"
            return result

        target_metric = None
        if multiple_type == "ev_ebitda":
            target_metric = target.fundamentals.ebitda_ttm
        elif multiple_type == "pe":
            target_metric = target.fundamentals.net_income_ttm
        elif multiple_type == "ps":
            target_metric = target.fundamentals.revenue_ttm

        if not target_metric or target_metric <= 0:
            result.assumptions = assumptions
            result.rationale = f"資料不足：目標公司缺少 {multiple_type.upper()} 所需數據"
            result.data_quality = "partial"
            return result

        # 計算隱含市值
        if target.price and target.price.market_cap:
            shares = target.price.market_cap / target.price.last if target.price.last else None

            if shares:
                bear_market_cap = target_metric * bear_multiple
                base_market_cap = target_metric * base_multiple
                bull_market_cap = target_metric * bull_multiple

                result.fair_value_bear = bear_market_cap / shares
                result.fair_value_base = base_market_cap / shares
                result.fair_value_bull = bull_market_cap / shares

                result.upside_bear = self._calculate_upside(result.current_price, result.fair_value_bear)
                result.upside_base = self._calculate_upside(result.current_price, result.fair_value_base)
                result.upside_bull = self._calculate_upside(result.current_price, result.fair_value_bull)

                assumptions.append(f"目標公司 {multiple_type.upper()} 基準：${target_metric/1e9:.1f}B")

        result.assumptions = assumptions
        result.data_quality = "complete" if result.fair_value_base else "partial"
        result.rationale = self._generate_rationale(result)

        return result

    def _generate_rationale(self, result: ValuationResult) -> str:
        """生成估值說明

        Args:
            result: 估值結果

        Returns:
            說明文字
        """
        if not result.fair_value_base:
            return "資料不足以進行完整估值分析"

        parts = [f"基於同業倍數法，{result.ticker} 的合理價值區間為："]

        if result.fair_value_bear:
            parts.append(f"熊市 ${result.fair_value_bear:.2f}")
        if result.fair_value_base:
            parts.append(f"基準 ${result.fair_value_base:.2f}")
        if result.fair_value_bull:
            parts.append(f"牛市 ${result.fair_value_bull:.2f}")

        if result.current_price and result.upside_base:
            direction = "上漲" if result.upside_base > 0 else "下跌"
            parts.append(f"相對當前價格 ${result.current_price:.2f}，基準情境有 {abs(result.upside_base):.1f}% 的{direction}空間。")

        return " / ".join(parts[:3]) + ". " + (parts[3] if len(parts) > 3 else "")

    def analyze(
        self,
        target_ticker: str,
        companies: dict[str, CompanyData],
    ) -> ValuationResult:
        """對目標公司進行估值分析

        Args:
            target_ticker: 目標公司 ticker
            companies: 公司資料字典

        Returns:
            ValuationResult 實例
        """
        target = companies.get(target_ticker)
        if not target:
            return ValuationResult(
                ticker=target_ticker,
                method="peer_multiple",
                rationale="資料不足：找不到目標公司資料",
                data_quality="insufficient",
            )

        # 找同業
        peers = []
        if target.peers:
            for peer_ticker in target.peers[:8]:
                if peer_ticker in companies:
                    peers.append(companies[peer_ticker])

        # 如果同業不足，嘗試使用其他已有資料
        if len(peers) < 3:
            for ticker, company in companies.items():
                if ticker != target_ticker and company not in peers:
                    if company.sector == target.sector:
                        peers.append(company)
                        if len(peers) >= 5:
                            break

        # 嘗試不同倍數
        for multiple_type in ["ev_ebitda", "ps", "pe"]:
            result = self.peer_multiple_valuation(target, peers, multiple_type)
            if result.data_quality == "complete":
                return result

        # 返回最後嘗試的結果
        return result

    def analyze_multiple(
        self,
        tickers: list[str],
        companies: dict[str, CompanyData],
    ) -> dict[str, ValuationResult]:
        """對多個公司進行估值分析

        Args:
            tickers: 目標公司列表
            companies: 公司資料字典

        Returns:
            {ticker: ValuationResult} 字典
        """
        results = {}
        for ticker in tickers:
            logger.info(f"Analyzing valuation for {ticker}")
            results[ticker] = self.analyze(ticker, companies)
        return results


def main():
    """CLI demo"""
    from rich.console import Console
    from rich.table import Table

    from ..enrichers.fmp import FMPEnricher

    console = Console()

    # 取得資料
    console.print("[bold]Fetching company data...[/bold]")
    tickers = ["NVDA", "AMD", "INTC", "TSM", "AVGO"]

    with FMPEnricher() as enricher:
        companies = enricher.enrich_multiple(tickers)

    # 估值分析
    console.print("[bold]Running valuation analysis...[/bold]")
    analyzer = ValuationAnalyzer()
    results = analyzer.analyze_multiple(["NVDA", "AMD"], companies)

    # 顯示結果
    for ticker, result in results.items():
        console.print(f"\n[bold cyan]{ticker} Valuation[/bold cyan]")
        console.print(f"Method: {result.method}")
        console.print(f"Current Price: ${result.current_price:.2f}" if result.current_price else "Current Price: N/A")
        console.print(f"Data Quality: {result.data_quality}")

        if result.fair_value_base:
            table = Table(title="Fair Value Range")
            table.add_column("Scenario")
            table.add_column("Fair Value")
            table.add_column("Upside")

            if result.fair_value_bear:
                upside = f"{result.upside_bear:+.1f}%" if result.upside_bear else "N/A"
                table.add_row("Bear", f"${result.fair_value_bear:.2f}", upside)
            if result.fair_value_base:
                upside = f"{result.upside_base:+.1f}%" if result.upside_base else "N/A"
                table.add_row("Base", f"${result.fair_value_base:.2f}", upside)
            if result.fair_value_bull:
                upside = f"{result.upside_bull:+.1f}%" if result.upside_bull else "N/A"
                table.add_row("Bull", f"${result.fair_value_bull:.2f}", upside)

            console.print(table)

        console.print(f"\n[dim]{result.rationale}[/dim]")


if __name__ == "__main__":
    main()

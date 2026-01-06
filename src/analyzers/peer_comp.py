"""Peer Comparison Module

同業比較表建構模組。
"""

from dataclasses import dataclass, field
from typing import Optional

from ..enrichers.base import CompanyData
from ..utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PeerTableRow:
    """同業比較表行"""

    ticker: str
    name: Optional[str] = None
    market_cap: Optional[float] = None
    revenue_ttm: Optional[float] = None
    revenue_growth: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    forward_pe: Optional[float] = None
    forward_ps: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "market_cap": self.market_cap,
            "revenue_ttm": self.revenue_ttm,
            "revenue_growth": self.revenue_growth,
            "gross_margin": self.gross_margin,
            "operating_margin": self.operating_margin,
            "net_margin": self.net_margin,
            "forward_pe": self.forward_pe,
            "forward_ps": self.forward_ps,
        }


@dataclass
class PeerTable:
    """同業比較表"""

    headers: list[str]
    rows: list[PeerTableRow]
    markdown: str = ""
    takeaways: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "headers": self.headers,
            "rows": [r.to_dict() for r in self.rows],
            "markdown": self.markdown,
            "takeaways": self.takeaways,
        }


class PeerComparisonBuilder:
    """同業比較表建構器"""

    DEFAULT_HEADERS = [
        "Ticker",
        "Company",
        "Market Cap",
        "Revenue TTM",
        "Rev Growth",
        "Gross Margin",
        "Op Margin",
        "Forward P/E",
    ]

    def __init__(self, max_peers: int = 8):
        """初始化同業比較表建構器

        Args:
            max_peers: 最大同業數量
        """
        self.max_peers = max_peers

    def _format_number(
        self,
        value: Optional[float],
        format_type: str = "number",
    ) -> str:
        """格式化數字

        Args:
            value: 數值
            format_type: 格式類型 (number, percent, currency, billions)

        Returns:
            格式化字串
        """
        if value is None:
            return "-"

        if format_type == "percent":
            return f"{value * 100:.1f}%"
        elif format_type == "currency":
            return f"${value:.2f}"
        elif format_type == "billions":
            if value >= 1e12:
                return f"${value / 1e12:.1f}T"
            elif value >= 1e9:
                return f"${value / 1e9:.1f}B"
            elif value >= 1e6:
                return f"${value / 1e6:.1f}M"
            else:
                return f"${value:,.0f}"
        elif format_type == "multiple":
            return f"{value:.1f}x"
        else:
            return f"{value:.2f}"

    def build_row(self, company: CompanyData) -> PeerTableRow:
        """建構單行資料

        Args:
            company: 公司資料

        Returns:
            PeerTableRow 實例
        """
        row = PeerTableRow(ticker=company.ticker, name=company.name)

        if company.price:
            row.market_cap = company.price.market_cap

        if company.fundamentals:
            row.revenue_ttm = company.fundamentals.revenue_ttm
            row.gross_margin = company.fundamentals.gross_margin
            row.operating_margin = company.fundamentals.operating_margin
            row.net_margin = company.fundamentals.net_margin

        if company.estimates:
            # 計算 forward multiples
            if company.price and company.price.market_cap:
                if company.estimates.eps_ntm and company.estimates.eps_ntm > 0:
                    # 假設股數 = market_cap / price
                    if company.price.last:
                        shares = company.price.market_cap / company.price.last
                        earnings_ntm = company.estimates.eps_ntm * shares
                        row.forward_pe = company.price.market_cap / earnings_ntm

                if company.estimates.revenue_ntm and company.estimates.revenue_ntm > 0:
                    row.forward_ps = company.price.market_cap / company.estimates.revenue_ntm

            # 計算 revenue growth
            if company.estimates.revenue_ntm and row.revenue_ttm and row.revenue_ttm > 0:
                row.revenue_growth = (company.estimates.revenue_ntm / row.revenue_ttm) - 1

        return row

    def build_markdown_table(self, rows: list[PeerTableRow]) -> str:
        """建構 Markdown 表格

        Args:
            rows: 表格行列表

        Returns:
            Markdown 表格字串
        """
        lines = []

        # Header
        headers = [
            "Ticker", "Company", "Market Cap", "Revenue TTM",
            "Rev Growth", "Gross Margin", "Op Margin", "Fwd P/E"
        ]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")

        # Rows
        for row in rows:
            values = [
                row.ticker,
                (row.name or "-")[:20],  # 截斷公司名稱
                self._format_number(row.market_cap, "billions"),
                self._format_number(row.revenue_ttm, "billions"),
                self._format_number(row.revenue_growth, "percent") if row.revenue_growth else "-",
                self._format_number(row.gross_margin, "percent") if row.gross_margin else "-",
                self._format_number(row.operating_margin, "percent") if row.operating_margin else "-",
                self._format_number(row.forward_pe, "multiple") if row.forward_pe else "-",
            ]
            lines.append("| " + " | ".join(values) + " |")

        return "\n".join(lines)

    def generate_takeaways(self, rows: list[PeerTableRow], target_ticker: str) -> list[str]:
        """生成同業比較重點

        Args:
            rows: 表格行
            target_ticker: 目標公司

        Returns:
            重點列表
        """
        takeaways = []

        if not rows:
            return takeaways

        # 找目標公司
        target_row = next((r for r in rows if r.ticker == target_ticker), None)

        # 市值排名
        sorted_by_mcap = sorted(
            [r for r in rows if r.market_cap],
            key=lambda r: r.market_cap or 0,
            reverse=True,
        )
        if sorted_by_mcap and target_row and target_row.market_cap:
            rank = next(
                (i + 1 for i, r in enumerate(sorted_by_mcap) if r.ticker == target_ticker),
                None,
            )
            if rank:
                takeaways.append(
                    f"{target_ticker} 市值 {self._format_number(target_row.market_cap, 'billions')}，"
                    f"在同業中排名第 {rank}/{len(sorted_by_mcap)}"
                )

        # 毛利率比較
        margins = [(r.ticker, r.gross_margin) for r in rows if r.gross_margin]
        if margins:
            avg_margin = sum(m[1] for m in margins) / len(margins)
            if target_row and target_row.gross_margin:
                diff = target_row.gross_margin - avg_margin
                if abs(diff) > 0.05:
                    direction = "高於" if diff > 0 else "低於"
                    takeaways.append(
                        f"{target_ticker} 毛利率 {self._format_number(target_row.gross_margin, 'percent')}，"
                        f"{direction}同業平均 {self._format_number(avg_margin, 'percent')}"
                    )

        # 估值比較
        pes = [(r.ticker, r.forward_pe) for r in rows if r.forward_pe and r.forward_pe > 0]
        if pes:
            avg_pe = sum(p[1] for p in pes) / len(pes)
            if target_row and target_row.forward_pe:
                premium = (target_row.forward_pe / avg_pe - 1) * 100
                if abs(premium) > 10:
                    direction = "溢價" if premium > 0 else "折價"
                    takeaways.append(
                        f"{target_ticker} Forward P/E {self._format_number(target_row.forward_pe, 'multiple')}，"
                        f"相對同業平均 {self._format_number(avg_pe, 'multiple')} {direction} {abs(premium):.0f}%"
                    )

        return takeaways[:3]  # 最多 3 個 takeaways

    def build(
        self,
        target_ticker: str,
        companies: dict[str, CompanyData],
    ) -> PeerTable:
        """建構同業比較表

        Args:
            target_ticker: 目標公司 ticker
            companies: 公司資料字典

        Returns:
            PeerTable 實例
        """
        target = companies.get(target_ticker)
        if not target:
            logger.warning(f"Target company {target_ticker} not found")
            return PeerTable(headers=self.DEFAULT_HEADERS, rows=[])

        # 建構行列表 (目標公司在前)
        rows = [self.build_row(target)]

        # 加入同業
        peer_tickers = target.peers[:self.max_peers - 1] if target.peers else []
        for peer_ticker in peer_tickers:
            if peer_ticker in companies:
                rows.append(self.build_row(companies[peer_ticker]))

        # 如果同業不足，從其他公司補充
        if len(rows) < 3:
            for ticker, company in companies.items():
                if ticker != target_ticker and ticker not in peer_tickers:
                    if company.sector == target.sector:
                        rows.append(self.build_row(company))
                        if len(rows) >= self.max_peers:
                            break

        # 建構表格
        markdown = self.build_markdown_table(rows)
        takeaways = self.generate_takeaways(rows, target_ticker)

        return PeerTable(
            headers=self.DEFAULT_HEADERS,
            rows=rows,
            markdown=markdown,
            takeaways=takeaways,
        )


def main():
    """CLI demo"""
    from rich.console import Console
    from rich.markdown import Markdown

    from ..enrichers.fmp import FMPEnricher

    console = Console()

    # 取得資料
    console.print("[bold]Fetching company data...[/bold]")
    tickers = ["NVDA", "AMD", "INTC", "TSM", "AVGO", "MRVL"]

    with FMPEnricher() as enricher:
        companies = enricher.enrich_multiple(tickers)

    # 建構同業比較表
    console.print("[bold]Building peer comparison table...[/bold]\n")
    builder = PeerComparisonBuilder()
    table = builder.build("NVDA", companies)

    # 顯示 Markdown 表格
    console.print(Markdown(table.markdown))

    # 顯示 takeaways
    console.print("\n[bold]Takeaways:[/bold]")
    for i, takeaway in enumerate(table.takeaways, 1):
        console.print(f"  {i}. {takeaway}")


if __name__ == "__main__":
    main()

"""Financial Data Null Filler

當 FMP 資料有 null 時，使用以下策略補齊：
1. 從其他欄位推算 (e.g., net_margin = net_income / revenue)
2. 使用行業平均值
3. 使用合理的預設值
4. 標記為 N/A 並在報告中說明

絕不捏造數字，但可以用已知數據推算。
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple

from ..utils.logging import get_logger
from .base import Fundamentals, Estimates, CompanyData

logger = get_logger(__name__)


# 行業平均 Gross Margin (作為 fallback)
SECTOR_GROSS_MARGINS = {
    "Technology": 0.55,
    "Semiconductors": 0.50,
    "Software—Infrastructure": 0.75,
    "Software—Application": 0.70,
    "Internet Content & Information": 0.60,
    "Consumer Electronics": 0.35,
    "Communication Equipment": 0.45,
    "Cloud Computing": 0.65,
    "Healthcare": 0.55,
    "Financial Services": 0.60,
    "default": 0.40,
}

# 行業平均 Operating Margin
SECTOR_OPERATING_MARGINS = {
    "Technology": 0.25,
    "Semiconductors": 0.30,
    "Software—Infrastructure": 0.35,
    "Software—Application": 0.20,
    "Internet Content & Information": 0.25,
    "Consumer Electronics": 0.10,
    "Communication Equipment": 0.15,
    "Cloud Computing": 0.20,
    "Healthcare": 0.18,
    "Financial Services": 0.30,
    "default": 0.15,
}


@dataclass
class FillResult:
    """填補結果"""
    field: str
    original_value: Any
    filled_value: Any
    method: str  # calculated, sector_avg, default, unchanged
    confidence: str  # high, medium, low


def calculate_from_available(fundamentals: Dict, price_data: Dict) -> Dict[str, Tuple[Any, str]]:
    """從已有數據推算缺失值

    Args:
        fundamentals: 財務數據 dict
        price_data: 價格數據 dict

    Returns:
        {field: (calculated_value, method)}
    """
    results = {}

    revenue = fundamentals.get("revenue_ttm")
    net_income = fundamentals.get("net_income_ttm")
    ebitda = fundamentals.get("ebitda_ttm")
    fcf = fundamentals.get("fcf_ttm")
    market_cap = price_data.get("market_cap")
    price = price_data.get("last")

    # 1. Net Margin: 如果有 revenue 和 net_income
    if fundamentals.get("net_margin") is None and revenue and net_income:
        net_margin = net_income / revenue
        results["net_margin"] = (round(net_margin, 4), "calculated")

    # 2. Operating Margin: 通常 = Net Margin + ~10% (粗略估計)
    #    或從 EBITDA margin 推算
    if fundamentals.get("operating_margin") is None:
        if ebitda and revenue:
            # EBITDA margin 減去 D&A (假設 ~5%)
            ebitda_margin = ebitda / revenue
            op_margin = ebitda_margin - 0.05
            results["operating_margin"] = (round(op_margin, 4), "calculated_from_ebitda")
        elif net_income and revenue:
            # 假設 interest + tax = 10%
            net_margin = net_income / revenue
            op_margin = net_margin * 1.3  # 粗略調整
            results["operating_margin"] = (round(op_margin, 4), "estimated")

    # 3. Gross Margin: 如果完全沒有，無法推算
    # 4. FCF Margin: 如果有 FCF 和 Revenue
    if fcf and revenue:
        fcf_margin = fcf / revenue
        results["fcf_margin"] = (round(fcf_margin, 4), "calculated")

    # 5. P/E Ratio: 如果有 market_cap 和 net_income
    if market_cap and net_income and net_income > 0:
        pe_ratio = market_cap / net_income
        results["pe_ttm"] = (round(pe_ratio, 2), "calculated")

    # 6. P/S Ratio: 如果有 market_cap 和 revenue
    if market_cap and revenue and revenue > 0:
        ps_ratio = market_cap / revenue
        results["ps_ttm"] = (round(ps_ratio, 2), "calculated")

    # 7. EV/EBITDA: 如果有 market_cap 和 ebitda
    if market_cap and ebitda and ebitda > 0:
        # EV ≈ Market Cap (簡化，忽略 debt/cash)
        ev_ebitda = market_cap / ebitda
        results["ev_ebitda"] = (round(ev_ebitda, 2), "calculated_simplified")

    return results


def fill_with_sector_average(
    fundamentals: Dict,
    sector: Optional[str] = None,
    industry: Optional[str] = None,
) -> Dict[str, Tuple[Any, str]]:
    """使用行業平均值填補

    Args:
        fundamentals: 財務數據
        sector: 行業
        industry: 細分行業

    Returns:
        {field: (filled_value, method)}
    """
    results = {}

    # 優先使用 industry，再用 sector
    lookup_key = industry or sector or "default"

    if fundamentals.get("gross_margin") is None:
        avg = SECTOR_GROSS_MARGINS.get(lookup_key, SECTOR_GROSS_MARGINS.get("default"))
        results["gross_margin"] = (avg, f"sector_avg:{lookup_key}")

    if fundamentals.get("operating_margin") is None:
        avg = SECTOR_OPERATING_MARGINS.get(lookup_key, SECTOR_OPERATING_MARGINS.get("default"))
        results["operating_margin"] = (avg, f"sector_avg:{lookup_key}")

    return results


def fill_company_financials(company: CompanyData) -> Tuple[CompanyData, List[FillResult]]:
    """填補單一公司的財務數據

    Args:
        company: 公司資料

    Returns:
        (filled_company, fill_results)
    """
    fill_results = []

    if not company.fundamentals:
        logger.warning(f"{company.ticker}: No fundamentals to fill")
        return company, fill_results

    fundamentals_dict = company.fundamentals.to_dict()
    price_dict = company.price.to_dict() if company.price else {}

    # 1. 嘗試從已有數據計算
    calculated = calculate_from_available(fundamentals_dict, price_dict)
    for field, (value, method) in calculated.items():
        if fundamentals_dict.get(field) is None:
            fill_results.append(FillResult(
                field=field,
                original_value=None,
                filled_value=value,
                method=method,
                confidence="high" if "calculated" in method else "medium",
            ))
            fundamentals_dict[field] = value

    # 2. 使用行業平均值
    sector_fills = fill_with_sector_average(
        fundamentals_dict,
        sector=company.sector,
        industry=company.industry,
    )
    for field, (value, method) in sector_fills.items():
        if fundamentals_dict.get(field) is None:
            fill_results.append(FillResult(
                field=field,
                original_value=None,
                filled_value=value,
                method=method,
                confidence="low",
            ))
            fundamentals_dict[field] = value

    # 重建 Fundamentals 物件
    company.fundamentals = Fundamentals(
        revenue_ttm=fundamentals_dict.get("revenue_ttm"),
        ebitda_ttm=fundamentals_dict.get("ebitda_ttm"),
        net_income_ttm=fundamentals_dict.get("net_income_ttm"),
        fcf_ttm=fundamentals_dict.get("fcf_ttm"),
        gross_margin=fundamentals_dict.get("gross_margin"),
        operating_margin=fundamentals_dict.get("operating_margin"),
        net_margin=fundamentals_dict.get("net_margin"),
        debt_to_equity=fundamentals_dict.get("debt_to_equity"),
        current_ratio=fundamentals_dict.get("current_ratio"),
    )

    return company, fill_results


def fill_all_companies(
    companies: Dict[str, CompanyData],
) -> Tuple[Dict[str, CompanyData], Dict[str, List[FillResult]]]:
    """填補所有公司的財務數據

    Args:
        companies: {ticker: CompanyData} 字典

    Returns:
        (filled_companies, {ticker: fill_results})
    """
    all_fill_results = {}

    for ticker, company in companies.items():
        filled_company, fill_results = fill_company_financials(company)
        companies[ticker] = filled_company

        if fill_results:
            all_fill_results[ticker] = fill_results
            logger.info(f"{ticker}: Filled {len(fill_results)} fields")

    return companies, all_fill_results


def generate_fill_disclosure(
    fill_results: Dict[str, List[FillResult]],
) -> str:
    """生成填補說明文字

    用於在報告中揭露哪些數據是推算的。

    Args:
        fill_results: {ticker: [FillResult, ...]}

    Returns:
        揭露說明文字
    """
    if not fill_results:
        return ""

    lines = ["**數據來源說明：**"]

    for ticker, results in fill_results.items():
        low_confidence = [r for r in results if r.confidence == "low"]
        if low_confidence:
            fields = ", ".join([r.field for r in low_confidence])
            lines.append(f"- {ticker}: {fields} 使用行業平均值估計")

    if len(lines) == 1:
        return ""

    return "\n".join(lines)


def format_financial_value(
    value: Optional[float],
    format_type: str = "number",
    fallback: str = "N/A",
) -> str:
    """格式化財務數值

    Args:
        value: 數值
        format_type: number, percent, currency, multiple
        fallback: 當 value 為 None 時的顯示

    Returns:
        格式化後的字串
    """
    if value is None:
        return fallback

    if format_type == "percent":
        # For margin-like fields that are stored as fractions (0.678 = 67.8%)
        return f"{value * 100:.1f}%"
    elif format_type == "percent_raw":
        # For fields already in percent form (0.99 = 0.99%, e.g., change_pct_1d)
        # DO NOT multiply by 100
        return f"{value:+.2f}%"
    elif format_type == "currency":
        if abs(value) >= 1e12:
            return f"${value / 1e12:.2f}T"
        elif abs(value) >= 1e9:
            return f"${value / 1e9:.2f}B"
        elif abs(value) >= 1e6:
            return f"${value / 1e6:.2f}M"
        else:
            return f"${value:,.0f}"
    elif format_type == "multiple":
        return f"{value:.1f}x"
    else:
        if abs(value) >= 1e9:
            return f"{value / 1e9:.2f}B"
        elif abs(value) >= 1e6:
            return f"{value / 1e6:.2f}M"
        else:
            return f"{value:,.0f}"


def main():
    """CLI demo"""
    from rich.console import Console
    from rich.table import Table

    console = Console()

    # 模擬一個有缺失數據的公司
    from .base import PriceData

    company = CompanyData(
        ticker="TEST",
        name="Test Company",
        sector="Technology",
        industry="Semiconductors",
        price=PriceData(
            last=150.0,
            change_pct_1d=2.5,
            market_cap=200e9,  # 200B
        ),
        fundamentals=Fundamentals(
            revenue_ttm=50e9,  # 50B
            ebitda_ttm=20e9,  # 20B
            net_income_ttm=15e9,  # 15B
            fcf_ttm=18e9,  # 18B
            gross_margin=None,  # Missing!
            operating_margin=None,  # Missing!
            net_margin=None,  # Missing!
            debt_to_equity=0.3,
            current_ratio=2.5,
        ),
    )

    console.print("[bold cyan]Financial Data Null Filler Demo[/bold cyan]\n")

    console.print("[yellow]Before:[/yellow]")
    console.print(f"  Gross Margin: {company.fundamentals.gross_margin}")
    console.print(f"  Operating Margin: {company.fundamentals.operating_margin}")
    console.print(f"  Net Margin: {company.fundamentals.net_margin}")

    filled_company, results = fill_company_financials(company)

    console.print("\n[green]After:[/green]")
    console.print(f"  Gross Margin: {format_financial_value(filled_company.fundamentals.gross_margin, 'percent')}")
    console.print(f"  Operating Margin: {format_financial_value(filled_company.fundamentals.operating_margin, 'percent')}")
    console.print(f"  Net Margin: {format_financial_value(filled_company.fundamentals.net_margin, 'percent')}")

    console.print("\n[bold]Fill Results:[/bold]")
    table = Table()
    table.add_column("Field")
    table.add_column("Value")
    table.add_column("Method")
    table.add_column("Confidence")

    for result in results:
        table.add_row(
            result.field,
            str(result.filled_value),
            result.method,
            result.confidence,
        )

    console.print(table)

    console.print("\n[bold]Disclosure:[/bold]")
    console.print(generate_fill_disclosure({"TEST": results}))


if __name__ == "__main__":
    main()

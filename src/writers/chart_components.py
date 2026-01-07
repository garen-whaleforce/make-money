"""Chart Components - 圖表資料結構與渲染 v4.3

每篇文章建議加 1 張圖：
- Flash: 板塊資金訊號圖（漲跌幅 + 成交量倍數）
- Earnings: 估值壓力測試圖（Bear/Base/Bull 目標價）
- Deep Dive: 財務趨勢圖（8 季營收/毛利率）

這些圖表使用 inline SVG 或 HTML/CSS 表格視覺化，
確保 Ghost email 和網頁都能正確顯示。
"""

from dataclasses import dataclass
from typing import List, Optional


# =============================================================================
# 資料結構
# =============================================================================

@dataclass
class SectorFlowItem:
    """板塊資金訊號項目 (Flash)"""
    ticker: str
    name: str
    change_pct: float
    volume_ratio: float  # 相對平均成交量倍數
    signal: str  # "bullish", "bearish", "neutral"


@dataclass
class ValuationScenario:
    """估值情境 (Earnings)"""
    label: str  # "Bear", "Base", "Bull"
    target_price: float
    multiple: float  # P/E 或其他倍數
    rationale: str
    probability: Optional[float] = None  # 機率 (0-1)


@dataclass
class QuarterlyMetric:
    """季度指標 (Deep Dive)"""
    quarter: str  # "Q1'24", "Q2'24" 等
    revenue: float  # 營收 (in millions)
    gross_margin: Optional[float] = None  # 毛利率 (%)
    operating_margin: Optional[float] = None  # 營業利潤率 (%)
    revenue_growth: Optional[float] = None  # YoY 成長率 (%)


# =============================================================================
# Flash: 板塊資金訊號圖
# =============================================================================

def render_sector_flow_chart(
    items: List[SectorFlowItem],
    title: str = "板塊資金訊號",
) -> str:
    """渲染板塊資金訊號圖

    顯示 6-8 個 ticker 的漲跌幅和成交量倍數。
    使用水平條形圖視覺化。

    Args:
        items: SectorFlowItem 列表
        title: 圖表標題

    Returns:
        HTML 字串
    """
    bars_html = ""
    max_change = max(abs(item.change_pct) for item in items) if items else 10

    for item in items[:8]:
        # 決定顏色
        if item.change_pct >= 2:
            color = "#10b981"  # 強漲
        elif item.change_pct >= 0:
            color = "#6ee7b7"  # 微漲
        elif item.change_pct >= -2:
            color = "#fca5a5"  # 微跌
        else:
            color = "#ef4444"  # 強跌

        # 計算條形寬度 (0-100%)
        bar_width = min(abs(item.change_pct) / max_change * 80, 80)

        # 成交量標記
        vol_label = f"{item.volume_ratio:.1f}x" if item.volume_ratio else ""
        vol_style = "background: #fef3c7; color: #92400e;" if item.volume_ratio >= 1.5 else "background: #f3f4f6; color: #6b7280;"

        # 方向箭頭
        arrow = "↑" if item.change_pct >= 0 else "↓"
        change_prefix = "+" if item.change_pct >= 0 else ""

        bars_html += f'''
        <div style="display: flex; align-items: center; margin-bottom: 12px; padding: 12px; background: #ffffff; border: 1px solid #e5e5e5; border-radius: 8px;">
            <div style="width: 80px; font-weight: 600; color: #3b82f6;">{item.ticker}</div>
            <div style="flex: 1; margin: 0 16px;">
                <div style="height: 24px; background: #f3f4f6; border-radius: 4px; overflow: hidden; position: relative;">
                    <div style="width: {bar_width}%; height: 100%; background: {color}; border-radius: 4px;"></div>
                </div>
            </div>
            <div style="width: 80px; text-align: right; font-weight: 600; color: {color};">
                {arrow} {change_prefix}{item.change_pct:.1f}%
            </div>
            <div style="width: 50px; text-align: center; margin-left: 12px;">
                <span style="padding: 2px 8px; border-radius: 4px; font-size: 12px; {vol_style}">{vol_label}</span>
            </div>
        </div>
        '''

    return f'''
    <div style="margin: 24px 0; font-family: system-ui, -apple-system, sans-serif;">
        <h3 style="margin: 0 0 16px 0; font-size: 18px; font-weight: 600; color: #1a1a1a;">📊 {title}</h3>
        <div style="background: #f9fafb; padding: 16px; border-radius: 12px;">
            <div style="display: flex; margin-bottom: 8px; padding: 0 12px; font-size: 12px; color: #6b7280;">
                <div style="width: 80px;">Ticker</div>
                <div style="flex: 1; text-align: center;">漲跌幅</div>
                <div style="width: 80px; text-align: right;">變動</div>
                <div style="width: 50px; text-align: center; margin-left: 12px;">成交量</div>
            </div>
            {bars_html}
        </div>
        <div style="margin-top: 8px; font-size: 12px; color: #6b7280; text-align: right;">
            成交量倍數 ≥1.5x 以黃色標記
        </div>
    </div>
    '''


# =============================================================================
# Earnings: 估值壓力測試圖
# =============================================================================

def render_valuation_stress_chart(
    current_price: float,
    scenarios: List[ValuationScenario],
    ticker: str,
    title: str = "估值壓力測試",
) -> str:
    """渲染估值壓力測試圖

    顯示 Bear/Base/Bull 三段目標價的視覺化比較。

    Args:
        current_price: 當前股價
        scenarios: ValuationScenario 列表 (應包含 Bear, Base, Bull)
        ticker: 股票代碼
        title: 圖表標題

    Returns:
        HTML 字串
    """
    # 排序並取得價格範圍
    sorted_scenarios = sorted(scenarios, key=lambda x: x.target_price)
    min_price = min(s.target_price for s in scenarios) * 0.9
    max_price = max(s.target_price for s in scenarios) * 1.1
    price_range = max_price - min_price

    # 計算位置
    def get_position(price: float) -> float:
        return ((price - min_price) / price_range) * 100 if price_range > 0 else 50

    current_pos = get_position(current_price)

    # 情境顏色
    scenario_colors = {
        "Bear": {"bg": "#fee2e2", "border": "#ef4444", "text": "#991b1b"},
        "Base": {"bg": "#dbeafe", "border": "#3b82f6", "text": "#1e40af"},
        "Bull": {"bg": "#dcfce7", "border": "#10b981", "text": "#166534"},
    }

    # 生成區間視覺化
    zones_html = ""
    for i, scenario in enumerate(sorted_scenarios):
        colors = scenario_colors.get(scenario.label, scenario_colors["Base"])
        pos = get_position(scenario.target_price)
        upside = ((scenario.target_price / current_price) - 1) * 100

        upside_label = f"+{upside:.0f}%" if upside >= 0 else f"{upside:.0f}%"

        zones_html += f'''
        <div style="position: absolute; left: {pos}%; transform: translateX(-50%); text-align: center;">
            <div style="width: 3px; height: 40px; background: {colors["border"]}; margin: 0 auto;"></div>
            <div style="padding: 8px 12px; background: {colors["bg"]}; border: 1px solid {colors["border"]}; border-radius: 8px; margin-top: 8px;">
                <div style="font-size: 12px; font-weight: 600; color: {colors["text"]};">{scenario.label}</div>
                <div style="font-size: 16px; font-weight: 700; color: {colors["text"]};">${scenario.target_price:.0f}</div>
                <div style="font-size: 11px; color: {colors["text"]};">{scenario.multiple:.1f}x P/E</div>
                <div style="font-size: 11px; color: {colors["text"]}; margin-top: 4px;">{upside_label}</div>
            </div>
        </div>
        '''

    # 表格資訊
    table_rows = ""
    for scenario in scenarios:
        colors = scenario_colors.get(scenario.label, scenario_colors["Base"])
        upside = ((scenario.target_price / current_price) - 1) * 100
        upside_label = f"+{upside:.1f}%" if upside >= 0 else f"{upside:.1f}%"

        table_rows += f'''
        <tr>
            <td style="padding: 12px; border-bottom: 1px solid #e5e5e5;">
                <span style="padding: 4px 8px; background: {colors["bg"]}; border-radius: 4px; font-weight: 600; color: {colors["text"]};">{scenario.label}</span>
            </td>
            <td style="padding: 12px; border-bottom: 1px solid #e5e5e5; font-weight: 600;">${scenario.target_price:.0f}</td>
            <td style="padding: 12px; border-bottom: 1px solid #e5e5e5;">{scenario.multiple:.1f}x</td>
            <td style="padding: 12px; border-bottom: 1px solid #e5e5e5; color: {"#10b981" if upside >= 0 else "#ef4444"};">{upside_label}</td>
            <td style="padding: 12px; border-bottom: 1px solid #e5e5e5; font-size: 13px; color: #6b7280;">{scenario.rationale}</td>
        </tr>
        '''

    return f'''
    <div style="margin: 24px 0; font-family: system-ui, -apple-system, sans-serif;">
        <h3 style="margin: 0 0 16px 0; font-size: 18px; font-weight: 600; color: #1a1a1a;">📈 {title} - {ticker}</h3>

        <!-- 視覺化區間 -->
        <div style="background: #f9fafb; padding: 24px; border-radius: 12px; margin-bottom: 16px;">
            <div style="position: relative; height: 120px; margin: 0 40px;">
                <!-- 軸線 -->
                <div style="position: absolute; top: 20px; left: 0; right: 0; height: 2px; background: #e5e5e5;"></div>

                <!-- 當前價格標記 -->
                <div style="position: absolute; left: {current_pos}%; transform: translateX(-50%); text-align: center;">
                    <div style="width: 12px; height: 12px; background: #1a1a1a; border-radius: 50%; margin: 14px auto 0 auto;"></div>
                    <div style="margin-top: 48px; padding: 6px 10px; background: #1a1a1a; border-radius: 4px;">
                        <div style="font-size: 11px; color: #ffffff;">現價</div>
                        <div style="font-size: 14px; font-weight: 700; color: #ffffff;">${current_price:.0f}</div>
                    </div>
                </div>

                {zones_html}
            </div>
        </div>

        <!-- 情境表格 -->
        <table style="width: 100%; border-collapse: collapse; background: #ffffff; border: 1px solid #e5e5e5; border-radius: 8px; overflow: hidden;">
            <thead>
                <tr style="background: #f9fafb;">
                    <th style="padding: 12px; text-align: left; font-weight: 600;">情境</th>
                    <th style="padding: 12px; text-align: left; font-weight: 600;">目標價</th>
                    <th style="padding: 12px; text-align: left; font-weight: 600;">倍數</th>
                    <th style="padding: 12px; text-align: left; font-weight: 600;">潛在報酬</th>
                    <th style="padding: 12px; text-align: left; font-weight: 600;">觸發條件</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
    </div>
    '''


# =============================================================================
# Deep Dive: 財務趨勢圖
# =============================================================================

def render_financial_trend_chart(
    quarters: List[QuarterlyMetric],
    ticker: str,
    title: str = "財務趨勢",
    show_margins: bool = True,
) -> str:
    """渲染財務趨勢圖

    顯示 8 季營收、毛利率、營業利潤率趨勢。

    Args:
        quarters: QuarterlyMetric 列表（按時間順序）
        ticker: 股票代碼
        title: 圖表標題
        show_margins: 是否顯示利潤率

    Returns:
        HTML 字串
    """
    if not quarters:
        return ""

    # 計算營收最大值
    max_revenue = max(q.revenue for q in quarters)

    # 生成條形圖
    bars_html = ""
    for q in quarters[-8:]:  # 最近 8 季
        bar_height = (q.revenue / max_revenue * 100) if max_revenue > 0 else 0
        revenue_b = q.revenue / 1000  # 轉換為 B

        # 成長率顏色
        growth_html = ""
        if q.revenue_growth is not None:
            growth_color = "#10b981" if q.revenue_growth >= 0 else "#ef4444"
            growth_prefix = "+" if q.revenue_growth >= 0 else ""
            growth_html = f'<div style="font-size: 10px; color: {growth_color};">{growth_prefix}{q.revenue_growth:.0f}%</div>'

        bars_html += f'''
        <div style="flex: 1; display: flex; flex-direction: column; align-items: center; min-width: 60px;">
            <div style="width: 100%; height: 120px; display: flex; align-items: flex-end; justify-content: center;">
                <div style="width: 70%; height: {bar_height}%; background: linear-gradient(to top, #3b82f6, #60a5fa); border-radius: 4px 4px 0 0;"></div>
            </div>
            <div style="margin-top: 8px; text-align: center;">
                <div style="font-size: 11px; font-weight: 600; color: #1a1a1a;">${revenue_b:.1f}B</div>
                {growth_html}
                <div style="font-size: 10px; color: #6b7280; margin-top: 4px;">{q.quarter}</div>
            </div>
        </div>
        '''

    # 利潤率趨勢表
    margins_html = ""
    if show_margins:
        margin_rows = ""
        for q in quarters[-8:]:
            gm = f"{q.gross_margin:.1f}%" if q.gross_margin is not None else "—"
            om = f"{q.operating_margin:.1f}%" if q.operating_margin is not None else "—"

            margin_rows += f'''
            <td style="padding: 8px; text-align: center; border-bottom: 1px solid #e5e5e5;">
                <div style="font-size: 12px; color: #10b981;">{gm}</div>
                <div style="font-size: 12px; color: #3b82f6;">{om}</div>
            </td>
            '''

        margins_html = f'''
        <div style="margin-top: 16px; overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="background: #f9fafb;">
                    <td style="padding: 8px; font-weight: 600; font-size: 12px; color: #6b7280;">毛利率</td>
                    {margin_rows}
                </tr>
            </table>
        </div>
        '''

    return f'''
    <div style="margin: 24px 0; font-family: system-ui, -apple-system, sans-serif;">
        <h3 style="margin: 0 0 16px 0; font-size: 18px; font-weight: 600; color: #1a1a1a;">📈 {title} - {ticker}</h3>

        <div style="background: #f9fafb; padding: 24px; border-radius: 12px;">
            <!-- 營收條形圖 -->
            <div style="display: flex; gap: 8px; align-items: flex-end;">
                {bars_html}
            </div>

            <div style="text-align: center; margin-top: 12px; font-size: 12px; color: #6b7280;">
                季度營收趨勢（單位：十億美元）
            </div>

            {margins_html}
        </div>

        <div style="display: flex; gap: 16px; margin-top: 12px; font-size: 12px;">
            <span style="display: flex; align-items: center; gap: 4px;">
                <span style="width: 12px; height: 12px; background: #3b82f6; border-radius: 2px;"></span>
                營收
            </span>
            <span style="display: flex; align-items: center; gap: 4px;">
                <span style="color: #10b981;">●</span> 毛利率
            </span>
            <span style="display: flex; align-items: center; gap: 4px;">
                <span style="color: #3b82f6;">●</span> 營業利潤率
            </span>
        </div>
    </div>
    '''


# =============================================================================
# JSON 資料欄位規格 (供 LLM 輸出使用)
# =============================================================================

CHART_DATA_SCHEMAS = {
    "flash_sector_flow": {
        "description": "Flash 板塊資金訊號圖資料",
        "fields": {
            "items": [
                {
                    "ticker": "NVDA",
                    "name": "NVIDIA",
                    "change_pct": 3.5,
                    "volume_ratio": 1.8,
                    "signal": "bullish"
                }
            ]
        }
    },
    "earnings_valuation_stress": {
        "description": "Earnings 估值壓力測試圖資料",
        "fields": {
            "current_price": 150.0,
            "ticker": "NVDA",
            "scenarios": [
                {
                    "label": "Bear",
                    "target_price": 120.0,
                    "multiple": 25.0,
                    "rationale": "AI 需求放緩"
                },
                {
                    "label": "Base",
                    "target_price": 160.0,
                    "multiple": 32.0,
                    "rationale": "維持現有增長軌道"
                },
                {
                    "label": "Bull",
                    "target_price": 200.0,
                    "multiple": 40.0,
                    "rationale": "AI 加速採用"
                }
            ]
        }
    },
    "deep_financial_trend": {
        "description": "Deep Dive 財務趨勢圖資料",
        "fields": {
            "ticker": "NVDA",
            "quarters": [
                {
                    "quarter": "Q1'24",
                    "revenue": 26044,
                    "gross_margin": 78.4,
                    "operating_margin": 56.0,
                    "revenue_growth": 262
                }
            ]
        }
    }
}

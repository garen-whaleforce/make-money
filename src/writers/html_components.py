"""HTML Components - Rocket Screener Design System v4.3

提供標準化的 HTML 元件，確保三種 Post（Flash、Earnings、Deep Dive）
可以共用一致的視覺風格。

統一版型元件清單：
1. Header - 標題 + tags pills
2. DataStamp - 資料時間戳記
3. TodaysPackage - 三篇互鏈（Flash → Earnings → Deep Dive）
4. DualSummary - 中英雙語摘要
5. KeyNumbers - 關鍵數字卡片（3-5 個 KPI）
6. TLDRBullets - 6 bullet 摘要
7. PaywallGate - 固定文案 + 按鈕 + 分隔線
8. MemberSection - 深度內容（含圖表）

額外元件：
- CardBox - 卡片式資訊框
- DataTable - 數據表格
- QuoteBlock - 引用區塊
- AlertBanner - 警示橫幅
- TickerPill - 股票標籤
- ScenarioMatrix - 情境矩陣（3x3 EPS × Guidance）
- TimelineBlock - 時間軸
- SourceFooter - 來源頁尾
- NewsRadarItem - 新聞雷達條目（4 行模板）
"""

from dataclasses import dataclass
from typing import Optional, List


# 共用樣式（inline CSS for email compatibility）
BASE_STYLES = {
    "font_family": "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    "text_color": "#1a1a1a",
    "bg_color": "#ffffff",
    "border_color": "#e5e5e5",
    "accent_color": "#3b82f6",  # Blue
    "success_color": "#10b981",  # Green
    "warning_color": "#f59e0b",  # Amber
    "danger_color": "#ef4444",   # Red
    "muted_color": "#6b7280",    # Gray
}


@dataclass
class CardItem:
    """卡片項目"""
    value: str
    label: str
    sublabel: Optional[str] = None
    color: Optional[str] = None  # "success", "warning", "danger", "neutral"


def render_card_box(items: list[CardItem], title: Optional[str] = None) -> str:
    """元件 1: CardBox - 卡片式資訊框

    用於顯示關鍵數字、指標等。

    Args:
        items: 卡片項目列表
        title: 區塊標題（可選）

    Returns:
        HTML 字串
    """
    color_map = {
        "success": BASE_STYLES["success_color"],
        "warning": BASE_STYLES["warning_color"],
        "danger": BASE_STYLES["danger_color"],
        "neutral": BASE_STYLES["muted_color"],
    }

    cards_html = ""
    for item in items:
        value_color = color_map.get(item.color, BASE_STYLES["text_color"])
        sublabel_html = f'<div style="font-size: 12px; color: {BASE_STYLES["muted_color"]};">{item.sublabel}</div>' if item.sublabel else ""

        cards_html += f'''
        <div style="flex: 1; min-width: 120px; padding: 16px; background: {BASE_STYLES["bg_color"]}; border: 1px solid {BASE_STYLES["border_color"]}; border-radius: 8px; text-align: center;">
            <div style="font-size: 24px; font-weight: 700; color: {value_color}; margin-bottom: 4px;">{item.value}</div>
            <div style="font-size: 14px; color: {BASE_STYLES["muted_color"]};">{item.label}</div>
            {sublabel_html}
        </div>
        '''

    title_html = f'<h3 style="margin: 0 0 16px 0; font-size: 18px; font-weight: 600; color: {BASE_STYLES["text_color"]};">{title}</h3>' if title else ""

    return f'''
    <div style="margin: 24px 0; font-family: {BASE_STYLES["font_family"]};">
        {title_html}
        <div style="display: flex; flex-wrap: wrap; gap: 12px;">
            {cards_html}
        </div>
    </div>
    '''


def render_data_table(
    headers: list[str],
    rows: list[list[str]],
    title: Optional[str] = None,
    highlight_first_col: bool = False,
) -> str:
    """元件 2: DataTable - 數據表格

    用於同業比較、財報記分板等表格資料。

    Args:
        headers: 表頭列表
        rows: 資料列（二維陣列）
        title: 表格標題（可選）
        highlight_first_col: 是否強調第一欄（如 ticker）

    Returns:
        HTML 字串
    """
    header_cells = "".join([
        f'<th style="padding: 12px 16px; text-align: left; font-weight: 600; background: #f9fafb; border-bottom: 2px solid {BASE_STYLES["border_color"]};">{h}</th>'
        for h in headers
    ])

    row_html = ""
    for row in rows:
        cells = ""
        for i, cell in enumerate(row):
            style = "padding: 12px 16px; border-bottom: 1px solid " + BASE_STYLES["border_color"] + ";"
            if highlight_first_col and i == 0:
                style += f" font-weight: 600; color: {BASE_STYLES['accent_color']};"
            cells += f'<td style="{style}">{cell}</td>'
        row_html += f'<tr style="background: {BASE_STYLES["bg_color"]};">{cells}</tr>'

    title_html = f'<h3 style="margin: 0 0 16px 0; font-size: 18px; font-weight: 600; color: {BASE_STYLES["text_color"]};">{title}</h3>' if title else ""

    return f'''
    <div style="margin: 24px 0; font-family: {BASE_STYLES["font_family"]};">
        {title_html}
        <div style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse; border: 1px solid {BASE_STYLES["border_color"]}; border-radius: 8px; overflow: hidden;">
                <thead>
                    <tr>{header_cells}</tr>
                </thead>
                <tbody>
                    {row_html}
                </tbody>
            </table>
        </div>
    </div>
    '''


def render_quote_block(
    quote: str,
    attribution: Optional[str] = None,
    context: Optional[str] = None,
) -> str:
    """元件 3: QuoteBlock - 引用區塊

    用於管理層語錄、關鍵觀點等。

    Args:
        quote: 引用內容
        attribution: 出處/發言者
        context: 上下文說明

    Returns:
        HTML 字串
    """
    attribution_html = f'<div style="margin-top: 12px; font-size: 14px; font-weight: 600; color: {BASE_STYLES["text_color"]};">— {attribution}</div>' if attribution else ""
    context_html = f'<div style="margin-top: 8px; font-size: 13px; color: {BASE_STYLES["muted_color"]};">{context}</div>' if context else ""

    return f'''
    <blockquote style="margin: 24px 0; padding: 20px 24px; background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%); border-left: 4px solid {BASE_STYLES["accent_color"]}; border-radius: 0 8px 8px 0; font-family: {BASE_STYLES["font_family"]};">
        <div style="font-size: 16px; line-height: 1.6; color: {BASE_STYLES["text_color"]}; font-style: italic;">"{quote}"</div>
        {attribution_html}
        {context_html}
    </blockquote>
    '''


def render_alert_banner(
    message: str,
    alert_type: str = "info",  # "info", "success", "warning", "danger"
    title: Optional[str] = None,
) -> str:
    """元件 4: AlertBanner - 警示橫幅

    用於重要提醒、風險警告等。

    Args:
        message: 訊息內容
        alert_type: 警示類型
        title: 標題（可選）

    Returns:
        HTML 字串
    """
    colors = {
        "info": {"bg": "#eff6ff", "border": "#3b82f6", "icon": "ℹ️"},
        "success": {"bg": "#f0fdf4", "border": "#10b981", "icon": "✓"},
        "warning": {"bg": "#fffbeb", "border": "#f59e0b", "icon": "⚠️"},
        "danger": {"bg": "#fef2f2", "border": "#ef4444", "icon": "⚠"},
    }

    c = colors.get(alert_type, colors["info"])
    title_html = f'<div style="font-weight: 600; margin-bottom: 4px;">{title}</div>' if title else ""

    return f'''
    <div style="margin: 24px 0; padding: 16px 20px; background: {c["bg"]}; border-left: 4px solid {c["border"]}; border-radius: 0 8px 8px 0; font-family: {BASE_STYLES["font_family"]};">
        <div style="display: flex; align-items: flex-start; gap: 12px;">
            <span style="font-size: 18px;">{c["icon"]}</span>
            <div style="flex: 1;">
                {title_html}
                <div style="font-size: 14px; line-height: 1.5; color: {BASE_STYLES["text_color"]};">{message}</div>
            </div>
        </div>
    </div>
    '''


def render_ticker_pill(
    ticker: str,
    price: Optional[float] = None,
    change_pct: Optional[float] = None,
    link: Optional[str] = None,
) -> str:
    """元件 5: TickerPill - 股票標籤

    用於股票代碼 + 漲跌顯示。

    Args:
        ticker: 股票代碼
        price: 價格（可選）
        change_pct: 漲跌幅（可選）
        link: 連結（可選）

    Returns:
        HTML 字串
    """
    change_color = BASE_STYLES["success_color"] if (change_pct or 0) >= 0 else BASE_STYLES["danger_color"]
    change_prefix = "+" if (change_pct or 0) >= 0 else ""

    price_html = f'<span style="margin-left: 8px; font-weight: 500;">${price:.2f}</span>' if price else ""
    change_html = f'<span style="margin-left: 4px; color: {change_color};">({change_prefix}{change_pct:.1f}%)</span>' if change_pct is not None else ""

    content = f'{ticker}{price_html}{change_html}'

    if link:
        return f'''<a href="{link}" style="display: inline-flex; align-items: center; padding: 4px 12px; background: #f3f4f6; border-radius: 16px; font-family: {BASE_STYLES["font_family"]}; font-size: 14px; font-weight: 600; color: {BASE_STYLES["accent_color"]}; text-decoration: none; margin: 4px;">{content}</a>'''

    return f'''<span style="display: inline-flex; align-items: center; padding: 4px 12px; background: #f3f4f6; border-radius: 16px; font-family: {BASE_STYLES["font_family"]}; font-size: 14px; font-weight: 600; color: {BASE_STYLES["text_color"]}; margin: 4px;">{content}</span>'''


def render_scenario_matrix(
    scenarios: dict,
    title: Optional[str] = None,
) -> str:
    """元件 6: ScenarioMatrix - 情境矩陣

    用於 3x3 EPS × Guidance 情境矩陣。

    Args:
        scenarios: 情境字典，格式如：
            {
                "beat_raised": {"label": "🚀 強勢突破", "description": "...", "action": "..."},
                "beat_maintained": {...},
                ...
            }
        title: 標題（可選）

    Returns:
        HTML 字串
    """
    # 情境順序和標籤
    rows = [
        ("EPS Beat", ["beat_raised", "beat_maintained", "beat_lowered"]),
        ("EPS Inline", ["inline_raised", "inline_maintained", "inline_lowered"]),
        ("EPS Miss", ["miss_raised", "miss_maintained", "miss_lowered"]),
    ]
    cols = ["Guidance Raised", "Guidance Maintained", "Guidance Lowered"]

    # 顏色映射
    cell_colors = {
        "beat_raised": "#dcfce7",      # Green
        "beat_maintained": "#ecfdf5",  # Light green
        "beat_lowered": "#fef3c7",     # Amber
        "inline_raised": "#dbeafe",    # Blue
        "inline_maintained": "#f3f4f6", # Gray
        "inline_lowered": "#fee2e2",   # Light red
        "miss_raised": "#fef3c7",      # Amber
        "miss_maintained": "#fee2e2",  # Light red
        "miss_lowered": "#fecaca",     # Red
    }

    # 表頭
    header_cells = '<th style="padding: 12px; background: #f9fafb; border: 1px solid #e5e5e5;"></th>'
    for col in cols:
        header_cells += f'<th style="padding: 12px; background: #f9fafb; border: 1px solid #e5e5e5; font-weight: 600; text-align: center;">{col}</th>'

    # 表格內容
    rows_html = ""
    for row_label, scenario_keys in rows:
        row_html = f'<td style="padding: 12px; background: #f9fafb; border: 1px solid #e5e5e5; font-weight: 600;">{row_label}</td>'
        for key in scenario_keys:
            scenario = scenarios.get(key, {})
            label = scenario.get("label", "")
            description = scenario.get("description", "")
            action = scenario.get("action", "")
            bg = cell_colors.get(key, "#f3f4f6")

            row_html += f'''
            <td style="padding: 12px; background: {bg}; border: 1px solid #e5e5e5; vertical-align: top;">
                <div style="font-weight: 600; margin-bottom: 4px;">{label}</div>
                <div style="font-size: 12px; color: #4b5563; margin-bottom: 4px;">{description}</div>
                <div style="font-size: 11px; color: #6b7280;"><strong>動作:</strong> {action}</div>
            </td>
            '''
        rows_html += f'<tr>{row_html}</tr>'

    title_html = f'<h3 style="margin: 0 0 16px 0; font-size: 18px; font-weight: 600; color: {BASE_STYLES["text_color"]};">{title}</h3>' if title else ""

    return f'''
    <div style="margin: 24px 0; font-family: {BASE_STYLES["font_family"]};">
        {title_html}
        <div style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr>{header_cells}</tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    </div>
    '''


@dataclass
class TimelineItem:
    """時間軸項目"""
    date: str
    event: str
    ticker: Optional[str] = None
    importance: str = "medium"  # "high", "medium", "low"


def render_timeline_block(
    items: list[TimelineItem],
    title: Optional[str] = None,
) -> str:
    """元件 7: TimelineBlock - 時間軸

    用於觀察清單、事件日曆等。

    Args:
        items: 時間軸項目列表
        title: 標題（可選）

    Returns:
        HTML 字串
    """
    importance_colors = {
        "high": BASE_STYLES["danger_color"],
        "medium": BASE_STYLES["accent_color"],
        "low": BASE_STYLES["muted_color"],
    }

    items_html = ""
    for item in items:
        dot_color = importance_colors.get(item.importance, BASE_STYLES["accent_color"])
        ticker_html = f'<span style="margin-left: 8px; padding: 2px 8px; background: #f3f4f6; border-radius: 4px; font-size: 12px; font-weight: 600;">{item.ticker}</span>' if item.ticker else ""

        items_html += f'''
        <div style="display: flex; align-items: flex-start; margin-bottom: 16px;">
            <div style="width: 12px; height: 12px; border-radius: 50%; background: {dot_color}; margin-right: 16px; margin-top: 4px; flex-shrink: 0;"></div>
            <div style="flex: 1;">
                <div style="font-size: 13px; color: {BASE_STYLES["muted_color"]}; margin-bottom: 2px;">{item.date}</div>
                <div style="font-size: 15px; color: {BASE_STYLES["text_color"]};">{item.event}{ticker_html}</div>
            </div>
        </div>
        '''

    title_html = f'<h3 style="margin: 0 0 16px 0; font-size: 18px; font-weight: 600; color: {BASE_STYLES["text_color"]};">{title}</h3>' if title else ""

    return f'''
    <div style="margin: 24px 0; padding: 20px; background: {BASE_STYLES["bg_color"]}; border: 1px solid {BASE_STYLES["border_color"]}; border-radius: 8px; font-family: {BASE_STYLES["font_family"]};">
        {title_html}
        <div style="border-left: 2px solid {BASE_STYLES["border_color"]}; padding-left: 24px; margin-left: 5px;">
            {items_html}
        </div>
    </div>
    '''


@dataclass
class SourceItem:
    """來源項目"""
    name: str
    source_type: str  # "primary", "news", "sec_filing", "data"
    url: Optional[str] = None


def render_source_footer(
    sources: list[SourceItem],
    title: str = "資料來源",
) -> str:
    """元件 8: SourceFooter - 來源頁尾

    用於資料來源引用。

    Args:
        sources: 來源項目列表
        title: 標題

    Returns:
        HTML 字串
    """
    type_labels = {
        "primary": "主要來源",
        "news": "新聞",
        "sec_filing": "SEC 文件",
        "data": "數據",
        "earnings_release": "財報",
        "transcript": "法說逐字稿",
        "10-Q": "10-Q",
        "8-K": "8-K",
    }

    sources_html = ""
    for source in sources:
        type_label = type_labels.get(source.source_type, source.source_type)
        name_html = f'<a href="{source.url}" style="color: {BASE_STYLES["accent_color"]}; text-decoration: none;">{source.name}</a>' if source.url else source.name

        sources_html += f'''
        <li style="margin-bottom: 8px;">
            <span style="font-size: 12px; padding: 2px 6px; background: #f3f4f6; border-radius: 4px; margin-right: 8px;">{type_label}</span>
            {name_html}
        </li>
        '''

    return f'''
    <div style="margin: 32px 0 24px 0; padding-top: 24px; border-top: 1px solid {BASE_STYLES["border_color"]}; font-family: {BASE_STYLES["font_family"]};">
        <h4 style="margin: 0 0 16px 0; font-size: 16px; font-weight: 600; color: {BASE_STYLES["muted_color"]};">{title}</h4>
        <ul style="list-style: none; margin: 0; padding: 0; font-size: 14px; color: {BASE_STYLES["text_color"]};">
            {sources_html}
        </ul>
    </div>
    '''


def render_paywall_divider() -> str:
    """渲染 Paywall 分隔線

    Returns:
        HTML 字串（含 Ghost members-only 標記）
    """
    return '''
    <!--members-only-->
    <div style="margin: 40px 0; padding: 24px; background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%); border-radius: 8px; text-align: center; font-family: system-ui, -apple-system, sans-serif;">
        <div style="font-size: 20px; font-weight: 600; color: #1e40af; margin-bottom: 8px;">🔒 以下為會員專屬內容</div>
        <div style="font-size: 14px; color: #3b82f6;">訂閱即可解鎖完整分析、估值模型、觀察清單</div>
    </div>
    '''


def render_cta_banner(
    headline: str = "想要更多深度分析？",
    subtext: str = "訂閱 Daily Deep Brief，每日獲得專業美股研究",
    button_text: str = "立即訂閱",
    button_link: str = "#subscribe",
) -> str:
    """渲染訂閱 CTA 橫幅

    Args:
        headline: 標題
        subtext: 副標題
        button_text: 按鈕文字
        button_link: 按鈕連結

    Returns:
        HTML 字串
    """
    return f'''
    <div style="margin: 32px 0; padding: 32px; background: linear-gradient(135deg, #1e3a8a 0%, #3730a3 100%); border-radius: 12px; text-align: center; font-family: system-ui, -apple-system, sans-serif;">
        <div style="font-size: 24px; font-weight: 700; color: #ffffff; margin-bottom: 8px;">{headline}</div>
        <div style="font-size: 16px; color: #c7d2fe; margin-bottom: 20px;">{subtext}</div>
        <a href="{button_link}" style="display: inline-block; padding: 12px 32px; background: #ffffff; color: #1e3a8a; font-size: 16px; font-weight: 600; text-decoration: none; border-radius: 8px;">{button_text}</a>
    </div>
    '''


# =============================================================================
# 統一版型元件 (v4.3 Design System)
# =============================================================================

def render_header(
    title: str,
    post_type: str,  # "flash", "earnings", "deep"
    tags: List[str] = None,
    ticker: Optional[str] = None,
) -> str:
    """元件 1: Header - 標題 + tags pills

    Args:
        title: 文章標題
        post_type: 文章類型
        tags: 標籤列表
        ticker: 主要股票代碼

    Returns:
        HTML 字串
    """
    type_styles = {
        "flash": {"bg": "#3b82f6", "label": "Flash"},
        "earnings": {"bg": "#10b981", "label": "Earnings"},
        "deep": {"bg": "#8b5cf6", "label": "Deep Dive"},
    }
    style = type_styles.get(post_type, type_styles["flash"])

    tags_html = ""
    if tags:
        for tag in tags[:5]:  # 最多 5 個標籤
            tags_html += f'<span style="display: inline-block; padding: 4px 10px; margin: 4px; background: #f3f4f6; border-radius: 16px; font-size: 12px; color: {BASE_STYLES["muted_color"]};">{tag}</span>'

    ticker_html = ""
    if ticker:
        ticker_html = f'<span style="display: inline-block; padding: 6px 14px; margin-left: 12px; background: {BASE_STYLES["accent_color"]}; border-radius: 20px; font-size: 14px; font-weight: 700; color: #ffffff;">{ticker}</span>'

    return f'''
    <div style="margin-bottom: 24px; font-family: {BASE_STYLES["font_family"]};">
        <div style="display: flex; align-items: center; margin-bottom: 12px;">
            <span style="display: inline-block; padding: 6px 14px; background: {style["bg"]}; border-radius: 20px; font-size: 13px; font-weight: 600; color: #ffffff; text-transform: uppercase;">{style["label"]}</span>
            {ticker_html}
        </div>
        <h1 style="margin: 0 0 12px 0; font-size: 28px; font-weight: 700; line-height: 1.3; color: {BASE_STYLES["text_color"]};">{title}</h1>
        <div style="display: flex; flex-wrap: wrap; gap: 4px;">
            {tags_html}
        </div>
    </div>
    '''


def render_data_stamp(
    date: str,
    data_as_of: Optional[str] = None,
    timezone: str = "ET",
) -> str:
    """元件 2: DataStamp - 資料時間戳記

    Args:
        date: 發佈日期
        data_as_of: 資料截止時間
        timezone: 時區

    Returns:
        HTML 字串
    """
    data_time_html = f' • 資料截至 {data_as_of} {timezone}' if data_as_of else ""

    return f'''
    <div style="margin: 16px 0 24px 0; padding: 12px 16px; background: #f9fafb; border-radius: 8px; font-family: {BASE_STYLES["font_family"]}; font-size: 13px; color: {BASE_STYLES["muted_color"]};">
        📅 {date}{data_time_html}
    </div>
    '''


@dataclass
class PackageLink:
    """Today's Package 連結"""
    post_type: str  # "flash", "earnings", "deep"
    title: str
    url: str
    is_current: bool = False


def render_todays_package(
    links: List[PackageLink],
    current_type: str = None,
) -> str:
    """元件 3: TodaysPackage - 三篇互鏈

    Args:
        links: 文章連結列表
        current_type: 當前文章類型

    Returns:
        HTML 字串
    """
    type_icons = {
        "flash": "⚡",
        "earnings": "📊",
        "deep": "🔬",
    }
    type_labels = {
        "flash": "Flash",
        "earnings": "Earnings",
        "deep": "Deep Dive",
    }

    links_html = ""
    for link in links:
        icon = type_icons.get(link.post_type, "📄")
        label = type_labels.get(link.post_type, link.post_type)
        is_current = link.post_type == current_type or link.is_current

        if is_current:
            links_html += f'''
            <div style="flex: 1; min-width: 200px; padding: 16px; background: {BASE_STYLES["accent_color"]}; border-radius: 8px; text-align: center;">
                <div style="font-size: 20px; margin-bottom: 4px;">{icon}</div>
                <div style="font-size: 12px; font-weight: 600; color: #ffffff; text-transform: uppercase; margin-bottom: 4px;">{label}</div>
                <div style="font-size: 13px; color: #dbeafe;">（本篇）</div>
            </div>
            '''
        else:
            links_html += f'''
            <a href="{link.url}" style="flex: 1; min-width: 200px; padding: 16px; background: #f9fafb; border: 1px solid {BASE_STYLES["border_color"]}; border-radius: 8px; text-align: center; text-decoration: none;">
                <div style="font-size: 20px; margin-bottom: 4px;">{icon}</div>
                <div style="font-size: 12px; font-weight: 600; color: {BASE_STYLES["muted_color"]}; text-transform: uppercase; margin-bottom: 4px;">{label}</div>
                <div style="font-size: 13px; color: {BASE_STYLES["accent_color"]};">閱讀 →</div>
            </a>
            '''

    return f'''
    <div style="margin: 24px 0; font-family: {BASE_STYLES["font_family"]};">
        <h3 style="margin: 0 0 16px 0; font-size: 16px; font-weight: 600; color: {BASE_STYLES["muted_color"]};">📦 今日包裹</h3>
        <div style="display: flex; flex-wrap: wrap; gap: 12px;">
            {links_html}
        </div>
    </div>
    '''


def render_dual_summary(
    chinese_summary: str,
    english_summary: str,
    date_note: Optional[str] = None,
) -> str:
    """元件 4: DualSummary - 中英雙語摘要

    Args:
        chinese_summary: 中文摘要 (100-150 字)
        english_summary: 英文摘要 (100-150 words)
        date_note: 日期備註（如財報日期）

    Returns:
        HTML 字串
    """
    date_html = f'<div style="font-size: 12px; color: {BASE_STYLES["muted_color"]}; margin-bottom: 16px;">📅 {date_note}</div>' if date_note else ""

    return f'''
    <div style="margin: 24px 0; font-family: {BASE_STYLES["font_family"]};">
        {date_html}
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 24px;">
            <div style="padding: 20px; background: #fafafa; border-radius: 8px; border-left: 4px solid #ef4444;">
                <div style="font-size: 12px; font-weight: 600; color: #ef4444; margin-bottom: 8px; text-transform: uppercase;">中文摘要</div>
                <div style="font-size: 15px; line-height: 1.7; color: {BASE_STYLES["text_color"]};">{chinese_summary}</div>
            </div>
            <div style="padding: 20px; background: #fafafa; border-radius: 8px; border-left: 4px solid #3b82f6;">
                <div style="font-size: 12px; font-weight: 600; color: #3b82f6; margin-bottom: 8px; text-transform: uppercase;">English Summary</div>
                <div style="font-size: 15px; line-height: 1.7; color: {BASE_STYLES["text_color"]};">{english_summary}</div>
            </div>
        </div>
    </div>
    '''


@dataclass
class KeyNumber:
    """關鍵數字"""
    value: str
    label: str
    source: Optional[str] = None
    direction: Optional[str] = None  # "up", "down", "neutral"


def render_key_numbers(
    numbers: List[KeyNumber],
    title: str = "三個必記數字",
) -> str:
    """元件 5: KeyNumbers - 關鍵數字卡片

    Args:
        numbers: 關鍵數字列表（3-5 個）
        title: 區塊標題

    Returns:
        HTML 字串
    """
    direction_icons = {
        "up": "↑",
        "down": "↓",
        "neutral": "→",
    }
    direction_colors = {
        "up": BASE_STYLES["success_color"],
        "down": BASE_STYLES["danger_color"],
        "neutral": BASE_STYLES["muted_color"],
    }

    cards_html = ""
    for num in numbers[:5]:  # 最多 5 個
        icon = direction_icons.get(num.direction, "")
        color = direction_colors.get(num.direction, BASE_STYLES["text_color"])
        source_html = f'<div style="font-size: 11px; color: {BASE_STYLES["muted_color"]}; margin-top: 4px;">來源: {num.source}</div>' if num.source else ""

        cards_html += f'''
        <div style="flex: 1; min-width: 140px; padding: 20px; background: #ffffff; border: 1px solid {BASE_STYLES["border_color"]}; border-radius: 12px; text-align: center;">
            <div style="font-size: 28px; font-weight: 700; color: {color}; margin-bottom: 8px;">{num.value} {icon}</div>
            <div style="font-size: 14px; color: {BASE_STYLES["muted_color"]};">{num.label}</div>
            {source_html}
        </div>
        '''

    return f'''
    <div style="margin: 24px 0; font-family: {BASE_STYLES["font_family"]};">
        <h3 style="margin: 0 0 16px 0; font-size: 18px; font-weight: 600; color: {BASE_STYLES["text_color"]};">🔢 {title}</h3>
        <div style="display: flex; flex-wrap: wrap; gap: 16px;">
            {cards_html}
        </div>
    </div>
    '''


@dataclass
class TLDRItem:
    """TL;DR 項目"""
    ticker: str
    move: str
    reason: str


def render_tldr_bullets(
    items: List[TLDRItem],
    title: str = "TL;DR 摘要",
) -> str:
    """元件 6: TLDRBullets - 6 bullet 摘要

    Args:
        items: TL;DR 項目列表（5-7 個）
        title: 區塊標題

    Returns:
        HTML 字串
    """
    bullets_html = ""
    for item in items[:7]:  # 最多 7 個
        # 判斷漲跌
        move_color = BASE_STYLES["success_color"] if "+" in item.move or "↑" in item.move else (
            BASE_STYLES["danger_color"] if "-" in item.move or "↓" in item.move else BASE_STYLES["text_color"]
        )

        bullets_html += f'''
        <li style="margin-bottom: 12px; padding-left: 8px;">
            <span style="font-weight: 600; color: {BASE_STYLES["accent_color"]};">{item.ticker}</span>
            <span style="margin-left: 8px; font-weight: 600; color: {move_color};">{item.move}</span>
            <span style="margin-left: 8px; color: {BASE_STYLES["text_color"]};">— {item.reason}</span>
        </li>
        '''

    return f'''
    <div style="margin: 24px 0; font-family: {BASE_STYLES["font_family"]};">
        <h3 style="margin: 0 0 16px 0; font-size: 18px; font-weight: 600; color: {BASE_STYLES["text_color"]};">📋 {title}</h3>
        <ul style="margin: 0; padding-left: 20px; list-style-type: disc; font-size: 15px; line-height: 1.6;">
            {bullets_html}
        </ul>
    </div>
    '''


def render_paywall_gate() -> str:
    """元件 7: PaywallGate - 固定文案 + 按鈕 + 分隔線

    Returns:
        HTML 字串（含 Ghost members-only 標記）
    """
    return '''
    <!--members-only-->
    <div style="margin: 48px 0; font-family: system-ui, -apple-system, sans-serif;">
        <div style="height: 1px; background: linear-gradient(to right, transparent, #e5e5e5, transparent);"></div>
        <div style="padding: 32px; background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%); border-radius: 12px; text-align: center; margin-top: 32px;">
            <div style="font-size: 24px; margin-bottom: 12px;">🔒</div>
            <div style="font-size: 20px; font-weight: 700; color: #1e40af; margin-bottom: 8px;">以下為會員專屬內容</div>
            <div style="font-size: 15px; color: #3b82f6; margin-bottom: 20px;">解鎖完整分析、估值模型、觀察清單</div>
            <div style="display: flex; justify-content: center; gap: 16px; flex-wrap: wrap;">
                <a href="#/portal/signup" style="display: inline-block; padding: 12px 28px; background: #1e40af; color: #ffffff; font-size: 15px; font-weight: 600; text-decoration: none; border-radius: 8px;">免費訂閱</a>
                <a href="#/portal/account" style="display: inline-block; padding: 12px 28px; background: #ffffff; border: 1px solid #1e40af; color: #1e40af; font-size: 15px; font-weight: 600; text-decoration: none; border-radius: 8px;">已是會員？登入</a>
            </div>
        </div>
    </div>
    '''


@dataclass
class NewsRadarItem:
    """新聞雷達條目"""
    headline: str
    impact: str  # "+", "-", "mixed"
    chain: str  # 事件 → 產業 → tickers
    watch: str  # 下一個可驗證訊號


def render_news_radar_quick(
    items: List[NewsRadarItem],
    title: str = "新聞雷達快覽",
) -> str:
    """新聞雷達快覽 - 6 條新聞的 4 行模板

    Args:
        items: 新聞項目列表（6 條）
        title: 區塊標題

    Returns:
        HTML 字串
    """
    impact_styles = {
        "+": {"bg": "#dcfce7", "color": "#166534", "icon": "📈"},
        "-": {"bg": "#fee2e2", "color": "#991b1b", "icon": "📉"},
        "mixed": {"bg": "#fef3c7", "color": "#92400e", "icon": "↔️"},
    }

    items_html = ""
    for i, item in enumerate(items[:6], 1):
        style = impact_styles.get(item.impact, impact_styles["mixed"])

        items_html += f'''
        <div style="padding: 16px; background: #ffffff; border: 1px solid {BASE_STYLES["border_color"]}; border-radius: 8px; margin-bottom: 12px;">
            <div style="display: flex; align-items: flex-start; gap: 12px;">
                <div style="width: 28px; height: 28px; background: {style["bg"]}; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; flex-shrink: 0;">{style["icon"]}</div>
                <div style="flex: 1;">
                    <div style="font-size: 15px; font-weight: 500; color: {BASE_STYLES["text_color"]}; margin-bottom: 8px;">{item.headline}</div>
                    <div style="display: flex; flex-wrap: wrap; gap: 8px; font-size: 13px;">
                        <span style="padding: 2px 8px; background: {style["bg"]}; border-radius: 4px; color: {style["color"]};">Impact: {item.impact}</span>
                        <span style="color: {BASE_STYLES["muted_color"]};">📊 {item.chain}</span>
                    </div>
                    <div style="margin-top: 8px; font-size: 13px; color: {BASE_STYLES["muted_color"]};">👀 <strong>Watch:</strong> {item.watch}</div>
                </div>
            </div>
        </div>
        '''

    return f'''
    <div style="margin: 24px 0; font-family: {BASE_STYLES["font_family"]};">
        <h3 style="margin: 0 0 16px 0; font-size: 18px; font-weight: 600; color: {BASE_STYLES["text_color"]};">📡 {title}</h3>
        {items_html}
    </div>
    '''


def render_member_section_header(title: str, reading_time: str = "10-15 min") -> str:
    """元件 8: MemberSection - 會員區塊標題

    Args:
        title: 區塊標題
        reading_time: 預估閱讀時間

    Returns:
        HTML 字串
    """
    return f'''
    <div style="margin: 32px 0 24px 0; font-family: {BASE_STYLES["font_family"]};">
        <div style="display: flex; align-items: center; justify-content: space-between; padding-bottom: 16px; border-bottom: 2px solid {BASE_STYLES["accent_color"]};">
            <h2 style="margin: 0; font-size: 22px; font-weight: 700; color: {BASE_STYLES["text_color"]};">🔓 {title}</h2>
            <span style="font-size: 13px; color: {BASE_STYLES["muted_color"]};">⏱️ {reading_time}</span>
        </div>
    </div>
    '''

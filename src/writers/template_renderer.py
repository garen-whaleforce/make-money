"""Template Renderer - JSON to HTML 渲染器 v4.3

將 LLM 的純 JSON 輸出轉換成 Ghost CMS 相容的 HTML。
這確保：
1. 輸出格式一致性
2. 設計系統元件統一
3. Paywall 位置正確
4. 圖表正確嵌入
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import json

from .html_components import (
    render_header,
    render_data_stamp,
    render_todays_package,
    render_dual_summary,
    render_key_numbers,
    render_tldr_bullets,
    render_paywall_gate,
    render_member_section_header,
    render_news_radar_quick,
    render_data_table,
    render_scenario_matrix,
    render_timeline_block,
    render_source_footer,
    render_ticker_pill,
    render_alert_banner,
    PackageLink,
    KeyNumber,
    TLDRItem,
    NewsRadarItem,
    TimelineItem,
    SourceItem,
)

from .chart_components import (
    render_sector_flow_chart,
    render_valuation_stress_chart,
    render_financial_trend_chart,
    SectorFlowItem,
    ValuationScenario,
    QuarterlyMetric,
)


@dataclass
class RenderedPost:
    """渲染後的文章"""
    html: str
    json_data: Dict[str, Any]
    title: str
    slug: str
    tags: List[str]
    meta: Dict[str, Any]


class FlashRenderer:
    """Flash 文章渲染器"""

    def render(self, data: Dict[str, Any]) -> str:
        """渲染 Flash 文章

        Args:
            data: LLM 輸出的 JSON 資料

        Returns:
            HTML 字串
        """
        html_parts = []

        # 1. Header
        html_parts.append(render_header(
            title=data.get("title", ""),
            post_type="flash",
            tags=data.get("tags", []),
            ticker=data.get("deep_dive_ticker"),
        ))

        # 2. Data Stamp
        html_parts.append(render_data_stamp(
            date=data.get("date", ""),
            data_as_of=data.get("data_as_of"),
        ))

        # 3. Dual Summary
        summary = data.get("summary", {})
        html_parts.append(render_dual_summary(
            chinese_summary=summary.get("chinese", ""),
            english_summary=summary.get("english", ""),
        ))

        # 4. Key Numbers
        key_numbers = []
        for num in data.get("key_numbers", [])[:3]:
            key_numbers.append(KeyNumber(
                value=num.get("value", ""),
                label=num.get("label", ""),
                source=num.get("source"),
                direction=num.get("direction"),
            ))
        if key_numbers:
            html_parts.append(render_key_numbers(key_numbers))

        # 5. News Radar Quick (FREE ZONE)
        radar_items = []
        for item in data.get("news_radar", [])[:6]:
            radar_items.append(NewsRadarItem(
                headline=item.get("headline", ""),
                impact=item.get("impact", "mixed"),
                chain=item.get("chain", ""),
                watch=item.get("watch", ""),
            ))
        if radar_items:
            html_parts.append(render_news_radar_quick(radar_items))

        # 6. TL;DR
        tldr_items = []
        for item in data.get("tldr", []):
            tldr_items.append(TLDRItem(
                ticker=item.get("ticker", ""),
                move=item.get("move", ""),
                reason=item.get("reason", ""),
            ))
        if tldr_items:
            html_parts.append(render_tldr_bullets(tldr_items))

        # === PAYWALL ===
        html_parts.append(render_paywall_gate())

        # 7. Today's Package (MEMBERS ZONE)
        html_parts.append(render_member_section_header("會員專屬分析", "5-7 min"))

        cross_links = data.get("cross_links", {})
        package_links = [
            PackageLink("flash", "Flash", "#", is_current=True),
            PackageLink("earnings", "Earnings", cross_links.get("earnings", "#")),
            PackageLink("deep", "Deep Dive", cross_links.get("deep", "#")),
        ]
        html_parts.append(render_todays_package(package_links, "flash"))

        # 8. Sector Flow Chart
        chart_data = data.get("sector_flow_chart", {})
        if chart_data.get("items"):
            flow_items = []
            for item in chart_data["items"]:
                flow_items.append(SectorFlowItem(
                    ticker=item.get("ticker", ""),
                    name=item.get("name", ""),
                    change_pct=item.get("change_pct", 0),
                    volume_ratio=item.get("volume_ratio", 1),
                    signal=item.get("signal", "neutral"),
                ))
            html_parts.append(render_sector_flow_chart(flow_items))

        # 9. Deep Analysis (Top Event)
        deep_analysis = data.get("deep_analysis", {})
        if deep_analysis:
            html_parts.append(f'''
            <div style="margin: 24px 0; font-family: system-ui, sans-serif;">
                <h3 style="font-size: 20px; font-weight: 700; margin-bottom: 16px;">🔍 主事件深度分析</h3>
                <div style="padding: 20px; background: #f9fafb; border-radius: 12px; line-height: 1.8;">
                    {deep_analysis.get("content", "")}
                </div>
            </div>
            ''')

        # 10. Theme Board
        theme_board = data.get("theme_board", {})
        if theme_board:
            themes_html = self._render_theme_board(theme_board)
            html_parts.append(themes_html)

        # 11. Repricing Dashboard
        repricing = data.get("repricing_dashboard", [])
        if repricing:
            headers = ["變數", "為什麼重要", "領先訊號", "影響標的"]
            rows = [[r.get("variable", ""), r.get("why_important", ""),
                     r.get("leading_signal", ""), r.get("affected", "")] for r in repricing]
            html_parts.append(render_data_table(headers, rows, "📊 重新定價儀表板"))

        # 12. Scenario Playbook
        scenarios = data.get("scenario_playbook", {})
        if scenarios:
            html_parts.append(render_scenario_matrix(scenarios, "📋 情境策略表"))

        # 13. Watchlist
        watchlist = data.get("watchlist", [])
        if watchlist:
            timeline_items = []
            for item in watchlist:
                timeline_items.append(TimelineItem(
                    date=item.get("date", ""),
                    event=item.get("event", ""),
                    ticker=item.get("ticker"),
                    importance=item.get("importance", "medium"),
                ))
            html_parts.append(render_timeline_block(timeline_items, "📅 兩週觀察清單"))

        # 14. Sources
        sources = data.get("sources", [])
        if sources:
            source_items = []
            for s in sources:
                source_items.append(SourceItem(
                    name=s.get("name", ""),
                    source_type=s.get("type", "news"),
                    url=s.get("url"),
                ))
            html_parts.append(render_source_footer(source_items))

        return "\n".join(html_parts)

    def _render_theme_board(self, theme_board: Dict) -> str:
        """渲染 Theme Board"""
        themes_html = ""
        theme_colors = {
            "bullish": "#10b981",
            "bearish": "#ef4444",
            "neutral": "#6b7280",
            "watching": "#f59e0b",
        }

        for theme_id, theme_data in theme_board.items():
            status = theme_data.get("status", "neutral")
            color = theme_colors.get(status, "#6b7280")
            tickers = ", ".join(theme_data.get("tickers", [])[:4])

            themes_html += f'''
            <div style="display: flex; align-items: center; padding: 12px; border-bottom: 1px solid #e5e5e5;">
                <div style="width: 8px; height: 8px; background: {color}; border-radius: 50%; margin-right: 12px;"></div>
                <div style="flex: 1;">
                    <div style="font-weight: 600;">{theme_data.get("name", theme_id)}</div>
                    <div style="font-size: 12px; color: #6b7280;">{tickers}</div>
                </div>
                <div style="font-size: 12px; padding: 4px 8px; background: #f3f4f6; border-radius: 4px;">{status}</div>
            </div>
            '''

        return f'''
        <div style="margin: 24px 0; font-family: system-ui, sans-serif;">
            <h3 style="font-size: 18px; font-weight: 600; margin-bottom: 16px;">🎯 Theme Board</h3>
            <div style="background: #ffffff; border: 1px solid #e5e5e5; border-radius: 8px; overflow: hidden;">
                {themes_html}
            </div>
        </div>
        '''


class EarningsRenderer:
    """Earnings 文章渲染器"""

    def render(self, data: Dict[str, Any]) -> str:
        """渲染 Earnings 文章"""
        html_parts = []

        # 1. Header
        html_parts.append(render_header(
            title=data.get("title", ""),
            post_type="earnings",
            tags=data.get("tags", []),
            ticker=data.get("ticker"),
        ))

        # 2. Data Stamp with earnings date
        earnings_date = data.get("earnings_date", "")
        html_parts.append(render_data_stamp(
            date=data.get("date", ""),
            data_as_of=f"財報日期: {earnings_date}" if earnings_date else None,
        ))

        # 3. Dual Summary
        summary = data.get("summary", {})
        html_parts.append(render_dual_summary(
            chinese_summary=summary.get("chinese", ""),
            english_summary=summary.get("english", ""),
            date_note=f"分析基於 {earnings_date} 發布的財報" if earnings_date else None,
        ))

        # 4. Earnings Scoreboard
        scoreboard = data.get("earnings_scoreboard", [])
        if scoreboard:
            headers = ["Quarter", "EPS Actual", "EPS Est", "vs Est", "Revenue", "Reaction"]
            rows = [[s.get("quarter", ""), s.get("eps_actual", ""), s.get("eps_est", ""),
                     s.get("vs_est", ""), s.get("revenue", ""), s.get("reaction", "")] for s in scoreboard]
            html_parts.append(render_data_table(headers, rows, "📊 財報記分板", highlight_first_col=True))

        # 5. Key Numbers
        key_numbers = []
        for num in data.get("key_numbers", [])[:3]:
            key_numbers.append(KeyNumber(
                value=num.get("value", ""),
                label=num.get("label", ""),
                direction=num.get("direction"),
            ))
        if key_numbers:
            html_parts.append(render_key_numbers(key_numbers))

        # === PAYWALL ===
        html_parts.append(render_paywall_gate())

        # 6. Today's Package
        html_parts.append(render_member_section_header("會員專屬分析", "10-15 min"))

        cross_links = data.get("cross_links", {})
        package_links = [
            PackageLink("flash", "Flash", cross_links.get("flash", "#")),
            PackageLink("earnings", "Earnings", "#", is_current=True),
            PackageLink("deep", "Deep Dive", cross_links.get("deep", "#")),
        ]
        html_parts.append(render_todays_package(package_links, "earnings"))

        # 7. Valuation Stress Test Chart
        valuation = data.get("valuation_stress_test", {})
        if valuation.get("scenarios"):
            scenarios = []
            for s in valuation["scenarios"]:
                scenarios.append(ValuationScenario(
                    label=s.get("label", ""),
                    target_price=s.get("target_price", 0),
                    multiple=s.get("multiple", 0),
                    rationale=s.get("rationale", ""),
                ))
            html_parts.append(render_valuation_stress_chart(
                current_price=valuation.get("current_price", 0),
                scenarios=scenarios,
                ticker=data.get("ticker", ""),
            ))

        # 8. 3x3 Matrix
        matrix = data.get("eps_guidance_matrix", {})
        if matrix:
            html_parts.append(render_scenario_matrix(matrix, "📋 法說後劇本矩陣（EPS × Guidance）"))

        # 9. Peer Comparison
        peers = data.get("peer_comparison", [])
        if peers:
            headers = ["Ticker", "Price", "P/E TTM", "P/E Fwd", "EV/S", "GM%"]
            rows = [[p.get("ticker", ""), p.get("price", ""), p.get("pe_ttm", ""),
                     p.get("pe_fwd", ""), p.get("ev_s", ""), p.get("gm", "")] for p in peers]
            html_parts.append(render_data_table(headers, rows, "📊 同業比較", highlight_first_col=True))

        # 10. Sources
        sources = data.get("sources", [])
        if sources:
            source_items = [SourceItem(s.get("name", ""), s.get("type", "data"), s.get("url")) for s in sources]
            html_parts.append(render_source_footer(source_items))

        return "\n".join(html_parts)


class DeepDiveRenderer:
    """Deep Dive 文章渲染器"""

    def render(self, data: Dict[str, Any]) -> str:
        """渲染 Deep Dive 文章"""
        html_parts = []

        # 1. Header
        html_parts.append(render_header(
            title=data.get("title", ""),
            post_type="deep",
            tags=data.get("tags", []),
            ticker=data.get("ticker"),
        ))

        # 2. Data Stamp
        html_parts.append(render_data_stamp(
            date=data.get("date", ""),
            data_as_of=data.get("data_as_of"),
        ))

        # 3. Reading Guide
        html_parts.append(self._render_reading_guide())

        # 4. Dual Summary
        summary = data.get("summary", {})
        html_parts.append(render_dual_summary(
            chinese_summary=summary.get("chinese", ""),
            english_summary=summary.get("english", ""),
        ))

        # 5. Company Profile Card
        profile = data.get("company_profile", {})
        if profile:
            html_parts.append(self._render_company_card(profile))

        # 6. Key Numbers (5 個)
        key_numbers = []
        for num in data.get("key_numbers", [])[:5]:
            key_numbers.append(KeyNumber(
                value=num.get("value", ""),
                label=num.get("label", ""),
                direction=num.get("direction"),
            ))
        if key_numbers:
            html_parts.append(render_key_numbers(key_numbers, title="五個必記數字"))

        # 7. Bull vs Bear
        bull_bear = data.get("bull_bear", {})
        if bull_bear:
            html_parts.append(self._render_bull_bear(bull_bear))

        # === PAYWALL ===
        html_parts.append(render_paywall_gate())

        # 8. Today's Package
        html_parts.append(render_member_section_header("會員專屬深度分析", "15-30 min"))

        cross_links = data.get("cross_links", {})
        package_links = [
            PackageLink("flash", "Flash", cross_links.get("flash", "#")),
            PackageLink("earnings", "Earnings", cross_links.get("earnings", "#")),
            PackageLink("deep", "Deep Dive", "#", is_current=True),
        ]
        html_parts.append(render_todays_package(package_links, "deep"))

        # 9. Financial Trend Chart
        financials = data.get("financial_trend", {})
        if financials.get("quarters"):
            quarters = []
            for q in financials["quarters"]:
                quarters.append(QuarterlyMetric(
                    quarter=q.get("quarter", ""),
                    revenue=q.get("revenue", 0),
                    gross_margin=q.get("gross_margin"),
                    operating_margin=q.get("operating_margin"),
                    revenue_growth=q.get("revenue_growth"),
                ))
            html_parts.append(render_financial_trend_chart(
                quarters=quarters,
                ticker=data.get("ticker", ""),
            ))

        # 10. Business Model
        biz_model = data.get("business_model", "")
        if biz_model:
            html_parts.append(f'''
            <div style="margin: 24px 0;">
                <h3 style="font-size: 18px; font-weight: 600; margin-bottom: 16px;">🏢 商業模式概覽</h3>
                <div style="padding: 20px; background: #f9fafb; border-radius: 12px; line-height: 1.8;">
                    {biz_model}
                </div>
            </div>
            ''')

        # 11. Moat Analysis
        moat = data.get("moat_analysis", {})
        if moat:
            html_parts.append(self._render_moat_analysis(moat))

        # 12. Valuation Scenarios
        valuation = data.get("valuation_scenarios", {})
        if valuation.get("scenarios"):
            scenarios = []
            for s in valuation["scenarios"]:
                scenarios.append(ValuationScenario(
                    label=s.get("label", ""),
                    target_price=s.get("target_price", 0),
                    multiple=s.get("multiple", 0),
                    rationale=s.get("rationale", ""),
                ))
            html_parts.append(render_valuation_stress_chart(
                current_price=valuation.get("current_price", 0),
                scenarios=scenarios,
                ticker=data.get("ticker", ""),
                title="估值情境分析",
            ))

        # 13. Decision Tree
        decision_tree = data.get("decision_tree", [])
        if decision_tree:
            headers = ["訊號", "解讀", "動作", "風險控制", "下次檢查"]
            rows = [[d.get("signal", ""), d.get("interpretation", ""), d.get("action", ""),
                     d.get("risk_control", ""), d.get("next_check", "")] for d in decision_tree]
            html_parts.append(render_data_table(headers, rows, "🌳 If/Then 決策樹"))

        # 14. Risks
        risks = data.get("risks", [])
        if risks:
            headers = ["風險", "類別", "嚴重度", "機率", "監控訊號"]
            rows = [[r.get("risk", ""), r.get("category", ""), r.get("severity", ""),
                     r.get("probability", ""), r.get("signal", "")] for r in risks]
            html_parts.append(render_data_table(headers, rows, "⚠️ 風險評估"))

        # 15. Sources
        sources = data.get("sources", [])
        if sources:
            source_items = [SourceItem(s.get("name", ""), s.get("type", "data"), s.get("url")) for s in sources]
            html_parts.append(render_source_footer(source_items))

        return "\n".join(html_parts)

    def _render_reading_guide(self) -> str:
        """渲染閱讀指南"""
        return '''
        <div style="margin: 24px 0; padding: 20px; background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%); border-radius: 12px; font-family: system-ui, sans-serif;">
            <h3 style="margin: 0 0 12px 0; font-size: 16px; font-weight: 600; color: #1e40af;">📖 怎麼讀這份 Deep Dive</h3>
            <div style="display: flex; gap: 16px; flex-wrap: wrap; font-size: 14px;">
                <div style="flex: 1; min-width: 150px;">
                    <strong style="color: #3b82f6;">3 分鐘</strong>
                    <div style="color: #6b7280;">關鍵數字 + 多空對決 + 估值快覽</div>
                </div>
                <div style="flex: 1; min-width: 150px;">
                    <strong style="color: #3b82f6;">15 分鐘</strong>
                    <div style="color: #6b7280;">財務引擎 + 競爭矩陣 + 決策樹</div>
                </div>
                <div style="flex: 1; min-width: 150px;">
                    <strong style="color: #3b82f6;">完整版</strong>
                    <div style="color: #6b7280;">護城河 + 敏感度 + 監控儀表板</div>
                </div>
            </div>
        </div>
        '''

    def _render_company_card(self, profile: Dict) -> str:
        """渲染公司概覽卡片"""
        return f'''
        <div style="margin: 24px 0; padding: 24px; background: #ffffff; border: 1px solid #e5e5e5; border-radius: 12px; font-family: system-ui, sans-serif;">
            <div style="display: flex; align-items: center; margin-bottom: 16px;">
                <div style="font-size: 24px; font-weight: 700; color: #3b82f6; margin-right: 12px;">{profile.get("ticker", "")}</div>
                <div style="font-size: 18px; color: #1a1a1a;">{profile.get("name", "")}</div>
            </div>
            <div style="display: flex; flex-wrap: wrap; gap: 24px;">
                <div>
                    <div style="font-size: 12px; color: #6b7280;">股價</div>
                    <div style="font-size: 18px; font-weight: 600;">${profile.get("price", "N/A")}</div>
                </div>
                <div>
                    <div style="font-size: 12px; color: #6b7280;">漲跌</div>
                    <div style="font-size: 18px; font-weight: 600; color: {"#10b981" if profile.get("change_pct", 0) >= 0 else "#ef4444"};">{profile.get("change_pct", 0):+.1f}%</div>
                </div>
                <div>
                    <div style="font-size: 12px; color: #6b7280;">市值</div>
                    <div style="font-size: 18px; font-weight: 600;">{profile.get("market_cap", "N/A")}</div>
                </div>
                <div>
                    <div style="font-size: 12px; color: #6b7280;">P/E TTM</div>
                    <div style="font-size: 18px; font-weight: 600;">{profile.get("pe_ttm", "N/A")}</div>
                </div>
                <div>
                    <div style="font-size: 12px; color: #6b7280;">毛利率</div>
                    <div style="font-size: 18px; font-weight: 600;">{profile.get("gross_margin", "N/A")}</div>
                </div>
            </div>
        </div>
        '''

    def _render_bull_bear(self, bull_bear: Dict) -> str:
        """渲染多空對決"""
        bull = bull_bear.get("bull", {})
        bear = bull_bear.get("bear", {})

        bull_points = "".join([f'<li style="margin-bottom: 8px;">{p}</li>' for p in bull.get("points", [])])
        bear_points = "".join([f'<li style="margin-bottom: 8px;">{p}</li>' for p in bear.get("points", [])])

        return f'''
        <div style="margin: 24px 0; font-family: system-ui, sans-serif;">
            <h3 style="font-size: 18px; font-weight: 600; margin-bottom: 16px;">⚔️ 多空對決</h3>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
                <div style="padding: 20px; background: #dcfce7; border-radius: 12px; border-left: 4px solid #10b981;">
                    <div style="font-size: 16px; font-weight: 700; color: #166534; margin-bottom: 12px;">🐂 Bull Case</div>
                    <div style="font-size: 14px; color: #166534; margin-bottom: 8px;">{bull.get("thesis", "")}</div>
                    <ul style="margin: 0; padding-left: 20px; font-size: 14px; color: #166534;">
                        {bull_points}
                    </ul>
                </div>
                <div style="padding: 20px; background: #fee2e2; border-radius: 12px; border-left: 4px solid #ef4444;">
                    <div style="font-size: 16px; font-weight: 700; color: #991b1b; margin-bottom: 12px;">🐻 Bear Case</div>
                    <div style="font-size: 14px; color: #991b1b; margin-bottom: 8px;">{bear.get("thesis", "")}</div>
                    <ul style="margin: 0; padding-left: 20px; font-size: 14px; color: #991b1b;">
                        {bear_points}
                    </ul>
                </div>
            </div>
        </div>
        '''

    def _render_moat_analysis(self, moat: Dict) -> str:
        """渲染護城河分析"""
        moat_types = moat.get("types", [])
        types_html = "".join([
            f'<span style="display: inline-block; padding: 6px 12px; margin: 4px; background: #dbeafe; border-radius: 16px; font-size: 13px; color: #1e40af;">{t}</span>'
            for t in moat_types
        ])

        durability_colors = {
            "high": "#10b981",
            "medium": "#f59e0b",
            "low": "#ef4444",
        }
        durability = moat.get("durability", "medium")
        durability_color = durability_colors.get(durability, "#6b7280")

        return f'''
        <div style="margin: 24px 0; font-family: system-ui, sans-serif;">
            <h3 style="font-size: 18px; font-weight: 600; margin-bottom: 16px;">🏰 護城河分析</h3>
            <div style="padding: 20px; background: #f9fafb; border-radius: 12px;">
                <div style="margin-bottom: 16px;">
                    <span style="font-size: 14px; color: #6b7280; margin-right: 12px;">護城河類型:</span>
                    {types_html}
                </div>
                <div style="margin-bottom: 16px;">
                    <span style="font-size: 14px; color: #6b7280; margin-right: 12px;">持久度:</span>
                    <span style="padding: 4px 12px; background: {durability_color}; color: #ffffff; border-radius: 4px; font-size: 13px; font-weight: 600;">{durability.upper()}</span>
                </div>
                <div style="font-size: 15px; line-height: 1.7; color: #1a1a1a;">
                    {moat.get("description", "")}
                </div>
            </div>
        </div>
        '''


# =============================================================================
# 主渲染函式
# =============================================================================

def render_post(post_type: str, data: Dict[str, Any]) -> RenderedPost:
    """渲染文章

    Args:
        post_type: 文章類型 ("flash", "earnings", "deep")
        data: LLM 輸出的 JSON 資料

    Returns:
        RenderedPost 物件
    """
    renderers = {
        "flash": FlashRenderer(),
        "earnings": EarningsRenderer(),
        "deep": DeepDiveRenderer(),
    }

    renderer = renderers.get(post_type)
    if not renderer:
        raise ValueError(f"Unknown post type: {post_type}")

    html = renderer.render(data)

    return RenderedPost(
        html=html,
        json_data=data,
        title=data.get("title", ""),
        slug=data.get("slug", ""),
        tags=data.get("tags", []),
        meta=data.get("meta", {}),
    )

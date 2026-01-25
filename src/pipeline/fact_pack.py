"""Fact Pack Generator - P1-1

建立「事實包」(Fact Pack)，作為所有可驗證數據的唯一來源。
LLM 只能引用 fact_pack 中的數據，不能自行推算或編造。

設計原則：
1. 所有數字都有明確來源和時間戳
2. YoY 等衍生數據在這裡預先計算好
3. 如果數據不存在，欄位為 null，而非讓 LLM 猜測
4. P0-1: 同時提供 raw + formatted（*_fmt）欄位
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from ..utils.logging import get_logger

logger = get_logger(__name__)


def format_number(value: Optional[float], unit: str = "") -> Optional[str]:
    """格式化數字為可讀字串"""
    if value is None:
        return None

    abs_val = abs(value)
    if abs_val >= 1e12:
        formatted = f"${value/1e12:.2f}T"
    elif abs_val >= 1e9:
        formatted = f"${value/1e9:.1f}B"
    elif abs_val >= 1e6:
        formatted = f"${value/1e6:.1f}M"
    else:
        formatted = f"${value:,.0f}"

    return formatted


def format_percent(value: Optional[float], with_sign: bool = True) -> Optional[str]:
    """格式化百分比"""
    if value is None:
        return None
    prefix = "+" if with_sign and value >= 0 else ""
    return f"{prefix}{value:.2f}%"


def format_margin(value: Optional[float]) -> Optional[str]:
    """格式化 margin（0.70 -> 70.0%）"""
    if value is None:
        return None
    # 如果是小數形式（0.70），轉換為百分比
    if isinstance(value, (int, float)) and -1 <= value <= 1:
        return f"{value * 100:.1f}%"
    return f"{value:.1f}%"


def parse_percent_string(value: Union[str, float, None]) -> Optional[float]:
    """P0-1: 解析字串百分比為數值（兼容舊 schema）

    Examples:
        "+0.42%" -> 0.42
        "-1.23%" -> -1.23
        "4.18%" -> 4.18
        0.42 -> 0.42 (pass through)
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Remove % and convert
        match = re.match(r"([+-]?\d+\.?\d*)\s*%?", value.strip())
        if match:
            return float(match.group(1))
    return None


def build_fact_pack(edition_pack: dict, run_date: str) -> dict:
    """從 edition_pack 建立 fact_pack

    P0-1: 正確處理新舊 schema + peer_table dict + raw/fmt 雙軌

    Args:
        edition_pack: 完整的 edition pack 資料
        run_date: 發布日期 (YYYY-MM-DD)

    Returns:
        fact_pack dict
    """
    now = datetime.utcnow().isoformat()

    fact_pack = {
        "meta": {
            "date": run_date,
            "generated_at": now,
            "data_sources": ["FMP", "Google News RSS"],
            "version": "1.1",  # P0-1 升版
            "notice": "LLM MUST ONLY cite data from this fact_pack. DO NOT calculate or infer numbers. Use *_fmt fields for display."
        },
        "market_snapshot": {},
        "tickers": {},
        "earnings": {},
        "peer_table": {},
        "analyst_actions": []
    }

    # ========== 1. Market Snapshot ==========
    # P0-1: 兼容新舊 schema
    market_snapshot = edition_pack.get("meta", {}).get("market_snapshot", {})
    if market_snapshot:
        as_of = market_snapshot.get("as_of") or f"{run_date} close"

        # P0-1: 嘗試新 schema（數值型），否則 fallback 到舊 schema（字串型）
        spy_change_pct = market_snapshot.get("spy_change_pct")
        if spy_change_pct is None:
            spy_change_pct = parse_percent_string(market_snapshot.get("spy_change"))

        qqq_change_pct = market_snapshot.get("qqq_change_pct")
        if qqq_change_pct is None:
            qqq_change_pct = parse_percent_string(market_snapshot.get("qqq_change"))

        us10y = market_snapshot.get("us10y")
        if isinstance(us10y, str):
            us10y = parse_percent_string(us10y)

        dxy = market_snapshot.get("dxy")
        if isinstance(dxy, str):
            try:
                dxy = float(dxy)
            except (ValueError, TypeError):
                dxy = None

        vix = market_snapshot.get("vix")
        if isinstance(vix, str):
            try:
                vix = float(vix)
            except (ValueError, TypeError):
                vix = None

        fact_pack["market_snapshot"] = {
            "as_of": as_of,
            "spy": {
                "price": market_snapshot.get("spy_price"),
                "change_pct": spy_change_pct,
                "change_pct_fmt": format_percent(spy_change_pct) if spy_change_pct is not None else None,
            },
            "qqq": {
                "price": market_snapshot.get("qqq_price"),
                "change_pct": qqq_change_pct,
                "change_pct_fmt": format_percent(qqq_change_pct) if qqq_change_pct is not None else None,
            },
            "us10y": {
                "value": us10y,
                "value_fmt": f"{us10y:.2f}%" if us10y is not None else None,
            },
            "dxy": {
                "value": dxy,
                "value_fmt": f"{dxy:.2f}" if dxy is not None else None,
            },
            "vix": {
                "value": vix,
                "value_fmt": f"{vix:.2f}" if vix is not None else None,
            }
        }

    # ========== 2. Ticker Data ==========
    # P0-1: 加入 raw + formatted 雙軌
    market_data = edition_pack.get("market_data", {})
    for ticker, data in market_data.items():
        if not data:
            continue

        price = data.get("price")
        change_pct = data.get("change_pct")
        market_cap = data.get("market_cap")
        gross_margin = data.get("gross_margin")
        operating_margin = data.get("operating_margin")
        net_margin = data.get("net_margin")

        fact_pack["tickers"][ticker] = {
            "ticker": ticker,
            "company_name": data.get("company_name", ticker),
            "price": {
                "value": price,
                "value_fmt": f"${price:.2f}" if price else None,
                "change_pct": change_pct,
                "change_pct_fmt": format_percent(change_pct) if change_pct is not None else None,
                "change_dollars": data.get("change"),
                "as_of": f"{run_date} close"
            },
            "market_cap": {
                "value": market_cap,
                "value_fmt": format_number(market_cap) if market_cap else None,
                "as_of": f"{run_date}"
            } if market_cap else None,
            "valuation": {
                "pe_ttm": data.get("pe"),
                "pe_forward": data.get("pe_forward"),
                "ps_ttm": data.get("ps"),
                "ev_sales": data.get("ev_sales"),
                "as_of": f"{run_date}"
            },
            "financials_ttm": {
                "revenue": data.get("revenue_ttm"),
                "revenue_fmt": format_number(data.get("revenue_ttm")),
                "eps": data.get("eps_ttm"),
                "eps_fmt": f"${data.get('eps_ttm'):.2f}" if data.get("eps_ttm") else None,
                "gross_margin": gross_margin,
                "gross_margin_fmt": format_margin(gross_margin),
                "operating_margin": operating_margin,
                "operating_margin_fmt": format_margin(operating_margin),
                "net_margin": net_margin,
                "net_margin_fmt": format_margin(net_margin),
                "as_of": "TTM"
            } if data.get("revenue_ttm") else None
        }

    # ========== 3. Earnings Data ==========
    recent_earnings = edition_pack.get("recent_earnings", {})
    if recent_earnings:
        ticker = recent_earnings.get("ticker", "")

        # 從 history 中取得 YoY 數據
        history = recent_earnings.get("history", [])
        current_q = history[0] if history else recent_earnings

        # 組裝季度字串
        fiscal_period = current_q.get("fiscal_period", "")
        fiscal_year = current_q.get("fiscal_year", "")
        fiscal_period_str = f"{fiscal_period} FY{str(fiscal_year)[-2:]}" if fiscal_year else fiscal_period

        # Revenue
        revenue = current_q.get("revenue_actual")
        revenue_yoy = current_q.get("revenue_yoy_percent")

        # EPS
        eps = current_q.get("eps_actual") or current_q.get("eps_diluted")
        eps_yoy = current_q.get("eps_yoy_percent")

        # Margins
        gross_margin = current_q.get("gross_margin")
        operating_margin = current_q.get("operating_margin")
        net_margin = current_q.get("net_margin")

        fact_pack["earnings"][ticker] = {
            "ticker": ticker,
            "fiscal_period": fiscal_period_str,
            "fiscal_period_end": current_q.get("date"),
            "announcement_date": current_q.get("announcement_date"),
            "revenue": {
                "value": revenue,
                "formatted": format_number(revenue) if revenue else None,
                "yoy_pct": revenue_yoy,
                "qoq_pct": None  # 可以之後計算
            },
            "eps": {
                "value": eps,
                "yoy_pct": eps_yoy,
                "beat_miss_pct": None  # 需要估計值才能計算
            },
            "margins": {
                "gross_pct": gross_margin,
                "operating_pct": operating_margin,
                "net_pct": net_margin
            },
            "source": {
                "name": f"{ticker} {fiscal_period_str} Earnings",
                "url": None  # 可以加入 SEC filing URL
            }
        }

        # 加入歷史季度（用於比較）
        if len(history) > 1:
            fact_pack["earnings"][f"{ticker}_history"] = [
                {
                    "fiscal_period": f"{q.get('fiscal_period', '')} FY{str(q.get('fiscal_year', ''))[-2:] if q.get('fiscal_year') else ''}",
                    "revenue": q.get("revenue_actual"),
                    "revenue_yoy_pct": q.get("revenue_yoy_percent"),
                    "eps": q.get("eps_actual") or q.get("eps_diluted"),
                    "eps_yoy_pct": q.get("eps_yoy_percent"),
                    "gross_margin_pct": q.get("gross_margin"),
                    "date": q.get("date")
                }
                for q in history[:4]
            ]

    # ========== 4. Deep Dive Data ==========
    deep_dive_data = edition_pack.get("deep_dive_data", {})
    if deep_dive_data:
        ticker = edition_pack.get("deep_dive_ticker", "")
        if ticker and ticker in fact_pack["tickers"]:
            # 補充 deep dive 特有的資料
            company = deep_dive_data.get("company", {})
            if company:
                fact_pack["tickers"][ticker]["company_name"] = company.get("name", ticker)
                fact_pack["tickers"][ticker]["sector"] = company.get("sector")
                fact_pack["tickers"][ticker]["industry"] = company.get("industry")

    # ========== 5. Peer Comparison ==========
    # P0-1: 正確處理 peer_table dict（headers/rows）或 list
    peer_table_raw = edition_pack.get("peer_table", [])

    # 判斷是 dict (新格式) 還是 list (舊格式)
    if isinstance(peer_table_raw, dict):
        # 新格式：{headers: [...], rows: [...], markdown: "...", takeaways: [...]}
        peer_rows = peer_table_raw.get("rows", [])
        fact_pack["peer_table"] = {
            "headers": peer_table_raw.get("headers", []),
            "rows": [],
            "takeaways": peer_table_raw.get("takeaways", [])
        }
    else:
        # 舊格式：直接是 list
        peer_rows = peer_table_raw
        fact_pack["peer_table"] = {"headers": [], "rows": [], "takeaways": []}

    for peer in peer_rows:
        ticker = peer.get("ticker", "")
        if not ticker:
            continue

        # 提取數據並格式化
        price = peer.get("price")
        change_pct = peer.get("change_pct")
        market_cap = peer.get("market_cap")
        gross_margin = peer.get("gross_margin")
        operating_margin = peer.get("operating_margin")
        net_margin = peer.get("net_margin")
        revenue_ttm = peer.get("revenue_ttm")

        peer_data = {
            "ticker": ticker,
            "name": peer.get("name", ticker),
            "price": price,
            "price_fmt": f"${price:.2f}" if price else None,
            "change_pct": change_pct,
            "change_pct_fmt": format_percent(change_pct) if change_pct is not None else None,
            "market_cap": market_cap,
            "market_cap_fmt": format_number(market_cap),
            "revenue_ttm": revenue_ttm,
            "revenue_ttm_fmt": format_number(revenue_ttm),
            "gross_margin": gross_margin,
            "gross_margin_fmt": format_margin(gross_margin),
            "operating_margin": operating_margin,
            "operating_margin_fmt": format_margin(operating_margin),
            "net_margin": net_margin,
            "net_margin_fmt": format_margin(net_margin),
            "pe_ttm": peer.get("pe_ttm") or peer.get("forward_pe"),
            "pe_forward": peer.get("pe_fwd") or peer.get("forward_pe"),
            "ps_ttm": peer.get("ps_ttm") or peer.get("forward_ps"),
        }

        fact_pack["peer_table"]["rows"].append(peer_data)

        # 同時補充到 tickers（如果不存在）
        if ticker not in fact_pack["tickers"]:
            fact_pack["tickers"][ticker] = {
                "ticker": ticker,
                "company_name": peer.get("name", ticker),
                "price": {
                    "value": price,
                    "value_fmt": f"${price:.2f}" if price else None,
                    "change_pct": change_pct,
                    "change_pct_fmt": format_percent(change_pct) if change_pct is not None else None,
                    "as_of": f"{run_date} close"
                },
                "market_cap": {
                    "value": market_cap,
                    "value_fmt": format_number(market_cap),
                    "as_of": run_date
                } if market_cap else None,
                "valuation": {
                    "pe_ttm": peer.get("pe_ttm") or peer.get("forward_pe"),
                    "pe_forward": peer.get("pe_fwd") or peer.get("forward_pe"),
                    "ps_ttm": peer.get("ps_ttm") or peer.get("forward_ps"),
                    "as_of": run_date
                },
                "financials_ttm": {
                    "revenue": revenue_ttm,
                    "revenue_fmt": format_number(revenue_ttm),
                    "gross_margin": gross_margin,
                    "gross_margin_fmt": format_margin(gross_margin),
                    "operating_margin": operating_margin,
                    "operating_margin_fmt": format_margin(operating_margin),
                    "net_margin": net_margin,
                    "net_margin_fmt": format_margin(net_margin),
                    "as_of": "TTM"
                } if revenue_ttm else None
            }

    return fact_pack


def save_fact_pack(fact_pack: dict, output_path: str = "out/fact_pack.json") -> Path:
    """儲存 fact_pack 到檔案"""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(fact_pack, f, indent=2, ensure_ascii=False)

    logger.info(f"Saved fact_pack to {path}")
    return path


def load_fact_pack(input_path: str = "out/fact_pack.json") -> Optional[dict]:
    """載入 fact_pack"""
    path = Path(input_path)
    if not path.exists():
        return None

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# =============================================================================
# P0-3: Completeness Gate
# =============================================================================

def validate_fact_pack_completeness(
    fact_pack: dict,
    deep_dive_ticker: Optional[str] = None,
    require_earnings: bool = False,
) -> dict:
    """P0-3: 驗證 fact_pack 完整性

    檢查項目：
    1. deep_dive_ticker 必須有完整的價格和財務數據
    2. 如果需要 earnings，必須有 YoY 計算
    3. 關鍵欄位不能是 null

    Args:
        fact_pack: fact_pack dict
        deep_dive_ticker: 主要分析的 ticker
        require_earnings: 是否需要 earnings 數據

    Returns:
        {passed: bool, errors: [], warnings: [], details: {}}
    """
    errors = []
    warnings = []
    details = {
        "tickers_count": len(fact_pack.get("tickers", {})),
        "earnings_count": len(fact_pack.get("earnings", {})),
        "peer_table_rows": len(fact_pack.get("peer_table", {}).get("rows", [])),
    }

    # 1. 檢查 deep_dive_ticker 是否有完整數據
    if deep_dive_ticker:
        ticker_data = fact_pack.get("tickers", {}).get(deep_dive_ticker)
        if not ticker_data:
            errors.append(f"Deep dive ticker {deep_dive_ticker} not found in fact_pack")
        else:
            # 必須有價格
            price = ticker_data.get("price", {})
            if not price or price.get("value") is None:
                errors.append(f"{deep_dive_ticker}: missing price data")

            # 必須有市值
            market_cap = ticker_data.get("market_cap", {})
            if not market_cap or market_cap.get("value") is None:
                warnings.append(f"{deep_dive_ticker}: missing market_cap")

            # 應該有估值數據
            valuation = ticker_data.get("valuation", {})
            if not valuation or valuation.get("pe_ttm") is None:
                warnings.append(f"{deep_dive_ticker}: missing PE ratio")

    # 2. 檢查 earnings 完整性（如果需要）
    if require_earnings and deep_dive_ticker:
        earnings = fact_pack.get("earnings", {}).get(deep_dive_ticker)
        if not earnings:
            errors.append(f"Earnings data required but not found for {deep_dive_ticker}")
        else:
            # 必須有 revenue
            revenue = earnings.get("revenue", {})
            if not revenue or revenue.get("value") is None:
                errors.append(f"{deep_dive_ticker} earnings: missing revenue")

            # 必須有 YoY 計算
            if revenue.get("yoy_pct") is None:
                warnings.append(f"{deep_dive_ticker} earnings: missing revenue YoY")

            # 必須有 EPS
            eps = earnings.get("eps", {})
            if not eps or eps.get("value") is None:
                warnings.append(f"{deep_dive_ticker} earnings: missing EPS")

            # fiscal_period 不能是空的
            if not earnings.get("fiscal_period"):
                errors.append(f"{deep_dive_ticker} earnings: missing fiscal_period")

    # 3. 檢查 market_snapshot 完整性
    market_snapshot = fact_pack.get("market_snapshot", {})
    if not market_snapshot:
        warnings.append("market_snapshot is empty")
    else:
        # SPY 和 QQQ 是必要的
        spy = market_snapshot.get("spy", {})
        qqq = market_snapshot.get("qqq", {})
        if spy.get("change_pct") is None:
            warnings.append("market_snapshot: missing SPY change")
        if qqq.get("change_pct") is None:
            warnings.append("market_snapshot: missing QQQ change")

    # 4. 統計 null 欄位
    null_fields = []
    for ticker, data in fact_pack.get("tickers", {}).items():
        if data.get("price", {}).get("value") is None:
            null_fields.append(f"{ticker}.price")
    details["null_fields"] = null_fields
    if len(null_fields) > 3:
        warnings.append(f"Too many null price fields: {null_fields[:3]}...")

    passed = len(errors) == 0
    details["errors"] = errors
    details["warnings"] = warnings

    return {
        "passed": passed,
        "errors": errors,
        "warnings": warnings,
        "details": details,
    }


def calculate_yoy_percent(
    current: Optional[float],
    previous: Optional[float],
) -> Optional[float]:
    """P0-4: 正確計算 YoY 百分比

    YoY% = (current - previous) / |previous| * 100

    Args:
        current: 當期數值
        previous: 去年同期數值

    Returns:
        YoY 百分比（已乘以 100）或 None
    """
    if current is None or previous is None:
        return None
    if previous == 0:
        return None  # 避免除以零

    yoy = (current - previous) / abs(previous) * 100
    return round(yoy, 2)


def enrich_earnings_with_yoy(fact_pack: dict) -> dict:
    """P0-4: 從 history 計算正確的 YoY

    如果 earnings 中沒有 YoY，從 history 中計算：
    - Q3 FY24 vs Q3 FY23
    - 必須是同一季度比較

    Args:
        fact_pack: fact_pack dict

    Returns:
        更新後的 fact_pack
    """
    earnings = fact_pack.get("earnings", {})

    for ticker, data in earnings.items():
        if ticker.endswith("_history"):
            continue

        # 取得 history
        history_key = f"{ticker}_history"
        history = earnings.get(history_key, [])

        if not history or len(history) < 4:
            continue

        # 當期數據
        current_q = history[0]
        current_period = current_q.get("fiscal_period", "")  # e.g., "Q3 FY24"

        # 找去年同期
        # 從 "Q3 FY24" 推算 "Q3 FY23"
        import re
        match = re.match(r"(Q\d)\s*FY(\d{2})", current_period)
        if not match:
            continue

        quarter = match.group(1)  # "Q3"
        year = int(match.group(2))  # 24

        # 去年同期應該是 "Q3 FY23"
        prev_year = year - 1
        prev_period = f"{quarter} FY{prev_year:02d}"

        # 在 history 中找去年同期
        prev_q = None
        for q in history:
            if q.get("fiscal_period") == prev_period:
                prev_q = q
                break

        if not prev_q:
            logger.warning(f"{ticker}: Cannot find {prev_period} in history")
            continue

        # 計算 YoY
        current_revenue = current_q.get("revenue")
        prev_revenue = prev_q.get("revenue")
        revenue_yoy = calculate_yoy_percent(current_revenue, prev_revenue)

        current_eps = current_q.get("eps")
        prev_eps = prev_q.get("eps")
        eps_yoy = calculate_yoy_percent(current_eps, prev_eps)

        # 更新 fact_pack
        if revenue_yoy is not None:
            if data.get("revenue"):
                data["revenue"]["yoy_pct"] = revenue_yoy
                data["revenue"]["yoy_pct_fmt"] = format_percent(revenue_yoy)
                data["revenue"]["yoy_compared_to"] = prev_period

        if eps_yoy is not None:
            if data.get("eps"):
                data["eps"]["yoy_pct"] = eps_yoy
                data["eps"]["yoy_pct_fmt"] = format_percent(eps_yoy)
                data["eps"]["yoy_compared_to"] = prev_period

        logger.info(f"{ticker}: Calculated YoY - Revenue {revenue_yoy}%, EPS {eps_yoy}%")

    return fact_pack

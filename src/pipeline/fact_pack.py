"""Fact Pack Generator - P1-1

建立「事實包」(Fact Pack)，作為所有可驗證數據的唯一來源。
LLM 只能引用 fact_pack 中的數據，不能自行推算或編造。

設計原則：
1. 所有數字都有明確來源和時間戳
2. YoY 等衍生數據在這裡預先計算好
3. 如果數據不存在，欄位為 null，而非讓 LLM 猜測
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..utils.logging import get_logger

logger = get_logger(__name__)


def format_number(value: float, unit: str = "") -> str:
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


def build_fact_pack(edition_pack: dict, run_date: str) -> dict:
    """從 edition_pack 建立 fact_pack

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
            "version": "1.0",
            "notice": "LLM MUST ONLY cite data from this fact_pack. DO NOT calculate or infer numbers."
        },
        "market_snapshot": {},
        "tickers": {},
        "earnings": {},
        "analyst_actions": []
    }

    # ========== 1. Market Snapshot ==========
    market_snapshot = edition_pack.get("meta", {}).get("market_snapshot", {})
    if market_snapshot:
        as_of = f"{run_date} close"

        fact_pack["market_snapshot"] = {
            "spy": {
                "price": market_snapshot.get("spy_price"),
                "change_pct": market_snapshot.get("spy_change_pct"),
                "as_of": as_of
            },
            "qqq": {
                "price": market_snapshot.get("qqq_price"),
                "change_pct": market_snapshot.get("qqq_change_pct"),
                "as_of": as_of
            },
            "us10y": {
                "value": market_snapshot.get("us10y"),
                "change_bps": market_snapshot.get("us10y_change_bps"),
                "as_of": as_of
            },
            "dxy": {
                "value": market_snapshot.get("dxy"),
                "change_pct": market_snapshot.get("dxy_change_pct"),
                "as_of": as_of
            },
            "vix": {
                "value": market_snapshot.get("vix"),
                "change_pct": market_snapshot.get("vix_change_pct"),
                "as_of": as_of
            }
        }

    # ========== 2. Ticker Data ==========
    market_data = edition_pack.get("market_data", {})
    for ticker, data in market_data.items():
        if not data:
            continue

        price = data.get("price")
        change_pct = data.get("change_pct")
        market_cap = data.get("market_cap")

        fact_pack["tickers"][ticker] = {
            "ticker": ticker,
            "company_name": data.get("company_name", ticker),
            "price": {
                "value": price,
                "change_pct": change_pct,
                "change_dollars": data.get("change"),
                "as_of": f"{run_date} close"
            },
            "market_cap": {
                "value": market_cap,
                "formatted": format_number(market_cap) if market_cap else None,
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
                "revenue_formatted": format_number(data.get("revenue_ttm")),
                "eps": data.get("eps_ttm"),
                "gross_margin_pct": data.get("gross_margin"),
                "operating_margin_pct": data.get("operating_margin"),
                "net_margin_pct": data.get("net_margin"),
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
    peer_table = edition_pack.get("peer_table", [])
    if peer_table:
        for peer in peer_table:
            ticker = peer.get("ticker", "")
            if ticker and ticker not in fact_pack["tickers"]:
                fact_pack["tickers"][ticker] = {
                    "ticker": ticker,
                    "company_name": peer.get("name", ticker),
                    "price": {
                        "value": peer.get("price"),
                        "change_pct": peer.get("change_pct"),
                        "as_of": f"{run_date} close"
                    },
                    "valuation": {
                        "pe_ttm": peer.get("pe_ttm"),
                        "pe_forward": peer.get("pe_fwd"),
                        "ps_ttm": peer.get("ps_ttm"),
                        "ev_sales": peer.get("ev_sales"),
                        "as_of": f"{run_date}"
                    }
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

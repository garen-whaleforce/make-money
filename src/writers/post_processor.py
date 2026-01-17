"""Post Processor - P0-2 Data Blocks 程式化填充

在 LLM 輸出後，用 edition_pack 中的實際資料替換佔位符。

核心原則：
1. LLM 只負責寫推論與洞見
2. 數字由程式填充（deterministic）
3. 若缺少某 fact，顯示 N/A，絕不顯示「數據」「⟦UNTRACED⟧」
"""

import re
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass

from ..utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# 佔位符 Pattern
# =============================================================================

# 通用 UNTRACED pattern（包含所有括號變體）
UNTRACED_ANY = r"(?:⟦UNTRACED⟧|\[UNTRACED\]|【UNTRACED】)"
# 孤立的數據 pattern（排除合法詞組）
# 前向排除: 歷史數據、統計數據、資料數據、大數據
# 後向排除: 數據中心、數據庫、數據分析、數據科學、數據源、數據驗證
ISOLATED_DATA_PATTERN = r"(?<![歷史統計資料大])數據(?![中心庫分析科學源驗證])"
# 通用 placeholder pattern（UNTRACED + 孤立數據）
PLACEHOLDER_ANY = rf"(?:{UNTRACED_ANY}|{ISOLATED_DATA_PATTERN})"

# P0 級：這些絕不能出現在最終輸出
# P0-FIX: 數據 pattern 改用負向前瞻，排除合法詞組（數據中心、歷史數據等）
PLACEHOLDER_PATTERNS = [
    r"⟦UNTRACED⟧",
    r"\[UNTRACED\]",
    r"【UNTRACED】",  # 中文全形括號
    ISOLATED_DATA_PATTERN,  # 排除「數據中心」「歷史數據」「大數據」等
    r"-數據",
    r"\+數據",
    r"\{數據\}",
    r"TBD",
    r"N/A待補",
    r"待更新",
    r"待確認",
    r"待補充",
    r"\$XXX",
    r"XXX%",
]

# 破損 HTML/Markdown 模式（會造成顯示錯誤）
BROKEN_HTML_PATTERNS = [
    # Empty list items with just markdown bold markers
    (r"<li>\s*\*\*\s*</li>", ""),  # <li>**</li> → 移除
    (r"<li>\s*\*\*[^<]*\*\*\s*</li>", ""),  # <li>**some text**</li> without content → 移除
    # Broken bold tags
    (r"\*\*\s*\*\*", ""),  # ** ** → 移除
    # Empty strong tags
    (r"<strong>\s*</strong>", ""),
    # Double dashes from failed placeholder replacement
    (r"--+", "-"),
]

# 合併成一個 regex
PLACEHOLDER_REGEX = re.compile("|".join(PLACEHOLDER_PATTERNS), re.IGNORECASE)


@dataclass
class FillResult:
    """填充結果追蹤"""
    original: str
    filled: str
    source: str  # market_data, earnings, calculated, fallback
    ticker: Optional[str] = None


def format_change_pct(value: float) -> str:
    """格式化漲跌幅"""
    if value >= 0:
        return f"+{value:.2f}%"
    else:
        return f"{value:.2f}%"


def format_price(value: float) -> str:
    """格式化價格"""
    return f"${value:.2f}"


def format_market_cap(value: float) -> str:
    """格式化市值"""
    if value >= 1e12:
        return f"${value / 1e12:.2f}T"
    elif value >= 1e9:
        return f"${value / 1e9:.1f}B"
    elif value >= 1e6:
        return f"${value / 1e6:.1f}M"
    else:
        return f"${value:,.0f}"


def format_volume(value: float) -> str:
    """格式化成交量"""
    if value >= 1e9:
        return f"{value / 1e9:.2f}B"
    elif value >= 1e6:
        return f"{value / 1e6:.1f}M"
    elif value >= 1e3:
        return f"{value / 1e3:.1f}K"
    else:
        return f"{value:,.0f}"


# =============================================================================
# 主要填充邏輯
# =============================================================================

def fill_ticker_placeholders(
    html: str,
    market_data: Dict[str, Dict],
) -> Tuple[str, List[FillResult]]:
    """填充 ticker 相關的佔位符

    處理模式：
    - {TICKER} ... ⟦UNTRACED⟧ → 用 market_data 替換
    - {TICKER} ... -數據 → 用 market_data 替換
    - {TICKER} $XXX (-⟦UNTRACED⟧) → 替換括號內的漲跌幅

    Args:
        html: 原始 HTML
        market_data: {ticker: {price, change_pct, market_cap, volume}}

    Returns:
        (filled_html, fill_results)
    """
    results = []

    for ticker, data in market_data.items():
        price = data.get("price")
        change_pct = data.get("change_pct")
        market_cap = data.get("market_cap")

        if price is None or change_pct is None:
            continue

        # Pattern 1a: <strong>TICKER</strong> -⟦UNTRACED⟧ (HTML bold)
        # 例如: <strong>AMD</strong> -⟦UNTRACED⟧ → <strong>AMD</strong> -0.74%
        pattern1a = rf"(<strong>{ticker}</strong>)\s*[-–]\s*{PLACEHOLDER_ANY}"
        def make_replace1a(t, chg):
            def replace(m):
                results.append(FillResult(
                    original=m.group(0),
                    filled=f"{m.group(1)} {format_change_pct(chg)}",
                    source="market_data",
                    ticker=t,
                ))
                return f"{m.group(1)} {format_change_pct(chg)}"
            return replace
        html = re.sub(pattern1a, make_replace1a(ticker, change_pct), html, flags=re.IGNORECASE)

        # Pattern 1b: **TICKER** -⟦UNTRACED⟧ (Markdown bold)
        # 例如: **AMD** -⟦UNTRACED⟧ → **AMD** -0.74%
        pattern1b = rf"(\*\*{ticker}\*\*)\s*[-–]\s*{PLACEHOLDER_ANY}"
        def make_replace1b(t, chg):
            def replace(m):
                results.append(FillResult(
                    original=m.group(0),
                    filled=f"{m.group(1)} {format_change_pct(chg)}",
                    source="market_data",
                    ticker=t,
                ))
                return f"{m.group(1)} {format_change_pct(chg)}"
            return replace
        html = re.sub(pattern1b, make_replace1b(ticker, change_pct), html, flags=re.IGNORECASE)

        # Pattern 1c: Plain TICKER -⟦UNTRACED⟧ (no formatting)
        # 例如: AMD -⟦UNTRACED⟧ → AMD -0.74%
        pattern1c = rf"({ticker})\s*[-–]\s*{PLACEHOLDER_ANY}"
        def make_replace1c(t, chg):
            def replace(m):
                results.append(FillResult(
                    original=m.group(0),
                    filled=f"{t} {format_change_pct(chg)}",
                    source="market_data",
                    ticker=t,
                ))
                return f"{t} {format_change_pct(chg)}"
            return replace
        html = re.sub(pattern1c, make_replace1c(ticker, change_pct), html, flags=re.IGNORECASE)

        # Pattern 2a: **TICKER** $XXX (-⟦UNTRACED⟧) (Markdown)
        # 例如: **AMD** $203.17 (-⟦UNTRACED⟧) → **AMD** $203.17 (-0.74%)
        pattern2a = rf"(\*\*{ticker}\*\*)\s*\$[\d.,]+\s*\([-–]?{PLACEHOLDER_ANY}\)"
        def make_replace2a(t, p, chg):
            def replace(m):
                results.append(FillResult(
                    original=m.group(0),
                    filled=f"{m.group(1)} {format_price(p)} ({format_change_pct(chg)})",
                    source="market_data",
                    ticker=t,
                ))
                return f"{m.group(1)} {format_price(p)} ({format_change_pct(chg)})"
            return replace
        html = re.sub(pattern2a, make_replace2a(ticker, price, change_pct), html, flags=re.IGNORECASE)

        # Pattern 2b: Plain TICKER $XXX (-⟦UNTRACED⟧)
        # 例如: AMD $203.17 (-⟦UNTRACED⟧) → AMD $203.17 (-0.74%)
        pattern2b = rf"({ticker})\s*\$[\d.,]+\s*\([-–]?{PLACEHOLDER_ANY}\)"
        def make_replace2b(t, p, chg):
            def replace(m):
                results.append(FillResult(
                    original=m.group(0),
                    filled=f"{t} {format_price(p)} ({format_change_pct(chg)})",
                    source="market_data",
                    ticker=t,
                ))
                return f"{t} {format_price(p)} ({format_change_pct(chg)})"
            return replace
        html = re.sub(pattern2b, make_replace2b(ticker, price, change_pct), html, flags=re.IGNORECASE)

        # Pattern 3: 單日漲跌 -數據 (在 ticker 附近)
        # 例如: <div>單日漲跌</div>...<div>-數據</div>
        pattern3 = rf"(單日漲跌.*?)([-–]?{PLACEHOLDER_ANY})"
        def make_replace3(t, chg):
            def replace(m):
                results.append(FillResult(
                    original=m.group(0),
                    filled=f"{m.group(1)}{format_change_pct(chg)}",
                    source="market_data",
                    ticker=t,
                ))
                return f"{m.group(1)}{format_change_pct(chg)}"
            return replace
        # 只在該 ticker 出現的上下文中替換（簡化：全局替換）
        html = re.sub(pattern3, make_replace3(ticker, change_pct), html, count=1, flags=re.DOTALL)

    return html, results


def fill_generic_placeholders(
    html: str,
    fallback: str = "N/A",
) -> Tuple[str, List[FillResult]]:
    """填充剩餘的通用佔位符

    這些是 LLM 無法從 edition_pack 取得的資料，
    用 N/A 或省略處理，絕不留下「數據」字樣。

    Args:
        html: 原始 HTML
        fallback: 替換文字

    Returns:
        (filled_html, fill_results)
    """
    results = []

    def replace_placeholder(m):
        results.append(FillResult(
            original=m.group(0),
            filled=fallback,
            source="fallback",
        ))
        return fallback

    html = PLACEHOLDER_REGEX.sub(replace_placeholder, html)

    return html, results


def process_post_html(
    html: str,
    edition_pack: Dict[str, Any],
    post_type: str = "flash",
) -> Tuple[str, Dict[str, Any]]:
    """處理文章 HTML，填充所有佔位符

    Args:
        html: 原始 HTML
        edition_pack: edition_pack.json 的內容
        post_type: flash, earnings, deep

    Returns:
        (processed_html, processing_report)
    """
    all_results = []

    # 1. 取得 market_data
    market_data = edition_pack.get("market_data", {})

    # 2. 填充 ticker 佔位符
    html, ticker_results = fill_ticker_placeholders(html, market_data)
    all_results.extend(ticker_results)

    # 3. 填充剩餘佔位符
    html, generic_results = fill_generic_placeholders(html)
    all_results.extend(generic_results)

    # 4. 生成報告
    report = {
        "total_fills": len(all_results),
        "ticker_fills": len(ticker_results),
        "fallback_fills": len(generic_results),
        "fills": [
            {
                "original": r.original,
                "filled": r.filled,
                "source": r.source,
                "ticker": r.ticker,
            }
            for r in all_results
        ],
    }

    if generic_results:
        logger.warning(
            f"[{post_type}] {len(generic_results)} placeholders replaced with fallback. "
            f"Consider adding data sources for: {[r.original for r in generic_results[:3]]}"
        )

    return html, report


def validate_no_placeholders(html: str) -> Tuple[bool, List[str]]:
    """驗證 HTML 中沒有佔位符

    Args:
        html: HTML 內容

    Returns:
        (is_valid, found_placeholders)
    """
    matches = PLACEHOLDER_REGEX.findall(html)
    return len(matches) == 0, matches


# =============================================================================
# Quality Gate Integration
# =============================================================================

def placeholder_quality_gate(
    html: str,
    title: str = "",
    excerpt: str = "",
) -> Dict[str, Any]:
    """P0-5: 佔位符品質檢查

    Args:
        html: HTML 內容
        title: 標題
        excerpt: 摘要

    Returns:
        {passed, failures, details}
    """
    all_content = f"{title}\n{excerpt}\n{html}"

    is_valid, found = validate_no_placeholders(all_content)

    return {
        "gate": "placeholder_blocking",
        "passed": is_valid,
        "failures": found,
        "count": len(found),
        "severity": "P0" if not is_valid else None,
        "message": f"Found {len(found)} placeholder(s): {found[:5]}" if found else "No placeholders found",
    }


def single_article_quality_gate(html: str, expected_ticker: str = None) -> Dict[str, Any]:
    """P0-5: 單篇完整性檢查（防串檔）

    Args:
        html: HTML 內容
        expected_ticker: 預期的 ticker

    Returns:
        {passed, failures, details}
    """
    # 檢查 h1 數量
    h1_matches = re.findall(r"<h1[^>]*>.*?</h1>", html, re.IGNORECASE | re.DOTALL)
    h1_count = len(h1_matches)

    failures = []

    if h1_count == 0:
        failures.append("No h1 tag found")
    elif h1_count > 1:
        failures.append(f"Multiple h1 tags found ({h1_count}): possible article merge")

    # 如果有預期 ticker，檢查 h1 是否包含
    if expected_ticker and h1_matches:
        h1_text = h1_matches[0]
        if expected_ticker.upper() not in h1_text.upper():
            failures.append(f"Expected ticker {expected_ticker} not found in h1")

    return {
        "gate": "single_article_integrity",
        "passed": len(failures) == 0,
        "failures": failures,
        "h1_count": h1_count,
        "severity": "P0" if failures else None,
        "message": "; ".join(failures) if failures else "Single article verified",
    }


# =============================================================================
# P0-3: 智能佔位符修稿器
# =============================================================================

# 可移除的句子模式（若包含無法填充的佔位符）
REMOVABLE_SENTENCE_PATTERNS = [
    # 數據來源不確定的句子
    rf"目前\s*(?:spot\s*)?price\s*~?\s*{PLACEHOLDER_ANY}[^。]*[。]?",
    rf"[^。]*(?:預計|預期|估計)\s*{PLACEHOLDER_ANY}[^。]*[。]?",
    # 括號中的佔位符可以整個移除
    rf"\([^)]*{PLACEHOLDER_ANY}[^)]*\)",
]

# 這些 ticker 相關佔位符用 market_data 填充
TICKER_CONTEXT_PATTERNS = [
    # "NVDA -⟦UNTRACED⟧" or "NVDA +⟦UNTRACED⟧"
    rf"([A-Z]{{2,5}})\s*([+-]?){PLACEHOLDER_ANY}",
    # "$NVDA -⟦UNTRACED⟧"
    rf"\$([A-Z]{{2,5}})\s*([+-]?){PLACEHOLDER_ANY}",
    # "NVDA 飆升/上漲/下跌 ⟦UNTRACED⟧"
    rf"([A-Z]{{2,5}})\s*(?:飆升|上漲|下跌|漲|跌|up|down)\s*{PLACEHOLDER_ANY}",
    # "NVDA: -⟦UNTRACED⟧" (Theme Board style)
    rf"([A-Z]{{2,5}}):\s*([+-]?){PLACEHOLDER_ANY}",
]

# 可安全移除的包含佔位符的完整片段（適合 aggressive 模式）
REMOVABLE_FRAGMENTS = [
    # 目標價相關（沒有實際數字就移除整段）
    rf"目標價[^。,，]*{PLACEHOLDER_ANY}[^。,，]*[。,，]?",
    # 價格範圍
    rf"價格[^。,，]*{PLACEHOLDER_ANY}[^。,，]*[。,，]?",
    # 括號中的佔位符
    rf"\([^)]*{PLACEHOLDER_ANY}[^)]*\)",
    # 單純的 "上漲/下跌 ⟦UNTRACED⟧" 短語
    rf"(?:上漲|下跌|漲|跌)\s*{PLACEHOLDER_ANY}%?",
]

# 最終替換規則：將無法填充的佔位符替換為合理的泛稱（不是移除）
FINAL_REPLACEMENT_RULES = [
    # "飆漲 ⟦UNTRACED⟧" → "飆漲" (remove the placeholder part)
    (rf"(飆漲|飆升|暴漲|大漲|上漲|下跌|大跌|暴跌)\s*{UNTRACED_ANY}%?", r"\1"),
    # "up ⟦UNTRACED⟧" → "significantly"
    (rf"\bup\s*{UNTRACED_ANY}%?\s*(?:intraday)?", "significantly"),
    # "↑⟦UNTRACED⟧" or "↓⟦UNTRACED⟧" → just the arrow
    (rf"([↑↓])\s*{UNTRACED_ANY}%?", r"\1"),
    # "盤中飆漲/飆升 ⟦UNTRACED⟧" → "盤中飆漲"
    (rf"(盤中[^\s]*)\s*{UNTRACED_ANY}%?", r"\1"),
    # "相當於 ⟦UNTRACED⟧ 個" → "相當於數千個"
    (rf"相當於\s*{UNTRACED_ANY}\s*個", "相當於數千個"),
    # "將達 ⟦UNTRACED⟧ TWh" → "將大幅增加"
    (rf"將達\s*{UNTRACED_ANY}\s*TWh", "將大幅增加"),
    # "+⟦UNTRACED⟧" 作為單獨元素 → 移除整行
    (rf"<strong>\+{UNTRACED_ANY}</strong>[^<]*</p>", "</p>"),
    # "— TICKER" descriptions with placeholder at start
    (rf"<strong>\+?{UNTRACED_ANY}</strong>\s*—", "<strong>（待更新）</strong> —"),
    # Generic pattern for remaining isolated placeholders - replace with empty
    (rf"\s*{UNTRACED_ANY}%?\s*", " "),
]


def cleanup_broken_html(html: str) -> Tuple[str, List[str]]:
    """
    清理破損的 HTML/Markdown 結構

    處理：
    - <li>**</li> 空白列表項
    - ** ** 空白粗體
    - <strong></strong> 空白標籤
    - 多餘的破折號

    Args:
        html: HTML 內容

    Returns:
        (cleaned_html, list of changes made)
    """
    changes = []

    for pattern, replacement in BROKEN_HTML_PATTERNS:
        matches = re.findall(pattern, html)
        if matches:
            html = re.sub(pattern, replacement, html)
            changes.append(f"Removed {len(matches)} instances of pattern: {pattern[:30]}...")

    # 清理連續空白行
    html = re.sub(r'\n\s*\n\s*\n', '\n\n', html)

    # 清理空的 <ul></ul>
    html = re.sub(r'<ul>\s*</ul>', '', html)

    return html, changes


def fix_markdown_lists_to_html(html: str) -> Tuple[str, int]:
    """
    將 Markdown 風格的 dash lists 轉換為 HTML lists

    例如：
    <p>立即閱讀：
    - <a href="...">Link 1</a>
    - <a href="...">Link 2</a></p>

    轉換為：
    <p>立即閱讀：</p>
    <ul>
      <li><a href="...">Link 1</a></li>
      <li><a href="...">Link 2</a></li>
    </ul>

    Args:
        html: HTML 內容

    Returns:
        (fixed_html, number of conversions)
    """
    conversions = 0

    # 找到包含 "- <a" 的 <p> 標籤並轉換
    pattern = r'<p>([^<]*?)(\n\s*-\s*<a[^>]+>[^<]*</a>\s*)+</p>'

    def convert_to_list(m):
        nonlocal conversions
        conversions += 1
        full_match = m.group(0)
        prefix = m.group(1).strip()

        # 提取所有 - <a>...</a> 項目
        items = re.findall(r'-\s*(<a[^>]+>[^<]*</a>)', full_match)

        if not items:
            return full_match

        # 建立 HTML list
        list_items = '\n'.join(f'  <li>{item}</li>' for item in items)

        if prefix:
            return f'<p>{prefix}</p>\n<ul>\n{list_items}\n</ul>'
        else:
            return f'<ul>\n{list_items}\n</ul>'

    html = re.sub(pattern, convert_to_list, html, flags=re.DOTALL)

    return html, conversions


def intelligent_placeholder_fixer(
    html: str,
    edition_pack: Dict[str, Any],
    fact_pack: Optional[Dict[str, Any]] = None,
    strategy: str = "conservative",  # "conservative" | "aggressive"
) -> Tuple[str, Dict[str, Any]]:
    """
    P0-3: 智能佔位符修稿器

    策略：
    1. 首先嘗試從 market_data / fact_pack 找到正確值
    2. 若找不到：
       - conservative: 替換為 N/A
       - aggressive: 嘗試移除整個句子

    Args:
        html: HTML 內容
        edition_pack: edition_pack.json
        fact_pack: fact_pack.json（可選，提供更多數據）
        strategy: 處理策略

    Returns:
        (fixed_html, report)
    """
    report = {
        "filled_from_data": 0,
        "removed_sentences": 0,
        "replaced_with_na": 0,
        "remaining": 0,
        "changes": [],
    }

    market_data = edition_pack.get("market_data", {})

    # 從 fact_pack 取得更多數據
    fact_tickers = {}
    if fact_pack:
        fact_tickers = fact_pack.get("tickers", {})

    # Step 1: 嘗試填充 ticker 相關佔位符
    for pattern in TICKER_CONTEXT_PATTERNS:
        def replace_ticker_placeholder(m):
            ticker = m.group(1)
            sign = m.group(2) if len(m.groups()) > 1 else ""

            # 從 market_data 找
            data = market_data.get(ticker)
            if data and data.get("change_pct") is not None:
                change = data["change_pct"]
                formatted = format_change_pct(change)
                report["filled_from_data"] += 1
                report["changes"].append(f"{ticker}: filled from market_data ({formatted})")
                return f"{ticker} {formatted}"

            # 從 fact_pack 找
            fact = fact_tickers.get(ticker, {})
            price_data = fact.get("price", {})
            if price_data.get("change_pct") is not None:
                change = price_data["change_pct"]
                formatted = format_change_pct(change)
                report["filled_from_data"] += 1
                report["changes"].append(f"{ticker}: filled from fact_pack ({formatted})")
                return f"{ticker} {formatted}"

            # 找不到，用 N/A
            report["replaced_with_na"] += 1
            report["changes"].append(f"{ticker}: replaced with N/A (no data)")
            return f"{ticker} N/A"

        html = re.sub(pattern, replace_ticker_placeholder, html, flags=re.IGNORECASE)

    # Step 2: 嘗試移除無法填充的句子（aggressive 模式）
    if strategy == "aggressive":
        for pattern in REMOVABLE_SENTENCE_PATTERNS:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                html = re.sub(pattern, "", html, flags=re.IGNORECASE)
                report["removed_sentences"] += len(matches)
                for m in matches[:3]:
                    report["changes"].append(f"Removed: {m[:50]}...")

    # Step 3: 應用最終替換規則（更精細的替換）
    for pattern, replacement in FINAL_REPLACEMENT_RULES:
        before_count = len(PLACEHOLDER_REGEX.findall(html))
        html = re.sub(pattern, replacement, html)
        after_count = len(PLACEHOLDER_REGEX.findall(html))
        if before_count > after_count:
            report["changes"].append(f"Final rule applied: {pattern[:30]}... → {replacement[:20]}")
            report["replaced_with_na"] += (before_count - after_count)

    # Step 4: 替換剩餘佔位符為空字串（不用 N/A，直接移除）
    remaining_placeholders = PLACEHOLDER_REGEX.findall(html)
    if remaining_placeholders:
        def replace_remaining(m):
            report["replaced_with_na"] += 1
            return ""  # 改為空字串，不是 N/A
        html = PLACEHOLDER_REGEX.sub(replace_remaining, html)
        report["changes"].append(f"Removed {len(remaining_placeholders)} remaining placeholders")

    # Step 5: 清理多餘空白（只在文本中，不影響 HTML 結構）
    html = re.sub(r'  +', ' ', html)  # 多個空格合併為一個（保留換行）
    html = re.sub(r' ([，。、；：])', r'\1', html)  # 標點符號前的單個空格

    # Step 6: 驗證
    final_check = PLACEHOLDER_REGEX.findall(html)
    report["remaining"] = len(final_check)

    return html, report


def strip_placeholders_from_all_fields(post_json: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """
    P0-FIX: 從所有字串欄位中移除佔位符

    這是最後一道防線，確保 title, excerpt, newsletter_subject 等
    preview 欄位不會有佔位符洩漏到 Email/SEO/社群分享。

    Args:
        post_json: 文章 JSON

    Returns:
        (cleaned_json, removed_count)
    """
    removed_count = 0

    def clean_string(s: str) -> str:
        nonlocal removed_count
        if not isinstance(s, str):
            return s

        # 找出並移除所有佔位符
        matches = PLACEHOLDER_REGEX.findall(s)
        if matches:
            removed_count += len(matches)
            # 替換為空字串，然後清理多餘空白
            cleaned = PLACEHOLDER_REGEX.sub("", s)
            cleaned = re.sub(r'  +', ' ', cleaned).strip()
            # 清理殘留的破折號和括號
            cleaned = re.sub(r'\s*[-–]\s*$', '', cleaned)  # 結尾的破折號
            cleaned = re.sub(r'\(\s*\)', '', cleaned)  # 空括號
            cleaned = re.sub(r'\s*-\s*-\s*', ' - ', cleaned)  # 雙破折號
            return cleaned
        return s

    def clean_recursive(obj):
        if isinstance(obj, str):
            return clean_string(obj)
        elif isinstance(obj, dict):
            return {k: clean_recursive(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [clean_recursive(item) for item in obj]
        return obj

    cleaned_json = clean_recursive(post_json)

    if removed_count > 0:
        logger.warning(f"[P0-FIX] Stripped {removed_count} placeholders from post JSON fields")

    return cleaned_json, removed_count


def enhanced_process_post_html(
    html: str,
    edition_pack: Dict[str, Any],
    post_type: str = "flash",
    fact_pack: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    P0-3: 增強版文章處理（整合智能修稿器 + HTML 清理）

    處理順序：
    1. 先用原有的 ticker 佔位符填充
    2. 再用智能修稿器處理剩餘佔位符
    3. 清理破損的 HTML/Markdown
    4. 轉換 Markdown lists 為 HTML lists
    5. 最終驗證

    Args:
        html: 原始 HTML
        edition_pack: edition_pack.json
        post_type: flash, earnings, deep
        fact_pack: fact_pack.json（可選）

    Returns:
        (processed_html, combined_report)
    """
    # Step 1: 原有的 ticker 填充
    market_data = edition_pack.get("market_data", {})
    html, ticker_results = fill_ticker_placeholders(html, market_data)

    # Step 2: 智能修稿器（使用 aggressive 模式移除無法填充的句子）
    html, fixer_report = intelligent_placeholder_fixer(
        html, edition_pack, fact_pack, strategy="aggressive"
    )

    # Step 3: 最終的通用佔位符處理
    html, generic_results = fill_generic_placeholders(html)

    # Step 4: 清理破損的 HTML/Markdown
    html, cleanup_changes = cleanup_broken_html(html)

    # Step 5: 轉換 Markdown lists 為 HTML lists
    html, list_conversions = fix_markdown_lists_to_html(html)

    # Step 6: 最終驗證（再次檢查是否還有佔位符）
    final_check = PLACEHOLDER_REGEX.findall(html)

    # 合併報告
    combined_report = {
        "total_fills": len(ticker_results) + fixer_report["filled_from_data"],
        "ticker_fills": len(ticker_results),
        "intelligent_fills": fixer_report["filled_from_data"],
        "removed_sentences": fixer_report["removed_sentences"],
        "fallback_fills": len(generic_results) + fixer_report["replaced_with_na"],
        "html_cleanup": cleanup_changes,
        "list_conversions": list_conversions,
        "remaining_placeholders": len(final_check),
        "remaining_details": final_check[:10] if final_check else [],
        "changes": fixer_report["changes"] + cleanup_changes,
    }

    if combined_report["remaining_placeholders"] > 0:
        logger.warning(
            f"[{post_type}] Still has {combined_report['remaining_placeholders']} "
            f"placeholders after processing: {final_check[:5]}"
        )

    return html, combined_report


# =============================================================================
# P0-4: LLM 輸出轉換器（Schema → Renderer 格式）
# =============================================================================

def transform_llm_output_for_renderer(
    post_json: Dict[str, Any],
    post_type: str = "flash",
) -> Dict[str, Any]:
    """
    將 LLM 輸出的 JSON 轉換為 template_renderer 期望的格式

    Schema 輸出:
    - news_items, executive_summary, tldr (string array)

    Renderer 期望:
    - news_radar, summary (chinese/english), tldr (object array)

    Args:
        post_json: LLM 產生的 JSON（符合 schema）
        post_type: flash, earnings, deep

    Returns:
        轉換後的 JSON（符合 renderer）
    """
    transformed = post_json.copy()

    # 1. executive_summary → summary
    exec_summary = post_json.get("executive_summary", {})
    if exec_summary:
        transformed["summary"] = {
            "chinese": exec_summary.get("zh_tw", exec_summary.get("zh", "")),
            "english": exec_summary.get("en", ""),
        }

    # 2. news_items → news_radar (for flash)
    if post_type == "flash":
        news_items = post_json.get("news_items", [])
        if news_items:
            radar_items = []
            for item in news_items[:6]:
                radar_items.append({
                    "headline": item.get("headline_zh", item.get("headline", "")),
                    "impact": item.get("direction", "mixed"),
                    "chain": f"{item.get('affected_sectors', [''])[0] if item.get('affected_sectors') else ''} → {', '.join(item.get('affected_tickers', [])[:3])}",
                    "watch": item.get("what_to_watch", [""])[0] if item.get("what_to_watch") else "",
                })
            transformed["news_radar"] = radar_items

    # 3. tldr (string array) → tldr (object array with ticker/move/reason)
    tldr_items = post_json.get("tldr", [])
    if tldr_items and isinstance(tldr_items, list):
        if isinstance(tldr_items[0], str):
            # 需要轉換 string array 為 object array
            transformed_tldr = []
            for item in tldr_items:
                # 嘗試解析格式 "TICKER +X%：描述" 或純文字
                import re
                match = re.match(r'^([A-Z]{2,5})\s*([+-]?[\d.]+%)?[：:]?\s*(.*)$', item)
                if match:
                    transformed_tldr.append({
                        "ticker": match.group(1),
                        "move": match.group(2) or "",
                        "reason": match.group(3) or item,
                    })
                else:
                    transformed_tldr.append({
                        "ticker": "",
                        "move": "",
                        "reason": item,
                    })
            transformed["tldr"] = transformed_tldr

    # 4. key_stocks → sector_flow_chart items
    key_stocks = post_json.get("key_stocks", [])
    if key_stocks and post_type == "flash":
        flow_items = []
        for stock in key_stocks[:8]:
            flow_items.append({
                "ticker": stock.get("ticker", ""),
                "name": stock.get("name", ""),
                "change_pct": stock.get("change_pct", 0),
                "volume_ratio": 1,
                "signal": "bullish" if stock.get("change_pct", 0) > 0 else "bearish",
            })
        transformed["sector_flow_chart"] = {"items": flow_items}

    # 5. repricing_dashboard → 添加 affected 欄位
    repricing = post_json.get("repricing_dashboard", [])
    if repricing:
        for item in repricing:
            if "direct_impact" in item and "affected" not in item:
                item["affected"] = item["direct_impact"]
        transformed["repricing_dashboard"] = repricing

    # 6. timeline → watchlist (for renderer)
    timeline = post_json.get("timeline", [])
    if timeline:
        transformed["watchlist"] = timeline

    # 7. 添加 deep_dive_ticker
    meta = post_json.get("meta", {})
    if meta.get("deep_dive_ticker"):
        transformed["deep_dive_ticker"] = meta["deep_dive_ticker"]

    # 8. contrarian_view → scenarios.bear
    contrarian = post_json.get("contrarian_view", {})
    if contrarian:
        scenarios = transformed.get("scenarios", {})
        if not scenarios.get("bear"):
            scenarios["bear"] = {
                "description": contrarian.get("bear_case", ""),
                "triggers": contrarian.get("trigger_indicators", []),
            }
        transformed["scenarios"] = scenarios

    # 9. theme_board 轉換（schema格式 → renderer格式）
    theme_board_raw = post_json.get("theme_board", {})
    if theme_board_raw:
        # Schema 格式: {"as_of": "...", "themes": [{"id": "ai_chips", "status": "...", ...}]}
        # Renderer 格式: {"ai_chips": {"name": "AI Chips", "status": "...", "tickers": [...]}}
        if "themes" in theme_board_raw and isinstance(theme_board_raw["themes"], list):
            new_theme_board = {}
            for theme in theme_board_raw["themes"]:
                theme_id = theme.get("id", "")
                if theme_id:
                    new_theme_board[theme_id] = {
                        "name": theme.get("title", theme.get("name", theme_id)),
                        "status": theme.get("status", "neutral"),
                        "tickers": theme.get("tickers", []),
                    }
            if new_theme_board:
                transformed["theme_board"] = new_theme_board
        elif isinstance(theme_board_raw, dict) and "themes" not in theme_board_raw:
            # 可能已經是正確格式，檢查第一個值是否為 dict
            first_value = next(iter(theme_board_raw.values()), None)
            if isinstance(first_value, dict):
                transformed["theme_board"] = theme_board_raw
            # 否則可能是 string values（如 "ai_chips": "bullish"），跳過

    # 10. 確保 cross_links 存在
    if "cross_links" not in transformed:
        transformed["cross_links"] = post_json.get("meta", {}).get("cross_links", {})

    # 11. 添加 date 欄位
    if "date" not in transformed and meta.get("date"):
        transformed["date"] = meta["date"]

    # Earnings-specific transformations
    if post_type == "earnings":
        # earnings_scoreboard 已經是正確格式
        # valuation → valuation_stress_test
        valuation = post_json.get("valuation", {})
        if valuation.get("scenarios"):
            transformed["valuation_stress_test"] = {
                "current_price": valuation.get("current_price", 0),
                "scenarios": [
                    {
                        "label": s.get("name", s.get("label", "")),
                        "target_price": s.get("target_price", 0),
                        "multiple": s.get("pe_multiple", s.get("multiple", 0)),
                        "rationale": s.get("rationale", ""),
                    }
                    for s in valuation["scenarios"]
                ]
            }

        # ticker_profile → company info
        ticker_profile = post_json.get("ticker_profile", {})
        if ticker_profile:
            transformed["ticker"] = ticker_profile.get("ticker", "")

    # Deep-specific transformations
    if post_type == "deep":
        # ticker_profile → company_profile
        ticker_profile = post_json.get("ticker_profile", {})
        if ticker_profile:
            transformed["company_profile"] = {
                "ticker": ticker_profile.get("ticker", ""),
                "name": ticker_profile.get("company_name", ""),
                "price": ticker_profile.get("price", 0),
                "change_pct": ticker_profile.get("change_pct", 0),
                "market_cap": ticker_profile.get("market_cap", ""),
                "pe_ttm": ticker_profile.get("pe_ttm", "N/A"),
                "gross_margin": ticker_profile.get("gross_margin", "N/A"),
            }
            transformed["ticker"] = ticker_profile.get("ticker", "")

        # thesis/anti_thesis → bull_bear
        thesis = post_json.get("thesis", "")
        anti_thesis = post_json.get("anti_thesis", "")
        if thesis or anti_thesis:
            bull_points = post_json.get("bull_points", [])
            bear_points = post_json.get("bear_points", [])
            transformed["bull_bear"] = {
                "bull": {
                    "thesis": thesis,
                    "points": bull_points if bull_points else [thesis] if thesis else [],
                },
                "bear": {
                    "thesis": anti_thesis,
                    "points": bear_points if bear_points else [anti_thesis] if anti_thesis else [],
                },
            }

        # valuation_scenarios
        valuation = post_json.get("valuation", {})
        if valuation.get("scenarios"):
            transformed["valuation_scenarios"] = {
                "current_price": valuation.get("current_price", 0),
                "scenarios": [
                    {
                        "label": s.get("name", s.get("label", "")),
                        "target_price": s.get("target_price", 0),
                        "multiple": s.get("pe_multiple", s.get("multiple", 0)),
                        "rationale": s.get("rationale", ""),
                    }
                    for s in valuation["scenarios"]
                ]
            }

        # decision_tree from if_then_branches
        if_then = post_json.get("if_then_branches", [])
        if if_then:
            decision_tree = []
            for branch in if_then:
                decision_tree.append({
                    "signal": branch.get("if_condition", branch.get("signal", "")),
                    "interpretation": branch.get("then_action", branch.get("interpretation", "")),
                    "action": branch.get("action", ""),
                    "risk_control": branch.get("risk_control", ""),
                    "next_check": branch.get("next_check", ""),
                })
            transformed["decision_tree"] = decision_tree

        # moat analysis
        moat = post_json.get("moat", {})
        if moat:
            transformed["moat_analysis"] = {
                "types": moat.get("types", []),
                "durability": moat.get("durability", "medium"),
                "description": moat.get("description", ""),
            }

    return transformed


def fill_missing_qa_fields(
    post_json: Dict[str, Any],
    edition_pack: Dict[str, Any],
    post_type: str = "flash",
) -> Dict[str, Any]:
    """
    填充 QA 必需但 LLM 可能遺漏的欄位

    Args:
        post_json: LLM 產生的 JSON
        edition_pack: edition_pack.json
        post_type: flash, earnings, deep

    Returns:
        填充後的 JSON
    """
    filled = post_json.copy()

    # 1. what_to_watch - 從 news_items 提取
    if not filled.get("what_to_watch"):
        watch_items = []
        for item in filled.get("news_items", []):
            watches = item.get("what_to_watch", [])
            if watches:
                watch_items.extend(watches[:2])
        if watch_items:
            filled["what_to_watch"] = watch_items[:5]
        else:
            # 從 timeline 提取
            timeline = filled.get("timeline", [])
            filled["what_to_watch"] = [t.get("event", "") for t in timeline[:3]]

    # 2. title_candidates - 基於標題生成變體
    if not filled.get("title_candidates"):
        title = filled.get("title", "")
        title_en = filled.get("title_en", "")
        ticker = filled.get("meta", {}).get("deep_dive_ticker", "")

        candidates = [title]
        if title_en:
            candidates.append(title_en)
        if ticker:
            candidates.append(f"{ticker} 深度分析：投資價值評估")
            candidates.append(f"今日焦點：{ticker} 帶動市場情緒")
            candidates.append(f"{ticker} 投資攻略：多空觀點完整解析")

        filled["title_candidates"] = candidates[:5] if len(candidates) >= 5 else candidates + [""] * (5 - len(candidates))

    # 3. disclosure - 添加免責聲明
    if not filled.get("disclosure"):
        filled["disclosure"] = {
            "not_investment_advice": True,
            "text": "本文僅供參考，非投資建議。投資有風險，入市需謹慎。過去績效不代表未來表現。"
        }

    # 4. repricing_dashboard - 確保至少 3 項
    repricing = filled.get("repricing_dashboard", [])
    if len(repricing) < 3:
        default_items = [
            {
                "variable": "Fed 利率預期",
                "why_important": "影響估值倍數",
                "leading_signal": "CME FedWatch",
                "direct_impact": "成長股估值",
            },
            {
                "variable": "美元指數 (DXY)",
                "why_important": "影響跨國企業獲利",
                "leading_signal": "DXY 走勢",
                "direct_impact": "科技股營收",
            },
            {
                "variable": "VIX 波動率",
                "why_important": "市場風險偏好指標",
                "leading_signal": "VIX 期貨",
                "direct_impact": "高 Beta 股票",
            },
        ]
        for item in default_items:
            if len(repricing) >= 3:
                break
            if item["variable"] not in [r.get("variable") for r in repricing]:
                repricing.append(item)
        filled["repricing_dashboard"] = repricing

    # 5. peer_table - 從 key_stocks 生成
    if not filled.get("peer_table") or len(filled.get("peer_table", [])) < 2:
        key_stocks = filled.get("key_stocks", [])
        if key_stocks:
            peer_table = []
            for stock in key_stocks[:4]:
                peer_table.append({
                    "ticker": stock.get("ticker", ""),
                    "price": stock.get("price", ""),
                    "change": f"{stock.get('change_pct', 0):+.2f}%" if stock.get("change_pct") else "",
                    "pe_ttm": stock.get("pe_ttm", "N/A"),
                    "market_cap": stock.get("market_cap", ""),
                })
            filled["peer_table"] = peer_table

    return filled


if __name__ == "__main__":
    # Demo
    from rich.console import Console
    from rich.table import Table

    console = Console()

    # 模擬 HTML 和 market_data
    test_html = """
    <li><strong>AMD</strong> -⟦UNTRACED⟧：AI 晶片競爭壓力</li>
    <li>核電需求增加推動鈾價，目前 spot price ~⟦UNTRACED⟧/lb</li>
    <div>單日漲跌</div><div>-數據</div>
    """

    test_market_data = {
        "AMD": {"price": 203.17, "change_pct": -0.74, "market_cap": 329e9},
        "NVDA": {"price": 185.04, "change_pct": -1.23, "market_cap": 4.5e12},
    }

    test_pack = {"market_data": test_market_data}

    console.print("[bold cyan]Post Processor Demo[/bold cyan]\n")
    console.print("[yellow]Before:[/yellow]")
    console.print(test_html)

    processed, report = process_post_html(test_html, test_pack)

    console.print("\n[green]After:[/green]")
    console.print(processed)

    console.print(f"\n[bold]Report:[/bold] {report['total_fills']} fills made")

    # 驗證
    is_valid, found = validate_no_placeholders(processed)
    console.print(f"\n[bold]Validation:[/bold] {'PASSED' if is_valid else 'FAILED'}")
    if found:
        console.print(f"  Remaining placeholders: {found}")

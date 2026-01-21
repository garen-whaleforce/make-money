"""
Percent Data Contract - P0-2

定義百分比欄位的語義，防止 99.87% 類錯誤。

核心問題：
- FMP API 返回 change_pct = 0.0375662 表示 +3.76%（已是百分比形式）
- 某些 API 返回 decimal = 0.0375662 表示 +3.76%（需要 *100）
- 若混淆會導致 0.04% vs 3.76% 的錯誤

契約規則：
1. edition_pack.market_data[ticker].change_pct: 已是百分比形式（-0.12 = -0.12%）
2. fact_pack.tickers[ticker].change_pct: 同上
3. 任何 _pct 結尾的欄位預設為百分比形式
4. 任何 _decimal 結尾的欄位預設為小數形式（需 *100）

驗證規則：
- change_pct 通常在 -20% ~ +20% 範圍內
- 若絕對值 > 50，很可能是已經乘過 100 的值
- 若絕對值 < 0.1 且非零，很可能是未乘 100 的小數
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple
import math

from ..utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# 契約定義
# =============================================================================

# 這些欄位已經是百分比形式（不需要 *100）
PCT_FIELDS = {
    "change_pct",           # 單日漲跌 -0.12 = -0.12%
    "change_percent",       # 同上
    "changesPercentage",    # FMP API 欄位名
    "yoy_pct",              # YoY 成長率
    "revenue_yoy_pct",
    "eps_yoy_pct",
    "gross_margin_pct",
    "operating_margin_pct",
    "net_margin_pct",
    "pe_ratio",             # 這不是百分比，但值域類似
}

# 這些欄位是小數形式（需要 *100 轉成百分比）
DECIMAL_FIELDS = {
    "change_decimal",
    "yoy_decimal",
    "gross_margin_decimal",
    "operating_margin_decimal",
    "net_margin_decimal",
}

# 合理的百分比範圍（用於偵測異常）
REASONABLE_PCT_RANGE = (-50.0, 100.0)  # 大多數單日漲跌在這範圍內

# 極端但仍可能的範圍（允許但會 warning）
EXTREME_PCT_RANGE = (-99.0, 500.0)


@dataclass
class PercentValidationResult:
    """百分比驗證結果"""
    field: str
    value: float
    is_valid: bool
    normalized_value: Optional[float] = None
    warning: Optional[str] = None
    error: Optional[str] = None


# =============================================================================
# 驗證函數
# =============================================================================

def validate_percent_value(
    value: float,
    field_name: str,
    expected_range: Tuple[float, float] = REASONABLE_PCT_RANGE,
) -> PercentValidationResult:
    """
    驗證單一百分比值

    Args:
        value: 百分比值
        field_name: 欄位名稱
        expected_range: 預期範圍

    Returns:
        PercentValidationResult
    """
    if value is None:
        return PercentValidationResult(
            field=field_name,
            value=None,
            is_valid=False,
            error="Value is None",
        )

    min_val, max_val = expected_range

    # 檢查是否在合理範圍內
    if min_val <= value <= max_val:
        return PercentValidationResult(
            field=field_name,
            value=value,
            is_valid=True,
        )

    # 檢查是否可能是小數形式（應該 *100）
    if -1 < value < 1 and value != 0:
        # 很可能是 0.0376 而非 3.76
        return PercentValidationResult(
            field=field_name,
            value=value,
            is_valid=False,
            normalized_value=value * 100,
            warning=f"Suspiciously small value {value:.4f}, might be decimal form. Normalized: {value * 100:.2f}%",
        )

    # 檢查是否超出極端範圍
    ext_min, ext_max = EXTREME_PCT_RANGE
    if value < ext_min or value > ext_max:
        return PercentValidationResult(
            field=field_name,
            value=value,
            is_valid=False,
            error=f"Value {value:.2f}% outside extreme range [{ext_min}, {ext_max}]",
        )

    # 在極端但允許的範圍內
    return PercentValidationResult(
        field=field_name,
        value=value,
        is_valid=True,
        warning=f"Value {value:.2f}% outside typical range {expected_range}",
    )


def normalize_percent(
    value: float,
    source_format: str = "pct",  # "pct" or "decimal"
) -> float:
    """
    正規化百分比值

    Args:
        value: 輸入值
        source_format: 來源格式
            - "pct": 已是百分比（3.76 = 3.76%）
            - "decimal": 小數形式（0.0376 = 3.76%）

    Returns:
        正規化後的百分比值
    """
    if source_format == "decimal":
        return value * 100
    return value


def detect_percent_format(value: float) -> str:
    """
    偵測百分比格式

    啟發式規則：
    - 若 |value| < 0.5 且 value != 0，可能是 decimal
    - 若 |value| > 0.5，可能是 pct

    Args:
        value: 輸入值

    Returns:
        "pct" or "decimal" or "unknown"
    """
    if value == 0:
        return "unknown"

    abs_val = abs(value)

    if abs_val < 0.5:
        return "decimal"  # 可能是 0.0376 = 3.76%
    elif abs_val > 0.5:
        return "pct"  # 可能是 3.76 = 3.76%
    else:
        return "unknown"


# =============================================================================
# 批量驗證
# =============================================================================

def validate_market_data(market_data: Dict[str, Dict]) -> Dict[str, Any]:
    """
    驗證 market_data 中的百分比欄位

    Args:
        market_data: edition_pack.market_data

    Returns:
        {
            "valid": bool,
            "errors": [],
            "warnings": [],
            "normalized": {}  # 需要正規化的欄位
        }
    """
    errors = []
    warnings = []
    normalized = {}

    for ticker, data in market_data.items():
        change_pct = data.get("change_pct")
        if change_pct is None:
            warnings.append(f"{ticker}: change_pct is None")
            continue

        result = validate_percent_value(change_pct, f"{ticker}.change_pct")

        if not result.is_valid:
            if result.error:
                errors.append(result.error)
            if result.normalized_value is not None:
                normalized[ticker] = {
                    "original": change_pct,
                    "normalized": result.normalized_value,
                }

        if result.warning:
            warnings.append(result.warning)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "normalized": normalized,
    }


def auto_fix_market_data(market_data: Dict[str, Dict]) -> Tuple[Dict, List[str]]:
    """
    自動修正 market_data 中的百分比問題

    Args:
        market_data: edition_pack.market_data

    Returns:
        (fixed_market_data, fix_log)
    """
    fixed = dict(market_data)
    fix_log = []

    for ticker, data in fixed.items():
        change_pct = data.get("change_pct")
        if change_pct is None:
            continue

        # 偵測格式
        detected = detect_percent_format(change_pct)

        if detected == "decimal":
            # 自動修正：小數形式 → 百分比形式
            original = change_pct
            normalized = change_pct * 100
            fixed[ticker] = {**data, "change_pct": normalized}
            fix_log.append(f"{ticker}: Fixed change_pct from {original:.6f} to {normalized:.2f}%")
            logger.warning(f"Auto-fixed {ticker} change_pct: {original:.6f} → {normalized:.2f}%")

    return fixed, fix_log


# =============================================================================
# Quality Gate Integration
# =============================================================================

def percent_quality_gate(edition_pack: Dict) -> Dict[str, Any]:
    """
    P0-2: 百分比品質檢查 Gate

    Args:
        edition_pack: 完整的 edition_pack

    Returns:
        {
            "gate": "percent_contract",
            "passed": bool,
            "errors": [],
            "warnings": [],
            "auto_fixed": int,
        }
    """
    market_data = edition_pack.get("market_data", {})

    validation = validate_market_data(market_data)

    # 計算需要 auto-fix 的數量
    auto_fixed = len(validation["normalized"])

    return {
        "gate": "percent_contract",
        "passed": validation["valid"],
        "errors": validation["errors"],
        "warnings": validation["warnings"],
        "auto_fixed": auto_fixed,
        "details": {
            "tickers_checked": len(market_data),
            "normalized_values": validation["normalized"],
        },
    }


# =============================================================================
# Format 函數（統一格式化）
# =============================================================================

def format_percent(value: float, precision: int = 2, include_sign: bool = True) -> str:
    """
    統一的百分比格式化函數

    Args:
        value: 百分比值（3.76 = 3.76%）
        precision: 小數位數
        include_sign: 是否包含正號

    Returns:
        格式化的字串
    """
    if value is None:
        return "N/A"

    if include_sign and value >= 0:
        return f"+{value:.{precision}f}%"
    else:
        return f"{value:.{precision}f}%"


def format_percent_badge(value: float) -> str:
    """
    格式化百分比為帶顏色的 badge（用於 HTML）

    Args:
        value: 百分比值

    Returns:
        HTML badge string
    """
    if value is None:
        return '<span class="badge badge-neutral">N/A</span>'

    color = "green" if value >= 0 else "red"
    sign = "+" if value >= 0 else ""

    return f'<span class="badge badge-{color}">{sign}{value:.2f}%</span>'

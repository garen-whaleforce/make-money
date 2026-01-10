"""Feature image generator for Ghost posts.

生成 1200x630 的 Open Graph 尺寸圖片，用於社群分享預覽。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

from ..utils.logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# 字型設定 - 支援中文
# ============================================================================
# 優先順序: 思源黑體 > 蘋方 > 微軟正黑 > 系統預設
CJK_FONTS = [
    "Noto Sans TC",
    "Noto Sans CJK TC",
    "PingFang TC",
    "Microsoft JhengHei",
    "Heiti TC",
    "Arial Unicode MS",
    "DejaVu Sans",
]

def _get_cjk_font() -> Optional[str]:
    """找到系統上可用的中文字型"""
    available = {f.name for f in fm.fontManager.ttflist}
    for font in CJK_FONTS:
        if font in available:
            return font
    return None

# 設定 matplotlib 預設字型
_cjk_font = _get_cjk_font()
if _cjk_font:
    plt.rcParams["font.family"] = _cjk_font
    plt.rcParams["font.sans-serif"] = [_cjk_font] + plt.rcParams.get("font.sans-serif", [])
    logger.info(f"Using CJK font: {_cjk_font}")
else:
    logger.warning("No CJK font found, Chinese characters may not render correctly")

plt.rcParams["axes.unicode_minus"] = False  # 正確顯示負號

# ============================================================================
# 品牌色彩
# ============================================================================
BRAND_COLORS = {
    "primary": "#1e3a5f",      # 深藍 - 主色
    "secondary": "#3b82f6",    # 亮藍
    "accent": "#f59e0b",       # 金色 - 強調
    "success": "#10b981",      # 綠色 - 漲
    "danger": "#ef4444",       # 紅色 - 跌
    "neutral": "#6b7280",      # 灰色
    "background": "#0f172a",   # 深色背景
    "surface": "#1e293b",      # 卡片背景
    "text": "#f8fafc",         # 白色文字
    "text_muted": "#94a3b8",   # 次要文字
}


@dataclass
class FeatureImageResult:
    """Result for a generated feature image."""

    path: Path
    alt_text: str
    kind: str


def _parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip().replace(",", "")
    multiplier = 1.0
    if text.endswith("%"):
        text = text[:-1]
    if text.endswith("T"):
        multiplier = 1e12
        text = text[:-1]
    elif text.endswith("B"):
        multiplier = 1e9
        text = text[:-1]
    elif text.endswith("M"):
        multiplier = 1e6
        text = text[:-1]
    if text.startswith("$"):
        text = text[1:]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _get_primary_ticker(post_data: dict) -> str:
    """從 post_data 取得主要 ticker

    優先順序:
    1. meta.deep_dive_ticker
    2. deep_dive_ticker (頂層)
    3. 從 key_numbers 標籤中擷取 ticker
    4. tickers_mentioned[0] (最後備選)
    """
    # 檢查 meta.deep_dive_ticker
    meta = post_data.get("meta") or {}
    ticker = meta.get("deep_dive_ticker")
    if ticker:
        return ticker

    # 檢查頂層 deep_dive_ticker
    ticker = post_data.get("deep_dive_ticker")
    if ticker:
        return ticker

    # 從 key_numbers 標籤中擷取 ticker (例如 "AVGO 現價" -> "AVGO")
    key_numbers = post_data.get("key_numbers") or []
    for kn in key_numbers:
        label = kn.get("label", "")
        # 標籤格式通常是 "TICKER 描述"
        parts = label.split()
        if parts and parts[0].isupper() and len(parts[0]) <= 5:
            return parts[0]

    # 最後備選
    tickers = post_data.get("tickers_mentioned") or []
    return tickers[0] if tickers else ""


def _save_fig(fig: plt.Figure, output_path: Path, facecolor: str = "white") -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=facecolor, pad_inches=0)
    plt.close(fig)


def _hex_to_rgb(hex_color: str) -> tuple:
    """Convert hex color to RGB tuple (0-1 range)"""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) / 255 for i in (0, 2, 4))


def _create_gradient_background(ax, color1: str, color2: str, direction: str = "vertical"):
    """Create gradient background on axes"""
    import matplotlib.colors as mcolors

    # Create gradient array
    if direction == "vertical":
        gradient = np.linspace(0, 1, 256).reshape(-1, 1)
    else:
        gradient = np.linspace(0, 1, 256).reshape(1, -1)

    # Create colormap
    c1 = _hex_to_rgb(color1)
    c2 = _hex_to_rgb(color2)
    cmap = mcolors.LinearSegmentedColormap.from_list("gradient", [c1, c2])

    ax.imshow(gradient, aspect='auto', cmap=cmap, extent=[0, 1, 0, 1], zorder=0)


def _render_branded_title_card(
    post_data: dict,
    output_path: Path,
    post_type: str = "flash",
) -> Optional[FeatureImageResult]:
    """生成品牌風格的標題卡片圖 (1200x630 OG 尺寸)

    設計風格：
    - 深色漸層背景 (深藍到深紫)
    - 左側：主標題 + 副標題
    - 右側：關鍵數字卡片 (最多3個)
    - 底部：品牌 logo + 日期
    """
    # 取得資料
    title = post_data.get("title", "Daily Deep Brief")
    ticker = _get_primary_ticker(post_data)

    # 取得關鍵數字 (最多3個)
    key_numbers = post_data.get("key_numbers", [])[:3]

    # 決定副標題
    post_type_labels = {
        "flash": "市場快報 | Flash Brief",
        "earnings": "財報分析 | Earnings Analysis",
        "deep": "深度研究 | Deep Dive",
    }
    subtitle = post_type_labels.get(post_type, "Daily Deep Brief")

    # 建立圖形 (1200x630 pixels at 150 dpi = 8x4.2 inches)
    fig = plt.figure(figsize=(8, 4.2), facecolor=BRAND_COLORS["background"])
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # 背景漸層
    _create_gradient_background(ax, BRAND_COLORS["background"], "#1a1a2e")

    # 左上角品牌標籤
    ax.text(
        0.05, 0.92,
        "ROCKET SCREENER",
        fontsize=11,
        color=BRAND_COLORS["accent"],
        fontweight="bold",
        va="top",
    )

    # 文章類型標籤
    type_colors = {
        "flash": BRAND_COLORS["secondary"],
        "earnings": BRAND_COLORS["accent"],
        "deep": BRAND_COLORS["success"],
    }
    ax.add_patch(plt.Rectangle(
        (0.05, 0.78), 0.18, 0.08,
        facecolor=type_colors.get(post_type, BRAND_COLORS["secondary"]),
        edgecolor="none",
        alpha=0.9,
        zorder=2,
    ))
    ax.text(
        0.14, 0.82,
        subtitle.split("|")[0].strip().upper(),
        fontsize=9,
        color="white",
        fontweight="bold",
        ha="center",
        va="center",
        zorder=3,
    )

    # 決定是否顯示關鍵數字卡片
    show_cards = bool(key_numbers)

    # 主標題處理 - 支援兩行顯示
    display_title = title
    # 尋找合適的斷點換行 (在標點符號處)
    line1_max = 18 if show_cards else 28
    if len(title) > line1_max:
        # 找第一行的斷點
        break_found = False
        for i in range(line1_max - 2, min(line1_max + 5, len(title))):
            if i < len(title) and title[i] in "，、：；。 ":
                line1 = title[:i+1].strip()
                line2 = title[i+1:].strip()
                # 第二行也可能需要截斷
                line2_max = 20 if show_cards else 30
                if len(line2) > line2_max:
                    line2 = line2[:line2_max-1] + "..."
                display_title = line1 + "\n" + line2
                break_found = True
                break
        if not break_found:
            # 沒找到標點，直接截斷
            display_title = title[:line1_max + 15] + "..."

    ax.text(
        0.05, 0.68,
        display_title,
        fontsize=16 if show_cards else 20,
        color=BRAND_COLORS["text"],
        fontweight="bold",
        va="top",
        ha="left",
        linespacing=1.5,
    )

    # Ticker 標籤 (放在標題下方左側)
    if ticker:
        ax.text(
            0.05, 0.18,
            f"${ticker}",
            fontsize=22,
            color=BRAND_COLORS["accent"],
            fontweight="bold",
            va="center",
        )

    # 右側關鍵數字卡片 (只在有數據時顯示)
    if show_cards:
        card_y_positions = [0.70, 0.46, 0.22]
        card_colors = [
            BRAND_COLORS["secondary"],
            BRAND_COLORS["success"],
            BRAND_COLORS["accent"],
        ]

        for i, kn in enumerate(key_numbers):
            if i >= 3:
                break

            y_pos = card_y_positions[i]

            # 卡片背景
            ax.add_patch(plt.Rectangle(
                (0.58, y_pos - 0.09), 0.38, 0.18,
                facecolor=BRAND_COLORS["surface"],
                edgecolor=card_colors[i],
                linewidth=2,
                alpha=0.9,
                zorder=2,
            ))

            # 數值
            value = str(kn.get("value", ""))
            ax.text(
                0.77, y_pos + 0.02,
                value,
                fontsize=15,
                color=BRAND_COLORS["text"],
                fontweight="bold",
                ha="center",
                va="center",
                zorder=3,
            )

            # 標籤
            label = kn.get("label", "")
            if len(label) > 18:
                label = label[:18] + "..."
            ax.text(
                0.77, y_pos - 0.05,
                label,
                fontsize=8,
                color=BRAND_COLORS["text_muted"],
                ha="center",
                va="center",
                zorder=3,
            )

    # 底部日期
    from datetime import datetime
    date_str = datetime.now().strftime("%Y-%m-%d")
    ax.text(
        0.95, 0.05,
        date_str,
        fontsize=9,
        color=BRAND_COLORS["text_muted"],
        ha="right",
        va="bottom",
    )

    # 底部分隔線
    ax.axhline(y=0.12, xmin=0.05, xmax=0.95, color=BRAND_COLORS["surface"], linewidth=1)

    _save_fig(fig, output_path, facecolor=BRAND_COLORS["background"])
    alt_text = f"{post_type.title()} - {title}"
    return FeatureImageResult(path=output_path, alt_text=alt_text, kind="branded_title")


def _render_flash_snapshot(post_data: dict, output_path: Path) -> Optional[FeatureImageResult]:
    """Flash 文章的 feature image - 使用品牌標題卡片"""
    return _render_branded_title_card(post_data, output_path, post_type="flash")


def _render_earnings_valuation(post_data: dict, output_path: Path) -> Optional[FeatureImageResult]:
    # Try multiple sources for valuation data
    # Priority: valuation_scenarios > valuation_quick_view > valuation_detailed > valuation
    valuation = None
    scenarios = {}

    # Source 1: valuation_scenarios (earnings posts)
    vs = post_data.get("valuation_scenarios") or {}
    if vs.get("scenarios"):
        scenarios_list = vs.get("scenarios", [])
        # Convert list format to dict format
        for s in scenarios_list:
            case = s.get("case", "").lower()
            if case in ["bear", "base", "bull"]:
                scenarios[case] = {"target_price": s.get("target_price")}
        valuation = {"current_metrics": vs.get("current_metrics", {})}

    # Source 2: valuation_quick_view (deep posts)
    if not scenarios:
        vqv = post_data.get("valuation_quick_view") or {}
        if vqv.get("bear_target") or vqv.get("base_target") or vqv.get("bull_target"):
            scenarios = {
                "bear": {"target_price": vqv.get("bear_target")},
                "base": {"target_price": vqv.get("base_target")},
                "bull": {"target_price": vqv.get("bull_target")},
            }
            valuation = {"current_metrics": {"price": vqv.get("current_price")}}

    # Source 3: valuation_detailed.scenarios (deep posts)
    if not scenarios:
        vd = post_data.get("valuation_detailed") or {}
        vd_scenarios = vd.get("scenarios", [])
        for s in vd_scenarios:
            scenario_name = s.get("scenario", "").lower()
            if "熊" in scenario_name or "bear" in scenario_name:
                scenarios["bear"] = {"target_price": s.get("target")}
            elif "基" in scenario_name or "base" in scenario_name:
                scenarios["base"] = {"target_price": s.get("target")}
            elif "牛" in scenario_name or "bull" in scenario_name:
                scenarios["bull"] = {"target_price": s.get("target")}

    # Source 4: valuation (fallback)
    if not scenarios:
        valuation = post_data.get("valuation") or {}
        scenarios = valuation.get("scenarios") or {}

    if valuation is None:
        valuation = post_data.get("valuation") or {}

    ticker = _get_primary_ticker(post_data)

    labels = []
    values = []
    colors = []
    palette = {
        "bear": "#ef4444",
        "base": "#3b82f6",
        "bull": "#10b981",
    }

    for key in ["bear", "base", "bull"]:
        scenario = scenarios.get(key) or {}
        target = scenario.get("target_price")
        target_value = _parse_float(target)
        if target_value is None:
            continue
        labels.append(key.title())
        values.append(target_value)
        colors.append(palette.get(key, "#6b7280"))

    if len(values) < 2:
        return None

    current_price = None
    current_metrics = valuation.get("current_metrics") or {}
    current_price = _parse_float(current_metrics.get("price"))
    if current_price is None:
        market_data = post_data.get("market_data") or {}
        if ticker and ticker in market_data:
            current_price = _parse_float(market_data[ticker].get("price"))

    fig, ax = plt.subplots(figsize=(12, 6.3))
    fig.patch.set_facecolor("white")

    bars = ax.barh(labels, values, color=colors)
    ax.set_xlabel("Target Price")
    ax.set_title(f"Valuation Scenarios {ticker}".strip())

    for bar, value in zip(bars, values):
        ax.text(value, bar.get_y() + bar.get_height() / 2, f"{value:.2f}", va="center", ha="left", fontsize=10)

    if current_price is not None:
        ax.axvline(current_price, color="#111827", linestyle="--", linewidth=1.4)
        ax.text(current_price, len(labels) - 0.3, "Current", rotation=90, va="bottom", ha="center", fontsize=9)

    _save_fig(fig, output_path)
    alt_text = f"Valuation scenarios for {ticker}".strip()
    return FeatureImageResult(path=output_path, alt_text=alt_text, kind="valuation_scenarios")


def _render_deep_sensitivity(post_data: dict, output_path: Path) -> Optional[FeatureImageResult]:
    sensitivity = post_data.get("sensitivity_matrix") or {}
    price_matrix = sensitivity.get("price_matrix")
    if not price_matrix:
        return None

    fig, ax = plt.subplots(figsize=(12, 6.3))
    fig.patch.set_facecolor("white")
    cax = ax.imshow(price_matrix, cmap="YlGnBu")
    fig.colorbar(cax, ax=ax, fraction=0.046, pad=0.04)

    eps_range = sensitivity.get("eps_range") or []
    pe_range = sensitivity.get("pe_range") or []
    if eps_range:
        ax.set_yticks(range(len(eps_range)))
        ax.set_yticklabels([str(v) for v in eps_range])
        ax.set_ylabel("EPS")
    if pe_range:
        ax.set_xticks(range(len(pe_range)))
        ax.set_xticklabels([str(v) for v in pe_range], rotation=45, ha="right")
        ax.set_xlabel("P/E")

    ticker = _get_primary_ticker(post_data)
    ax.set_title(f"Sensitivity Matrix {ticker}".strip())

    _save_fig(fig, output_path)
    alt_text = f"Sensitivity matrix for {ticker}".strip()
    return FeatureImageResult(path=output_path, alt_text=alt_text, kind="sensitivity_matrix")


def _render_peer_valuation(post_data: dict, output_path: Path) -> Optional[FeatureImageResult]:
    peer = post_data.get("peer_comparison") or {}
    peers = peer.get("peers") or []
    labels = []
    values = []
    for item in peers:
        ticker = item.get("ticker") or item.get("symbol") or ""
        pe_value = _parse_float(item.get("pe_ttm") or item.get("pe_forward"))
        if ticker and pe_value is not None:
            labels.append(ticker)
            values.append(pe_value)
        if len(labels) >= 6:
            break

    if len(values) < 2:
        return None

    fig, ax = plt.subplots(figsize=(12, 6.3))
    fig.patch.set_facecolor("white")
    bars = ax.bar(labels, values, color="#3b82f6")
    ax.set_ylabel("P/E")
    ax.set_title("Peer Valuation Comparison")

    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value, f"{value:.1f}", ha="center", va="bottom", fontsize=9)

    _save_fig(fig, output_path)
    alt_text = "Peer valuation comparison"
    return FeatureImageResult(path=output_path, alt_text=alt_text, kind="peer_valuation")


def generate_feature_image(
    post_type: str,
    post_data: dict,
    output_dir: str = "out/feature_images",
) -> Optional[FeatureImageResult]:
    """Generate feature image for a given post type.

    所有文章類型都使用統一的品牌標題卡片設計，
    包含標題、ticker、關鍵數字等資訊。
    """
    slug = post_data.get("slug") or f"{post_type}-post"
    output_path = Path(output_dir) / f"{slug}.png"

    # 統一使用品牌標題卡片
    return _render_branded_title_card(post_data, output_path, post_type=post_type)

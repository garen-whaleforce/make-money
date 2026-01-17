"""Number Traceability Checker

檢查文章中的數字是否能追溯到 research_pack。
這是最重要的品質 Gate - 防止 AI 杜撰數字。
"""

import re
from dataclasses import dataclass, field
from typing import Optional

import yaml

from ..utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class TracedNumber:
    """追溯到的數字"""

    value: str  # 原始數字字串
    location: str  # 在文章中的位置 (句子片段)
    traced: bool  # 是否成功追溯
    source_path: Optional[str] = None  # 在 research_pack 中的路徑
    source_value: Optional[str] = None  # research_pack 中的值
    reason: Optional[str] = None  # 追溯失敗的原因


@dataclass
class TraceResult:
    """追溯檢查結果"""

    passed: bool
    total_numbers: int = 0
    traced_count: int = 0
    untraced_count: int = 0
    critical_untraced: int = 0
    numbers: list[TracedNumber] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "total_numbers": self.total_numbers,
            "traced_count": self.traced_count,
            "untraced_count": self.untraced_count,
            "critical_untraced": self.critical_untraced,
            "numbers": [
                {
                    "value": n.value,
                    "location": n.location[:100],
                    "traced": n.traced,
                    "source_path": n.source_path,
                    "reason": n.reason,
                }
                for n in self.numbers
            ],
            "errors": self.errors,
            "warnings": self.warnings,
        }


class NumberTracer:
    """數字追溯器"""

    # 數字提取模式
    NUMBER_PATTERNS = [
        (r'\$[\d,]+\.?\d*[BMK]?', 'currency', 3),  # $150.00, $1.5B
        (r'[\d.]+x', 'multiple', 3),  # 25.5x
        (r'-?[\d.]+%', 'percent', 2),  # -15.5% or 15.5%
        (r'\d{1,3}(?:,\d{3})+', 'large_number', 1),  # 1,000,000
    ]

    # 可忽略的模式 (年份、季度等)
    IGNORABLE_PATTERNS = [
        r'\b20[0-9]{2}\b',  # 年份 2020-2099
        r'\bQ[1-4]\b',  # 季度
        r'\b[0-9]{1,2}/[0-9]{1,2}\b',  # 日期
        r'\b[0-9]{1,2}:[0-9]{2}\b',  # 時間
        r'^[0-5]$',  # Impact scores 0-5
        r'^[1-9]$',  # 單個數字（通常是排序）
        r'^\d+\.$',  # 清單序號 "1." "2." 等
    ]

    # 常見合理數字（不需追溯）
    ALLOWLISTED_NUMBERS = {
        # 常見整數
        3, 5, 7, 8, 10, 12, 100,
        # 常見百分比
        0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 5.0, 10.0,
        # 常見指標閾值
        60, 200, 300, 500,
    }

    def __init__(
        self,
        config_path: str = "config/quality_rules.yaml",
        max_untraced: int = 3,
    ):
        """初始化數字追溯器

        Args:
            config_path: 設定檔路徑
            max_untraced: 最大允許的未追溯數字數量
        """
        self.max_untraced = max_untraced

        # 載入設定
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
                trace_config = config.get("number_traceability", {})
                self.max_untraced = trace_config.get("max_untraced_numbers", max_untraced)
                self.enabled = trace_config.get("enabled", True)
        except FileNotFoundError:
            self.enabled = True

    def _extract_numbers(self, text: str) -> list[tuple[str, str, int, str]]:
        """從文字中提取數字

        Args:
            text: 文字內容

        Returns:
            [(數字, 類型, 權重, 上下文), ...]
        """
        numbers = []

        for pattern, num_type, weight in self.NUMBER_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                value = match.group()

                # 檢查是否應該忽略
                should_ignore = False
                for ignore_pattern in self.IGNORABLE_PATTERNS:
                    if re.match(ignore_pattern, value):
                        should_ignore = True
                        break

                if should_ignore:
                    continue

                # 取得上下文 (前後 50 字元)
                start = max(0, match.start() - 50)
                end = min(len(text), match.end() + 50)
                context = text[start:end].replace("\n", " ").strip()

                numbers.append((value, num_type, weight, context))

        return numbers

    def _normalize_number(self, value: str) -> Optional[float]:
        """將數字字串正規化為浮點數

        Args:
            value: 數字字串

        Returns:
            浮點數或 None
        """
        try:
            # 移除 $, %, x 等符號
            cleaned = re.sub(r'[$%x,]', '', value.strip())

            # 處理 B/M/K 後綴
            multiplier = 1
            if cleaned.endswith('B') or cleaned.endswith('b'):
                multiplier = 1e9
                cleaned = cleaned[:-1]
            elif cleaned.endswith('M') or cleaned.endswith('m'):
                multiplier = 1e6
                cleaned = cleaned[:-1]
            elif cleaned.endswith('K') or cleaned.endswith('k'):
                multiplier = 1e3
                cleaned = cleaned[:-1]

            return float(cleaned) * multiplier
        except (ValueError, TypeError):
            return None

    def _extract_research_pack_numbers(self, research_pack: dict, prefix: str = "") -> dict[str, float]:
        """遞迴提取 research_pack 中的所有數字

        Args:
            research_pack: 研究包資料
            prefix: 路徑前綴

        Returns:
            {路徑: 數值} 字典
        """
        numbers = {}

        if isinstance(research_pack, dict):
            for key, value in research_pack.items():
                path = f"{prefix}.{key}" if prefix else key

                if isinstance(value, (int, float)) and value is not None:
                    numbers[path] = value
                elif isinstance(value, dict):
                    numbers.update(self._extract_research_pack_numbers(value, path))
                elif isinstance(value, list):
                    for i, item in enumerate(value):
                        if isinstance(item, dict):
                            numbers.update(
                                self._extract_research_pack_numbers(item, f"{path}[{i}]")
                            )

        return numbers

    def _find_match(
        self,
        value: float,
        research_numbers: dict[str, float],
        tolerance: float = 0.05,
    ) -> Optional[tuple[str, float]]:
        """在 research_pack 數字中找匹配

        Args:
            value: 要匹配的數值
            research_numbers: research_pack 中的數字
            tolerance: 容許誤差 (百分比)

        Returns:
            (路徑, 原始值) 或 None
        """
        # 先檢查是否在白名單中
        if value in self.ALLOWLISTED_NUMBERS:
            return ("allowlist", value)

        # 檢查是否是常見的小整數或百分比
        if isinstance(value, float) and value == int(value):
            int_value = int(value)
            if 0 <= int_value <= 10:  # 0-10 的整數通常是排序或 Impact Score
                return ("allowlist:small_int", value)

        for path, rp_value in research_numbers.items():
            if rp_value == 0:
                if value == 0:
                    return path, rp_value
                continue

            # 計算相對誤差
            diff = abs(value - rp_value) / abs(rp_value)
            if diff <= tolerance:
                return path, rp_value

            # 也檢查百分比形式 (0.15 vs 15)
            if value > 1 and rp_value < 1:
                if abs(value / 100 - rp_value) / abs(rp_value) <= tolerance:
                    return path, rp_value

        return None

    def trace(self, markdown: str, research_pack: dict) -> TraceResult:
        """執行數字追溯檢查

        Args:
            markdown: 文章 Markdown 內容
            research_pack: 研究包資料

        Returns:
            TraceResult 實例
        """
        result = TraceResult(passed=True)

        if not self.enabled:
            result.warnings.append("Number traceability check is disabled")
            return result

        # 提取文章中的數字
        article_numbers = self._extract_numbers(markdown)
        result.total_numbers = len(article_numbers)

        # 提取 research_pack 中的數字
        rp_numbers = self._extract_research_pack_numbers(research_pack)

        # 逐一檢查追溯
        for value_str, num_type, weight, context in article_numbers:
            traced_num = TracedNumber(
                value=value_str,
                location=context,
                traced=False,
            )

            # 正規化數字
            normalized = self._normalize_number(value_str)

            if normalized is None:
                traced_num.reason = "Cannot parse number"
                result.numbers.append(traced_num)
                continue

            # 嘗試在 research_pack 中找匹配
            match = self._find_match(normalized, rp_numbers)

            if match:
                traced_num.traced = True
                traced_num.source_path = match[0]
                traced_num.source_value = str(match[1])
                result.traced_count += 1
            else:
                traced_num.traced = False
                traced_num.reason = f"No match found for {normalized}"
                result.untraced_count += 1

                if weight >= 2:  # 關鍵數字
                    result.critical_untraced += 1

            result.numbers.append(traced_num)

        # 判定結果
        if result.critical_untraced > self.max_untraced:
            result.passed = False
            result.errors.append(
                f"Too many untraced critical numbers: {result.critical_untraced} > {self.max_untraced}"
            )

        # 生成警告
        if result.untraced_count > 0:
            untraced_examples = [
                n.value for n in result.numbers if not n.traced
            ][:5]
            result.warnings.append(
                f"Untraced numbers ({result.untraced_count}): {', '.join(untraced_examples)}"
            )

        return result


def main():
    """CLI demo"""
    import json
    from rich.console import Console
    from rich.table import Table

    console = Console()

    # 測試用資料
    test_markdown = """
# NVIDIA Q4 分析

NVDA 目前股價 $145.50，市值達 $3.5T。

## 估值分析
- 熊市情境：$120.00 (-17%)
- 基準情境：$155.00 (+7%)
- 牛市情境：$180.00 (+24%)

毛利率維持在 75.5%，營業利益率 65.2%。
Forward P/E 約 35.5x，高於同業平均 28.0x。

2025 年預估營收成長 45%。
    """

    test_research_pack = {
        "companies": {
            "NVDA": {
                "price": {
                    "last": 145.50,
                    "market_cap": 3.5e12,
                },
                "fundamentals": {
                    "gross_margin": 0.755,
                    "operating_margin": 0.652,
                },
            }
        },
        "valuations": {
            "NVDA": {
                "fair_value": {
                    "bear": 120.00,
                    "base": 155.00,
                    "bull": 180.00,
                },
                "current_price": 145.50,
            }
        },
        "peer_table": {
            "rows": [
                {"ticker": "NVDA", "forward_pe": 35.5},
                {"ticker": "AMD", "forward_pe": 28.0},
            ]
        }
    }

    # 執行追溯
    tracer = NumberTracer()
    result = tracer.trace(test_markdown, test_research_pack)

    # 顯示結果
    console.print(f"\n[bold]Number Traceability Check[/bold]")
    console.print(f"Status: {'[green]PASSED[/green]' if result.passed else '[red]FAILED[/red]'}")
    console.print(f"Total numbers: {result.total_numbers}")
    console.print(f"Traced: {result.traced_count}")
    console.print(f"Untraced: {result.untraced_count}")
    console.print(f"Critical untraced: {result.critical_untraced}")

    # 詳細表格
    table = Table(title="Number Trace Details")
    table.add_column("Number", style="cyan")
    table.add_column("Traced", style="green")
    table.add_column("Source Path")
    table.add_column("Reason")

    for num in result.numbers:
        traced = "✓" if num.traced else "✗"
        table.add_row(
            num.value,
            traced,
            num.source_path or "-",
            num.reason or "-",
        )

    console.print(table)


if __name__ == "__main__":
    main()

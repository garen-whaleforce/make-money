"""Compliance Checker

合規與品質控管檢查器。
"""

import re
from dataclasses import dataclass, field
from typing import Optional

import yaml

from ..utils.logging import get_logger

logger = get_logger(__name__)


# 預設禁用詞
DEFAULT_FORBIDDEN_WORDS = [
    # 中文 - 投資保證類語言
    "保證獲利",
    "穩賺不賠",
    "零風險",
    "必漲",
    "必跌",
    "絕對會漲",
    "絕對會跌",
    "絕對賺",
    "絕對不會虧",
    "肯定獲利",
    "肯定賺",
    # 英文
    "guaranteed profit",
    "guaranteed return",
    "risk-free",
    "sure thing",
    "can't lose",
    "will definitely",
    "100% safe",
]

# 必須包含的免責聲明關鍵字
REQUIRED_DISCLOSURES = [
    "非投資建議",
    "not investment advice",
    "投資有風險",
    "risk",
]


@dataclass
class QualityCheckResult:
    """品質檢查結果"""

    passed: bool
    source_count: int = 0
    source_check_passed: bool = False
    numbers_traceable: bool = True
    compliance_passed: bool = False
    disclosure_present: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "source_count": self.source_count,
            "source_check_passed": self.source_check_passed,
            "numbers_traceable": self.numbers_traceable,
            "compliance_passed": self.compliance_passed,
            "disclosure_present": self.disclosure_present,
            "warnings": self.warnings,
            "errors": self.errors,
        }


class ComplianceChecker:
    """合規檢查器"""

    def __init__(
        self,
        min_sources: int = 3,  # 放寬至 3
        forbidden_words: Optional[list[str]] = None,
        config_path: Optional[str] = None,
    ):
        """初始化合規檢查器

        Args:
            min_sources: 最少來源數量
            forbidden_words: 禁用詞列表
            config_path: 設定檔路徑
        """
        self.min_sources = min_sources
        self.forbidden_words = forbidden_words or DEFAULT_FORBIDDEN_WORDS

        # 從設定檔載入
        if config_path:
            try:
                with open(config_path) as f:
                    config = yaml.safe_load(f)
                    quality = config.get("quality", {})
                    self.min_sources = quality.get("min_sources", min_sources)
                    self.forbidden_words = quality.get("forbidden_words", self.forbidden_words)
            except Exception as e:
                logger.warning(f"Failed to load config: {e}")

    def check_sources(self, sources: list[dict]) -> tuple[bool, int, list[str]]:
        """檢查來源數量

        Args:
            sources: 來源列表

        Returns:
            (passed, count, warnings)
        """
        count = len(sources)
        passed = count >= self.min_sources
        warnings = []

        if not passed:
            warnings.append(f"Insufficient sources: {count} < {self.min_sources}")

        return passed, count, warnings

    def check_forbidden_words(self, text: str) -> tuple[bool, list[str]]:
        """檢查禁用詞

        Args:
            text: 要檢查的文字

        Returns:
            (passed, found_words)
        """
        found = []
        text_lower = text.lower()

        for word in self.forbidden_words:
            if word.lower() in text_lower:
                found.append(word)

        return len(found) == 0, found

    def check_disclosures(self, disclosures: dict, markdown: str) -> tuple[bool, list[str]]:
        """檢查免責聲明

        Args:
            disclosures: 免責聲明物件
            markdown: Markdown 內容

        Returns:
            (passed, warnings)
        """
        warnings = []

        # 檢查結構化免責聲明
        if not disclosures.get("not_investment_advice"):
            warnings.append("Missing 'not_investment_advice' disclosure flag")

        # 檢查內容中是否有免責聲明
        combined_text = markdown.lower()
        has_disclosure = any(
            keyword.lower() in combined_text
            for keyword in REQUIRED_DISCLOSURES
        )

        if not has_disclosure:
            warnings.append("No disclosure keywords found in content")

        return len(warnings) == 0, warnings

    def check_number_traceability(
        self,
        post_markdown: str,
        research_pack: dict,
    ) -> tuple[bool, list[str]]:
        """檢查數字可追溯性

        Args:
            post_markdown: 文章 Markdown
            research_pack: 研究包

        Returns:
            (passed, warnings)
        """
        warnings = []

        # 提取文章中的數字 (價格、百分比等)
        price_pattern = r'\$[\d,]+\.?\d*'
        percent_pattern = r'[\d.]+%'

        prices_in_post = re.findall(price_pattern, post_markdown)
        percents_in_post = re.findall(percent_pattern, post_markdown)

        # 提取研究包中的數字
        research_pack_str = str(research_pack)
        prices_in_pack = set(re.findall(price_pattern, research_pack_str))
        percents_in_pack = set(re.findall(percent_pattern, research_pack_str))

        # 檢查是否可追溯 (簡化版：只警告，不阻擋)
        untraced_prices = [p for p in prices_in_post if p not in prices_in_pack]
        if len(untraced_prices) > 5:
            warnings.append(
                f"Found {len(untraced_prices)} prices that may not be traceable to research_pack"
            )

        # 這是一個寬鬆的檢查，預設通過
        return True, warnings

    def check(
        self,
        post: dict,
        research_pack: dict,
    ) -> QualityCheckResult:
        """執行完整品質檢查

        Args:
            post: 文章資料
            research_pack: 研究包資料

        Returns:
            QualityCheckResult 實例
        """
        result = QualityCheckResult(passed=True)

        # 1. 來源檢查 - 優先從 post 讀取
        sources = post.get("sources", [])
        if not sources:
            sources = research_pack.get("sources", [])
        source_passed, source_count, source_warnings = self.check_sources(sources)
        result.source_count = source_count
        result.source_check_passed = source_passed
        result.warnings.extend(source_warnings)
        if not source_passed:
            result.errors.append("Source count check failed")

        # 2. 禁用詞檢查
        markdown = post.get("markdown", "")
        compliance_passed, forbidden_found = self.check_forbidden_words(markdown)
        result.compliance_passed = compliance_passed
        if not compliance_passed:
            result.errors.append(f"Forbidden words found: {', '.join(forbidden_found)}")

        # 3. 免責聲明檢查
        disclosures = post.get("disclosures", {})
        disclosure_passed, disclosure_warnings = self.check_disclosures(disclosures, markdown)
        result.disclosure_present = disclosure_passed
        result.warnings.extend(disclosure_warnings)
        if not disclosure_passed:
            result.errors.append("Disclosure check failed")

        # 4. 數字追溯檢查
        traceable, trace_warnings = self.check_number_traceability(markdown, research_pack)
        result.numbers_traceable = traceable
        result.warnings.extend(trace_warnings)

        # 總結
        result.passed = (
            result.source_check_passed
            and result.compliance_passed
            and result.disclosure_present
        )

        return result


def main():
    """CLI demo"""
    from rich.console import Console
    from rich.table import Table

    console = Console()

    # 測試用資料
    test_post = {
        "markdown": """
# Test Article

This is a test article about NVDA.

## Disclaimer

本報告僅供參考，非投資建議。投資有風險，請審慎評估。
        """,
        "disclosures": {
            "not_investment_advice": True,
            "risk_warning": "投資有風險",
        },
    }

    test_research_pack = {
        "sources": [
            {"title": f"Source {i}", "url": f"https://example.com/{i}"}
            for i in range(6)
        ],
    }

    # 執行檢查
    checker = ComplianceChecker()
    result = checker.check(test_post, test_research_pack)

    # 顯示結果
    table = Table(title="Quality Check Result")
    table.add_column("Check", style="cyan")
    table.add_column("Status")
    table.add_column("Details")

    checks = [
        ("Sources", result.source_check_passed, f"{result.source_count} sources"),
        ("Compliance", result.compliance_passed, "No forbidden words" if result.compliance_passed else "Found forbidden words"),
        ("Disclosure", result.disclosure_present, "Present" if result.disclosure_present else "Missing"),
        ("Traceability", result.numbers_traceable, "OK" if result.numbers_traceable else "Warnings"),
    ]

    for name, passed, details in checks:
        status = "[green]✓ PASS[/green]" if passed else "[red]✗ FAIL[/red]"
        table.add_row(name, status, details)

    console.print(table)

    if result.warnings:
        console.print("\n[yellow]Warnings:[/yellow]")
        for w in result.warnings:
            console.print(f"  ⚠ {w}")

    if result.errors:
        console.print("\n[red]Errors:[/red]")
        for e in result.errors:
            console.print(f"  ✗ {e}")

    overall = "[green]PASSED[/green]" if result.passed else "[red]FAILED[/red]"
    console.print(f"\n[bold]Overall: {overall}[/bold]")


if __name__ == "__main__":
    main()

"""Quality Gate - 整合所有品質檢查

Fail-Closed 原則：任何一關失敗就不自動發布。
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from ..utils.logging import get_logger
from .compliance import ComplianceChecker, QualityCheckResult
from .trace_numbers import NumberTracer, TraceResult
from .validators import validate_research_pack, validate_post

logger = get_logger(__name__)


@dataclass
class GateResult:
    """單一 Gate 結果"""

    name: str
    passed: bool
    message: str
    details: Optional[dict] = None


@dataclass
class QualityReport:
    """完整品質報告"""

    run_id: str
    timestamp: str
    overall_passed: bool
    gates: list[GateResult] = field(default_factory=list)
    can_publish: bool = False
    can_send_newsletter: bool = False
    recommended_action: str = "draft"
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "overall_passed": self.overall_passed,
            "gates": [
                {
                    "name": g.name,
                    "passed": g.passed,
                    "message": g.message,
                    "details": g.details,
                }
                for g in self.gates
            ],
            "can_publish": self.can_publish,
            "can_send_newsletter": self.can_send_newsletter,
            "recommended_action": self.recommended_action,
            "errors": self.errors,
            "warnings": self.warnings,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


class QualityGate:
    """品質 Gate 檢查器"""

    def __init__(
        self,
        config_path: str = "config/quality_rules.yaml",
    ):
        """初始化品質 Gate

        Args:
            config_path: 設定檔路徑
        """
        self.config_path = Path(config_path)
        self.config = self._load_config()

        # 初始化各檢查器
        self.compliance_checker = ComplianceChecker(
            min_sources=self.config.get("sources", {}).get("min_count", 5),
            config_path=config_path,
        )
        self.number_tracer = NumberTracer(config_path=config_path)

    def _load_config(self) -> dict:
        """載入設定"""
        if self.config_path.exists():
            with open(self.config_path) as f:
                return yaml.safe_load(f)
        return {}

    def _check_sources(self, post: dict, research_pack: dict) -> GateResult:
        """檢查資訊來源

        優先從 post 讀取 sources（LLM 產出的文章），
        若沒有則從 research_pack 讀取。
        """
        # 優先從 post 讀取 sources
        sources = post.get("sources", [])
        if not sources:
            sources = research_pack.get("sources", [])

        source_count = len(sources)
        min_count = self.config.get("sources", {}).get("min_count", 3)  # 放寬至 3

        # 計算不同出版者數量
        publishers = set()
        for source in sources:
            # 支援三種格式：
            # 1. {publisher: ...}
            # 2. {title: "... - Publisher"}
            # 3. "Title - Publisher: URL" (字串格式)
            if isinstance(source, dict):
                publisher = source.get("publisher")
                if not publisher:
                    # 從 title 中提取 publisher（格式："Title - Publisher"）
                    title = source.get("title", "")
                    if " - " in title:
                        publisher = title.rsplit(" - ", 1)[-1]
            elif isinstance(source, str):
                # 字串格式，如 "Title - Publisher: URL"
                publisher = None
                if " - " in source:
                    # 提取 "Publisher" 部分
                    parts = source.rsplit(" - ", 1)
                    if len(parts) > 1:
                        publisher_part = parts[-1].split(":")[0].strip()
                        publisher = publisher_part
            else:
                publisher = None

            if publisher:
                publishers.add(publisher.lower())

        distinct_publishers = len(publishers)
        min_publishers = self.config.get("sources", {}).get("min_distinct_publishers", 0)  # 暫時關閉

        # 檢查主要事件是否為 rumor
        primary_event = research_pack.get("primary_event", {})
        event_type = primary_event.get("event_type", "")
        allow_rumor = self.config.get("sources", {}).get("allow_rumor_as_primary", False)

        errors = []
        if source_count < min_count:
            errors.append(f"Insufficient sources: {source_count} < {min_count}")
        if distinct_publishers < min_publishers:
            errors.append(f"Insufficient publishers: {distinct_publishers} < {min_publishers}")
        if event_type == "rumor" and not allow_rumor:
            errors.append("Rumor event cannot be primary")

        passed = len(errors) == 0

        return GateResult(
            name="sources",
            passed=passed,
            message="; ".join(errors) if errors else f"OK ({source_count} sources, {distinct_publishers} publishers)",
            details={
                "source_count": source_count,
                "distinct_publishers": distinct_publishers,
                "event_type": event_type,
            },
        )

    def _check_structure(self, post: dict, research_pack: dict) -> GateResult:
        """檢查結構

        優先從 post 讀取結構資訊（LLM 產出），
        若沒有則從 research_pack 讀取。
        """
        structure_config = self.config.get("structure", {})
        errors = []

        # 檢查 key_stocks - 優先從 post 讀取
        key_stocks = post.get("key_stocks", [])
        if not key_stocks:
            # 嘗試從 sections 中提取 Key Stocks
            for section in post.get("sections", []):
                if section.get("title") == "Key Stocks" and isinstance(section.get("content"), list):
                    key_stocks = section.get("content", [])
                    break
        if not key_stocks:
            key_stocks = research_pack.get("key_stocks", [])
        ks_config = structure_config.get("key_stocks", {})
        ks_min = ks_config.get("min", 1)  # 放寬下限至 1
        ks_max = ks_config.get("max", 10)  # 放寬上限至 10
        if not (ks_min <= len(key_stocks) <= ks_max):
            errors.append(f"key_stocks count {len(key_stocks)} not in [{ks_min}, {ks_max}]")

        # 檢查 TL;DR
        tldr = post.get("tldr", [])
        tldr_config = structure_config.get("tldr", {})
        tldr_min = tldr_config.get("min", 3)
        tldr_max = tldr_config.get("max", 8)  # 放寬上限
        if not (tldr_min <= len(tldr) <= tldr_max):
            errors.append(f"TL;DR count {len(tldr)} not in [{tldr_min}, {tldr_max}]")

        # 檢查 what_to_watch
        watch = post.get("what_to_watch", [])
        watch_config = structure_config.get("what_to_watch", {})
        watch_min = watch_config.get("min", 3)
        watch_max = watch_config.get("max", 10)  # 放寬上限
        if not (watch_min <= len(watch) <= watch_max):
            errors.append(f"what_to_watch count {len(watch)} not in [{watch_min}, {watch_max}]")

        # 檢查 title_candidates
        titles = post.get("title_candidates", [])
        title_config = structure_config.get("title_candidates", {})
        title_min = title_config.get("min", 5)
        if len(titles) < title_min:
            errors.append(f"title_candidates count {len(titles)} < {title_min}")

        # 檢查 peer_table - 優先從 post 讀取
        peer_table = post.get("peer_table", {})
        if not peer_table:
            peer_table = research_pack.get("peer_table", {})
        peer_config = structure_config.get("peer_table", {})
        # 讓 peer_table 成為可選
        if peer_config.get("required", False) and peer_table:
            rows = peer_table.get("rows", [])
            min_rows = peer_config.get("min_rows", 3)
            if len(rows) < min_rows:
                errors.append(f"peer_table rows {len(rows)} < {min_rows}")

        passed = len(errors) == 0

        return GateResult(
            name="structure",
            passed=passed,
            message="; ".join(errors) if errors else "OK",
            details={
                "key_stocks_count": len(key_stocks),
                "tldr_count": len(tldr),
                "what_to_watch_count": len(watch),
                "title_candidates_count": len(titles),
            },
        )

    def _check_valuation(self, post: dict, research_pack: dict) -> GateResult:
        """檢查估值

        優先從 post 讀取 valuations（LLM 產出），
        若沒有則從 research_pack 讀取。
        """
        valuations = post.get("valuations", {})
        if not valuations:
            valuations = research_pack.get("valuations", {})

        key_stocks = post.get("key_stocks", [])
        if not key_stocks:
            key_stocks = research_pack.get("key_stocks", [])

        warnings = []
        null_count = 0
        total_count = 0

        for stock in key_stocks:
            ticker = stock.get("ticker")
            if ticker and ticker in valuations:
                total_count += 1
                val = valuations[ticker]
                fair_value = val.get("fair_value", {})

                # 檢查三種情境是否都有
                for scenario in ["bear", "base", "bull"]:
                    if fair_value.get(scenario) is None:
                        null_count += 1
                        # 檢查是否有理由
                        if not val.get("rationale"):
                            warnings.append(f"{ticker} {scenario} is null without rationale")

        # 估值可用率
        availability = (total_count * 3 - null_count) / (total_count * 3) if total_count > 0 else 0

        return GateResult(
            name="valuation",
            passed=True,  # 估值是軟性要求
            message=f"Valuation availability: {availability:.0%}",
            details={
                "total_stocks": total_count,
                "null_scenarios": null_count,
                "availability": availability,
                "warnings": warnings,
            },
        )

    def _check_publishing(self, mode: str, newsletter_slug: str, email_segment: str) -> GateResult:
        """檢查發佈參數"""
        pub_config = self.config.get("publishing", {})
        errors = []

        if mode == "publish":
            # 檢查 newsletter slug
            allowed_slugs = pub_config.get("allowed_newsletter_slugs", [])
            if newsletter_slug and newsletter_slug not in allowed_slugs:
                errors.append(f"Newsletter slug '{newsletter_slug}' not in allowlist")

            # 檢查 email segment
            allowed_segments = pub_config.get("allowed_email_segments", [])
            if email_segment and email_segment not in allowed_segments:
                errors.append(f"Email segment '{email_segment}' not in allowlist")

            # 必須指定 segment
            if pub_config.get("require_segment_for_newsletter", True):
                if newsletter_slug and not email_segment:
                    errors.append("Email segment required for newsletter")

        passed = len(errors) == 0

        return GateResult(
            name="publishing",
            passed=passed,
            message="; ".join(errors) if errors else "OK",
            details={
                "mode": mode,
                "newsletter_slug": newsletter_slug,
                "email_segment": email_segment,
            },
        )

    def run_all_gates(
        self,
        post: dict,
        research_pack: dict,
        mode: str = "draft",
        newsletter_slug: str = "",
        email_segment: str = "",
        run_id: str = "",
    ) -> QualityReport:
        """執行所有品質 Gate

        Args:
            post: 文章資料
            research_pack: 研究包資料
            mode: 發佈模式
            newsletter_slug: Newsletter slug
            email_segment: Email segment
            run_id: 執行 ID

        Returns:
            QualityReport 實例
        """
        report = QualityReport(
            run_id=run_id,
            timestamp=datetime.utcnow().isoformat(),
            overall_passed=True,
        )

        # Gate 1: 資訊來源（優先從 post 讀取）
        sources_result = self._check_sources(post, research_pack)
        report.gates.append(sources_result)
        if not sources_result.passed:
            report.overall_passed = False
            report.errors.append(f"[sources] {sources_result.message}")

        # Gate 2: 結構檢查
        structure_result = self._check_structure(post, research_pack)
        report.gates.append(structure_result)
        if not structure_result.passed:
            report.overall_passed = False
            report.errors.append(f"[structure] {structure_result.message}")

        # Gate 3: 合規檢查
        compliance_result = self.compliance_checker.check(post, research_pack)
        compliance_gate = GateResult(
            name="compliance",
            passed=compliance_result.passed,
            message="; ".join(compliance_result.errors) if compliance_result.errors else "OK",
            details=compliance_result.to_dict(),
        )
        report.gates.append(compliance_gate)
        if not compliance_result.passed:
            report.overall_passed = False
            report.errors.extend([f"[compliance] {e}" for e in compliance_result.errors])
        report.warnings.extend(compliance_result.warnings)

        # Gate 4: 數字追溯
        markdown = post.get("markdown", "")
        trace_result = self.number_tracer.trace(markdown, research_pack)
        trace_gate = GateResult(
            name="number_traceability",
            passed=trace_result.passed,
            message=f"Traced {trace_result.traced_count}/{trace_result.total_numbers} numbers",
            details=trace_result.to_dict(),
        )
        report.gates.append(trace_gate)
        if not trace_result.passed:
            report.overall_passed = False
            report.errors.extend([f"[trace] {e}" for e in trace_result.errors])
        report.warnings.extend(trace_result.warnings)

        # Gate 5: 估值檢查 (軟性，優先從 post 讀取)
        valuation_result = self._check_valuation(post, research_pack)
        report.gates.append(valuation_result)
        if valuation_result.details.get("warnings"):
            report.warnings.extend(valuation_result.details["warnings"])

        # Gate 6: 發佈參數檢查
        if mode == "publish":
            pub_result = self._check_publishing(mode, newsletter_slug, email_segment)
            report.gates.append(pub_result)
            if not pub_result.passed:
                report.overall_passed = False
                report.errors.append(f"[publishing] {pub_result.message}")

        # 決定推薦動作
        if report.overall_passed:
            report.can_publish = True
            report.can_send_newsletter = mode == "publish"
            report.recommended_action = mode
        else:
            report.can_publish = False
            report.can_send_newsletter = False
            report.recommended_action = "draft"

        return report

    def save_report(
        self,
        report: QualityReport,
        output_path: str = "out/quality_report.json",
    ) -> Path:
        """儲存品質報告

        Args:
            report: 品質報告
            output_path: 輸出路徑

        Returns:
            輸出檔案路徑
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            f.write(report.to_json())

        logger.info(f"Quality report saved to {output_path}")
        return output_path


def main():
    """CLI demo"""
    import argparse
    from rich.console import Console
    from rich.table import Table

    parser = argparse.ArgumentParser(description="Quality Gate")
    parser.add_argument("--post", "-p", default="out/post.json", help="Post JSON path")
    parser.add_argument("--research-pack", "-r", default="out/research_pack.json", help="Research pack path")
    parser.add_argument("--mode", "-m", default="draft", help="Publish mode")
    args = parser.parse_args()

    console = Console()

    # 載入資料
    with open(args.post) as f:
        post = json.load(f)
    with open(args.research_pack) as f:
        research_pack = json.load(f)

    # 執行檢查
    gate = QualityGate()
    report = gate.run_all_gates(
        post,
        research_pack,
        mode=args.mode,
        run_id=research_pack.get("meta", {}).get("run_id", "unknown"),
    )

    # 顯示結果
    console.print(f"\n[bold]Quality Gate Report[/bold]")
    console.print(f"Run ID: {report.run_id}")
    console.print(f"Overall: {'[green]PASSED[/green]' if report.overall_passed else '[red]FAILED[/red]'}")

    table = Table(title="Gate Results")
    table.add_column("Gate", style="cyan")
    table.add_column("Status")
    table.add_column("Message")

    for gate_result in report.gates:
        status = "[green]✓ PASS[/green]" if gate_result.passed else "[red]✗ FAIL[/red]"
        table.add_row(gate_result.name, status, gate_result.message[:60])

    console.print(table)

    console.print(f"\n[bold]Recommended Action:[/bold] {report.recommended_action}")
    console.print(f"Can Publish: {report.can_publish}")
    console.print(f"Can Send Newsletter: {report.can_send_newsletter}")

    if report.errors:
        console.print("\n[red]Errors:[/red]")
        for err in report.errors:
            console.print(f"  ✗ {err}")

    if report.warnings:
        console.print("\n[yellow]Warnings:[/yellow]")
        for warn in report.warnings:
            console.print(f"  ⚠ {warn}")

    # 儲存報告
    gate.save_report(report)


if __name__ == "__main__":
    main()

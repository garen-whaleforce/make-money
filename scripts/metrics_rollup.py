#!/usr/bin/env python3
"""Metrics Rollup

歷史執行指標彙總與分析。
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table


def load_run_reports(reports_dir: str, days: int = 30) -> list[dict]:
    """載入執行報告

    Args:
        reports_dir: 報告目錄
        days: 載入最近幾天的報告

    Returns:
        報告列表
    """
    reports = []
    cutoff = datetime.utcnow() - timedelta(days=days)

    reports_path = Path(reports_dir)
    if not reports_path.exists():
        return reports

    for json_file in reports_path.glob("**/*.json"):
        try:
            with open(json_file) as f:
                report = json.load(f)

            # 檢查時間
            if "started_at" in report:
                started_at = datetime.fromisoformat(report["started_at"].replace("Z", "+00:00"))
                if started_at.replace(tzinfo=None) >= cutoff:
                    report["_file_path"] = str(json_file)
                    reports.append(report)

        except Exception:
            continue

    # 按時間排序
    reports.sort(key=lambda r: r.get("started_at", ""), reverse=True)
    return reports


def calculate_metrics(reports: list[dict]) -> dict:
    """計算彙總指標

    Args:
        reports: 報告列表

    Returns:
        彙總指標
    """
    if not reports:
        return {}

    metrics = {
        "total_runs": len(reports),
        "successful_runs": 0,
        "failed_runs": 0,
        "avg_duration_seconds": 0,
        "total_api_calls": 0,
        "total_cache_hits": 0,
        "total_cache_misses": 0,
        "quality_pass_rate": 0,
        "by_edition": defaultdict(lambda: {"runs": 0, "passed": 0}),
        "by_gate": defaultdict(lambda: {"runs": 0, "passed": 0}),
        "common_errors": defaultdict(int),
        "common_warnings": defaultdict(int),
    }

    total_duration = 0
    quality_passed = 0

    for report in reports:
        # 成功/失敗統計
        if report.get("status") == "completed":
            metrics["successful_runs"] += 1
        else:
            metrics["failed_runs"] += 1

        # 執行時間
        if report.get("duration_seconds"):
            total_duration += report["duration_seconds"]

        # API 統計
        for api_metric in report.get("api_metrics", []):
            metrics["total_api_calls"] += api_metric.get("calls", 0)
            metrics["total_cache_hits"] += api_metric.get("cache_hits", 0)
            metrics["total_cache_misses"] += api_metric.get("cache_misses", 0)

        # 品質統計
        quality = report.get("quality", {})
        if quality.get("passed"):
            quality_passed += 1

        # 按 edition 統計
        edition = report.get("edition", "unknown")
        metrics["by_edition"][edition]["runs"] += 1
        if quality.get("passed"):
            metrics["by_edition"][edition]["passed"] += 1

        # 按 gate 統計
        for gate in quality.get("gates", []):
            gate_name = gate.get("name", "unknown")
            metrics["by_gate"][gate_name]["runs"] += 1
            if gate.get("passed"):
                metrics["by_gate"][gate_name]["passed"] += 1

        # 常見錯誤
        for error in report.get("errors", []):
            # 簡化錯誤訊息
            error_key = error[:50] if len(error) > 50 else error
            metrics["common_errors"][error_key] += 1

        # 常見警告
        for warning in report.get("warnings", []):
            warning_key = warning[:50] if len(warning) > 50 else warning
            metrics["common_warnings"][warning_key] += 1

    # 計算平均值和比率
    metrics["avg_duration_seconds"] = total_duration / len(reports) if reports else 0
    metrics["quality_pass_rate"] = quality_passed / len(reports) if reports else 0
    metrics["cache_hit_rate"] = (
        metrics["total_cache_hits"] / (metrics["total_cache_hits"] + metrics["total_cache_misses"])
        if (metrics["total_cache_hits"] + metrics["total_cache_misses"]) > 0
        else 0
    )

    # 轉換 defaultdict 為普通 dict
    metrics["by_edition"] = dict(metrics["by_edition"])
    metrics["by_gate"] = dict(metrics["by_gate"])
    metrics["common_errors"] = dict(sorted(metrics["common_errors"].items(), key=lambda x: -x[1])[:10])
    metrics["common_warnings"] = dict(sorted(metrics["common_warnings"].items(), key=lambda x: -x[1])[:10])

    return metrics


def print_metrics(metrics: dict, console: Console) -> None:
    """輸出指標

    Args:
        metrics: 彙總指標
        console: Rich console
    """
    if not metrics:
        console.print("[yellow]No metrics to display[/yellow]")
        return

    console.print("\n[bold]📊 Metrics Rollup[/bold]\n")

    # 總覽
    overview_table = Table(title="Overview")
    overview_table.add_column("Metric", style="cyan")
    overview_table.add_column("Value", style="green")

    overview_table.add_row("Total Runs", str(metrics["total_runs"]))
    overview_table.add_row("Successful Runs", str(metrics["successful_runs"]))
    overview_table.add_row("Failed Runs", str(metrics["failed_runs"]))
    overview_table.add_row("Avg Duration", f"{metrics['avg_duration_seconds']:.1f}s")
    overview_table.add_row("Quality Pass Rate", f"{metrics['quality_pass_rate']:.1%}")
    overview_table.add_row("Cache Hit Rate", f"{metrics['cache_hit_rate']:.1%}")

    console.print(overview_table)

    # API 統計
    api_table = Table(title="API Statistics")
    api_table.add_column("Metric", style="cyan")
    api_table.add_column("Value", style="green")

    api_table.add_row("Total API Calls", str(metrics["total_api_calls"]))
    api_table.add_row("Cache Hits", str(metrics["total_cache_hits"]))
    api_table.add_row("Cache Misses", str(metrics["total_cache_misses"]))

    console.print("\n")
    console.print(api_table)

    # 按 Edition 統計
    if metrics["by_edition"]:
        edition_table = Table(title="By Edition")
        edition_table.add_column("Edition", style="cyan")
        edition_table.add_column("Runs", style="green")
        edition_table.add_column("Passed", style="green")
        edition_table.add_column("Pass Rate", style="yellow")

        for edition, data in metrics["by_edition"].items():
            pass_rate = data["passed"] / data["runs"] if data["runs"] > 0 else 0
            edition_table.add_row(
                edition,
                str(data["runs"]),
                str(data["passed"]),
                f"{pass_rate:.1%}",
            )

        console.print("\n")
        console.print(edition_table)

    # 按 Gate 統計
    if metrics["by_gate"]:
        gate_table = Table(title="By Quality Gate")
        gate_table.add_column("Gate", style="cyan")
        gate_table.add_column("Runs", style="green")
        gate_table.add_column("Passed", style="green")
        gate_table.add_column("Pass Rate", style="yellow")

        for gate_name, data in sorted(metrics["by_gate"].items()):
            pass_rate = data["passed"] / data["runs"] if data["runs"] > 0 else 0
            color = "green" if pass_rate >= 0.9 else "yellow" if pass_rate >= 0.7 else "red"
            gate_table.add_row(
                gate_name,
                str(data["runs"]),
                str(data["passed"]),
                f"[{color}]{pass_rate:.1%}[/{color}]",
            )

        console.print("\n")
        console.print(gate_table)

    # 常見錯誤
    if metrics["common_errors"]:
        console.print("\n[bold red]Common Errors (Top 10)[/bold red]")
        for error, count in list(metrics["common_errors"].items())[:10]:
            console.print(f"  [{count}x] {error}")

    # 常見警告
    if metrics["common_warnings"]:
        console.print("\n[bold yellow]Common Warnings (Top 10)[/bold yellow]")
        for warning, count in list(metrics["common_warnings"].items())[:10]:
            console.print(f"  [{count}x] {warning}")


def main():
    parser = argparse.ArgumentParser(description="Metrics Rollup")
    parser.add_argument(
        "--reports-dir", "-r",
        default="out/reports",
        help="Reports directory",
    )
    parser.add_argument(
        "--days", "-d",
        type=int,
        default=30,
        help="Number of days to analyze",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output JSON file",
    )
    args = parser.parse_args()

    console = Console()

    # 載入報告
    console.print(f"Loading reports from {args.reports_dir} (last {args.days} days)...")
    reports = load_run_reports(args.reports_dir, args.days)
    console.print(f"Loaded {len(reports)} reports")

    # 計算指標
    metrics = calculate_metrics(reports)

    # 輸出
    print_metrics(metrics, console)

    # 儲存 JSON
    if args.output:
        with open(args.output, "w") as f:
            json.dump(metrics, f, indent=2, ensure_ascii=False)
        console.print(f"\n[green]Saved metrics to {args.output}[/green]")


if __name__ == "__main__":
    main()

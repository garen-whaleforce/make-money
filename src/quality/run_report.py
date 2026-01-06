"""Run Report Generator

生成詳細的執行報告，用於追蹤與優化。
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ..utils.logging import get_logger
from ..utils.time import format_datetime, get_now

logger = get_logger(__name__)


@dataclass
class APIMetrics:
    """API 呼叫統計"""

    provider: str
    calls: int = 0
    errors: int = 0
    total_time_ms: float = 0
    cache_hits: int = 0
    cache_misses: int = 0

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "calls": self.calls,
            "errors": self.errors,
            "total_time_ms": self.total_time_ms,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": self.cache_hits / (self.cache_hits + self.cache_misses)
            if (self.cache_hits + self.cache_misses) > 0 else 0,
        }


@dataclass
class DataGap:
    """資料缺口"""

    ticker: str
    missing_fields: list[str]
    severity: str  # critical, warning, info

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "missing_fields": self.missing_fields,
            "severity": self.severity,
        }


@dataclass
class RunReport:
    """執行報告"""

    run_id: str
    edition: str
    started_at: str
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    status: str = "running"

    # 候選事件統計
    candidate_events_count: int = 0
    distinct_publishers: int = 0
    top_events: list[dict] = field(default_factory=list)

    # 選題結果
    selected_event: Optional[dict] = None
    selection_reason: str = ""
    selected_theme: Optional[dict] = None
    selected_tickers: list[str] = field(default_factory=list)

    # API 統計
    api_metrics: list[APIMetrics] = field(default_factory=list)

    # 資料缺口
    data_gaps: list[DataGap] = field(default_factory=list)

    # 內容統計
    content_stats: dict = field(default_factory=dict)

    # 品質結果
    quality_passed: bool = False
    quality_gates: list[dict] = field(default_factory=list)

    # 發佈結果
    publish_result: Optional[dict] = None

    # 錯誤與警告
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "edition": self.edition,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "status": self.status,
            "candidate_events": {
                "count": self.candidate_events_count,
                "distinct_publishers": self.distinct_publishers,
                "top_10": self.top_events[:10],
            },
            "selection": {
                "event": self.selected_event,
                "reason": self.selection_reason,
                "theme": self.selected_theme,
                "tickers": self.selected_tickers,
            },
            "api_metrics": [m.to_dict() for m in self.api_metrics],
            "data_gaps": [g.to_dict() for g in self.data_gaps],
            "content_stats": self.content_stats,
            "quality": {
                "passed": self.quality_passed,
                "gates": self.quality_gates,
            },
            "publish_result": self.publish_result,
            "errors": self.errors,
            "warnings": self.warnings,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


class RunReportBuilder:
    """執行報告建構器"""

    def __init__(self, run_id: str, edition: str):
        """初始化報告建構器

        Args:
            run_id: 執行 ID
            edition: 版本 (premarket/postclose/intraday)
        """
        self.report = RunReport(
            run_id=run_id,
            edition=edition,
            started_at=datetime.utcnow().isoformat(),
        )
        self._start_time = time.time()
        self._api_timers: dict[str, float] = {}

    def set_candidate_events(
        self,
        events: list,
        scored_events: Optional[list] = None,
    ) -> None:
        """設定候選事件統計

        Args:
            events: 候選事件列表
            scored_events: 評分後的事件列表
        """
        self.report.candidate_events_count = len(events)

        # 統計不同出版者
        publishers = set()
        for event in events:
            publisher = getattr(event, "publisher", None) or event.get("publisher")
            if publisher:
                publishers.add(publisher.lower())
        self.report.distinct_publishers = len(publishers)

        # Top 10 事件
        if scored_events:
            self.report.top_events = [
                {
                    "id": e.event.id if hasattr(e, "event") else e.get("id"),
                    "title": (e.event.title if hasattr(e, "event") else e.get("title", ""))[:100],
                    "score": e.total_score if hasattr(e, "total_score") else e.get("score", 0),
                    "type": e.event_type if hasattr(e, "event_type") else e.get("event_type"),
                }
                for e in scored_events[:10]
            ]

    def set_selection(
        self,
        event: Any,
        reason: str,
        theme: Optional[dict] = None,
        tickers: Optional[list[str]] = None,
    ) -> None:
        """設定選題結果

        Args:
            event: 選中的事件
            reason: 選題原因
            theme: 主題
            tickers: 關鍵 tickers
        """
        if hasattr(event, "event"):
            self.report.selected_event = {
                "id": event.event.id,
                "title": event.event.title,
                "type": event.event_type,
                "score": event.total_score,
            }
        else:
            self.report.selected_event = event

        self.report.selection_reason = reason
        self.report.selected_theme = theme
        self.report.selected_tickers = tickers or []

    def start_api_timer(self, provider: str) -> None:
        """開始 API 計時"""
        self._api_timers[provider] = time.time()

    def end_api_timer(
        self,
        provider: str,
        success: bool = True,
        cache_hit: bool = False,
    ) -> None:
        """結束 API 計時

        Args:
            provider: 提供者名稱
            success: 是否成功
            cache_hit: 是否快取命中
        """
        elapsed = 0
        if provider in self._api_timers:
            elapsed = (time.time() - self._api_timers[provider]) * 1000
            del self._api_timers[provider]

        # 找或建立 metrics
        metrics = None
        for m in self.report.api_metrics:
            if m.provider == provider:
                metrics = m
                break

        if not metrics:
            metrics = APIMetrics(provider=provider)
            self.report.api_metrics.append(metrics)

        metrics.calls += 1
        metrics.total_time_ms += elapsed
        if not success:
            metrics.errors += 1
        if cache_hit:
            metrics.cache_hits += 1
        else:
            metrics.cache_misses += 1

    def add_data_gap(
        self,
        ticker: str,
        missing_fields: list[str],
        severity: str = "warning",
    ) -> None:
        """新增資料缺口

        Args:
            ticker: 股票代碼
            missing_fields: 缺少的欄位
            severity: 嚴重程度
        """
        self.report.data_gaps.append(DataGap(
            ticker=ticker,
            missing_fields=missing_fields,
            severity=severity,
        ))

    def analyze_data_gaps(self, companies: dict, key_tickers: list[str]) -> None:
        """分析資料缺口

        Args:
            companies: 公司資料字典
            key_tickers: 關鍵 tickers
        """
        required_fields = [
            ("price.last", "critical"),
            ("price.market_cap", "critical"),
            ("fundamentals.gross_margin", "warning"),
            ("fundamentals.operating_margin", "warning"),
            ("estimates.revenue_ntm", "info"),
            ("estimates.eps_ntm", "info"),
        ]

        for ticker in key_tickers:
            company = companies.get(ticker)
            if not company:
                self.add_data_gap(ticker, ["all"], "critical")
                continue

            missing = []
            for field_path, severity in required_fields:
                parts = field_path.split(".")
                value = company
                for part in parts:
                    if hasattr(value, part):
                        value = getattr(value, part)
                    elif isinstance(value, dict) and part in value:
                        value = value[part]
                    else:
                        value = None
                        break

                if value is None:
                    missing.append(field_path)

            if missing:
                # 用最高嚴重程度
                max_severity = "info"
                for field_path, severity in required_fields:
                    if field_path in missing:
                        if severity == "critical":
                            max_severity = "critical"
                            break
                        elif severity == "warning" and max_severity != "critical":
                            max_severity = "warning"

                self.add_data_gap(ticker, missing, max_severity)

    def set_content_stats(self, post: dict, research_pack: dict) -> None:
        """設定內容統計

        Args:
            post: 文章資料
            research_pack: 研究包資料
        """
        markdown = post.get("markdown", "")

        self.report.content_stats = {
            "word_count": len(markdown.split()),
            "char_count": len(markdown),
            "paragraph_count": len([p for p in markdown.split("\n\n") if p.strip()]),
            "key_stocks_count": len(research_pack.get("key_stocks", [])),
            "sources_count": len(research_pack.get("sources", [])),
            "tldr_count": len(post.get("tldr", [])),
            "what_to_watch_count": len(post.get("what_to_watch", [])),
            "title_candidates_count": len(post.get("title_candidates", [])),
        }

    def set_quality_result(self, quality_report: dict) -> None:
        """設定品質檢查結果

        Args:
            quality_report: 品質報告
        """
        self.report.quality_passed = quality_report.get("overall_passed", False)
        self.report.quality_gates = quality_report.get("gates", [])

    def set_publish_result(self, result: dict) -> None:
        """設定發佈結果

        Args:
            result: 發佈結果
        """
        self.report.publish_result = result

    def add_error(self, error: str) -> None:
        """新增錯誤"""
        self.report.errors.append(error)

    def add_warning(self, warning: str) -> None:
        """新增警告"""
        self.report.warnings.append(warning)

    def complete(self, status: str = "completed") -> RunReport:
        """完成報告

        Args:
            status: 最終狀態

        Returns:
            RunReport 實例
        """
        self.report.completed_at = datetime.utcnow().isoformat()
        self.report.duration_seconds = time.time() - self._start_time
        self.report.status = status
        return self.report

    def save(self, output_path: str = "out/run_report.json") -> Path:
        """儲存報告

        Args:
            output_path: 輸出路徑

        Returns:
            輸出檔案路徑
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            f.write(self.report.to_json())

        logger.info(f"Run report saved to {output_path}")
        return output_path

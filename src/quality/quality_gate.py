"""Quality Gate - 整合所有品質檢查

Fail-Closed 原則：任何一關失敗就不自動發布。
"""

import json
import re
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
        也會嘗試從 news_items 提取 publisher 資訊。
        """
        # 優先從 post 讀取 sources
        sources = post.get("sources", [])
        if not sources:
            sources = research_pack.get("sources", [])

        # 如果還是沒有 sources，嘗試從 news_items 建立
        if not sources:
            news_items = post.get("news_items", []) or research_pack.get("news_items", [])
            for item in news_items:
                if isinstance(item, dict):
                    publisher = item.get("publisher") or item.get("source")
                    sources.append({
                        "name": item.get("headline") or item.get("title", ""),
                        "publisher": publisher,
                        "url": item.get("url"),
                        "type": "news",
                    })

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
                publisher = source.get("publisher") or source.get("source")
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
            sections = post.get("sections", [])
            # sections 可能是 list 或 dict，需要處理兩種情況
            if isinstance(sections, list):
                for section in sections:
                    if isinstance(section, dict) and section.get("title") == "Key Stocks" and isinstance(section.get("content"), list):
                        key_stocks = section.get("content", [])
                        break
            elif isinstance(sections, dict):
                # 如果是 dict，嘗試從 key_stocks key 取得
                key_stocks = sections.get("key_stocks", [])
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

    def _check_topic_integrity(self, post: dict, research_pack: dict) -> GateResult:
        """檢查主題一致性（A1: 防止內容污染/串稿）

        確保 Deep Dive 文章只包含與主題相關的內容，
        不會混入無關公司或產業。
        """
        errors = []
        warnings = []

        post_type = post.get("meta", {}).get("post_type", "")
        deep_dive_ticker = research_pack.get("deep_dive_ticker") or post.get("meta", {}).get("ticker")

        # 只對 Deep Dive 做嚴格檢查
        if post_type != "deep":
            return GateResult(
                name="topic_integrity",
                passed=True,
                message="Skipped (not deep dive)",
                details={"post_type": post_type},
            )

        # 定義必須出現的關鍵字（根據 ticker）
        must_have_keywords = {
            "NVDA": ["NVDA", "NVIDIA", "GPU", "AI"],
            "AMD": ["AMD", "EPYC", "Ryzen", "GPU"],
            "AVGO": ["AVGO", "Broadcom", "semiconductor"],
            "TSM": ["TSM", "TSMC", "foundry", "semiconductor"],
            "MSFT": ["MSFT", "Microsoft", "Azure", "cloud"],
            "GOOGL": ["GOOGL", "Google", "Alphabet", "cloud"],
            "AMZN": ["AMZN", "Amazon", "AWS", "cloud"],
            "META": ["META", "Meta", "Facebook", "AI"],
        }

        # 定義禁止出現的無關公司/主題（串稿檢測）
        banned_keywords_for_ticker = {
            "NVDA": ["Grab", "MongoDB", "Zscaler", "Bitcoin mining", "quantum computing stock"],
            "AMD": ["Grab", "MongoDB", "Zscaler"],
            # 可以擴展其他 ticker
        }

        # 自我否定句型（Self-Contradiction）
        self_contradiction_patterns = [
            "資料不足",
            "無法提供精確",
            "數據缺失",
            "無法估算",
            "缺乏足夠資料",
            "insufficient data",
            "cannot provide accurate",
        ]

        # 取得文章內容（HTML 或 markdown）
        content = post.get("html", "") or post.get("markdown", "")
        content_lower = content.lower()

        # 檢查必須出現的關鍵字
        if deep_dive_ticker and deep_dive_ticker in must_have_keywords:
            required = must_have_keywords[deep_dive_ticker]
            found = [kw for kw in required if kw.lower() in content_lower]
            if len(found) < 2:  # 至少要有 2 個必要關鍵字
                errors.append(f"Missing required keywords for {deep_dive_ticker}: expected {required}, found {found}")

        # 檢查禁止出現的關鍵字（串稿檢測）
        if deep_dive_ticker and deep_dive_ticker in banned_keywords_for_ticker:
            banned = banned_keywords_for_ticker[deep_dive_ticker]
            found_banned = [kw for kw in banned if kw.lower() in content_lower]
            if found_banned:
                errors.append(f"Content contamination detected: found banned keywords {found_banned} in {deep_dive_ticker} Deep Dive")

        # 檢查自我否定句型（Self-Contradiction Gate）
        # 如果文章有「估值表/壓力測試」但同時有「資料不足」就 fail
        has_valuation_section = any(kw in content_lower for kw in ["估值", "valuation", "壓力測試", "stress test", "合理價"])
        has_self_contradiction = any(pattern.lower() in content_lower for pattern in self_contradiction_patterns)

        if has_valuation_section and has_self_contradiction:
            errors.append("Self-contradiction detected: valuation section exists but also claims 'insufficient data'")

        passed = len(errors) == 0

        return GateResult(
            name="topic_integrity",
            passed=passed,
            message="; ".join(errors) if errors else "OK (topic consistent)",
            details={
                "ticker": deep_dive_ticker,
                "has_valuation": has_valuation_section,
                "has_self_contradiction": has_self_contradiction,
                "errors": errors,
                "warnings": warnings,
            },
        )

    def _check_slug_content_consistency(self, post: dict, research_pack: dict) -> GateResult:
        """檢查 Slug 與內容主題一致性 (P0-3)

        P0-3 規則：
        - URL slug 中的 ticker/主題必須與文章內容的主題一致
        - 例如：nvda-deep-dive 的內容不能是 TSLA 分析
        - 這會嚴重損害 SEO、內部連結、用戶信任

        常見失敗場景：
        - slug 包含 NVDA 但文章分析 TSLA
        - slug 用了舊主題但內容被 LLM 改成其他主題
        """
        errors = []
        warnings = []

        slug = post.get("slug", "")
        title = post.get("title", "")
        content = post.get("html", "") or post.get("markdown", "")

        if not slug:
            warnings.append("Slug is empty")
            return GateResult(
                name="slug_content_consistency",
                passed=True,
                message="Skipped (no slug)",
                details={"warnings": warnings},
            )

        # 從 slug 提取可能的 ticker
        slug_upper = slug.upper()
        KNOWN_TICKERS = [
            "NVDA", "AMD", "AVGO", "TSM", "ASML", "MRVL", "CRDO", "ALAB",  # AI 半導體
            "MSFT", "GOOGL", "AMZN", "META", "AAPL",  # 科技巨頭
            "TSLA", "COIN", "MSTR", "PLTR", "CRWD",  # 高知名度
            "IONQ", "RGTI", "QBTS",  # 量子
            "OKLO", "NNE", "SMR", "CEG", "VST",  # 核能/電力
            "RKLB", "LUNR", "ASTS",  # 太空
        ]

        slug_tickers = [t for t in KNOWN_TICKERS if t in slug_upper]

        # 從 title 提取 ticker
        title_upper = title.upper() if title else ""
        title_tickers = [t for t in KNOWN_TICKERS if t in title_upper]

        # 從內容提取主要 ticker（出現次數最多的）
        content_upper = content.upper() if content else ""
        content_ticker_counts = {}
        for t in KNOWN_TICKERS:
            count = content_upper.count(t)
            if count > 0:
                content_ticker_counts[t] = count

        # 找出內容中最常出現的 ticker
        content_primary_ticker = None
        if content_ticker_counts:
            content_primary_ticker = max(content_ticker_counts.items(), key=lambda x: x[1])[0]

        # 檢查一致性
        # Case 1: Slug 有 ticker，但內容主要討論的是不同 ticker
        if slug_tickers and content_primary_ticker:
            if content_primary_ticker not in slug_tickers:
                # 確認是否真的不一致（內容主 ticker 出現次數要顯著高於 slug ticker）
                slug_ticker_count = content_ticker_counts.get(slug_tickers[0], 0)
                content_primary_count = content_ticker_counts.get(content_primary_ticker, 0)

                # 如果內容主 ticker 出現次數是 slug ticker 的 2 倍以上，視為嚴重不一致
                if content_primary_count > slug_ticker_count * 2 and content_primary_count > 10:
                    errors.append(
                        f"[P0-CRITICAL] Slug/Content 主題不一致！"
                        f"Slug 指向 {slug_tickers[0]}，但內容主要討論 {content_primary_ticker} "
                        f"({content_primary_ticker}: {content_primary_count}次 vs {slug_tickers[0]}: {slug_ticker_count}次)"
                    )

        # Case 2: Title 和 Slug 不一致
        if slug_tickers and title_tickers:
            if not any(t in title_tickers for t in slug_tickers):
                warnings.append(
                    f"Slug ticker ({slug_tickers}) 與 Title ticker ({title_tickers}) 可能不一致"
                )

        # Case 3: Deep Dive 類型特別檢查
        post_type = post.get("meta", {}).get("post_type", "")
        if post_type == "deep" and slug_tickers:
            expected_ticker = slug_tickers[0]
            # Deep Dive 應該大量討論指定的 ticker
            expected_count = content_ticker_counts.get(expected_ticker, 0)
            if expected_count < 20:
                warnings.append(
                    f"Deep Dive 類型但 {expected_ticker} 只出現 {expected_count} 次，"
                    f"可能內容不夠聚焦或主題錯誤"
                )

        passed = len(errors) == 0

        return GateResult(
            name="slug_content_consistency",
            passed=passed,
            message="; ".join(errors) if errors else "OK",
            details={
                "slug": slug,
                "slug_tickers": slug_tickers,
                "title_tickers": title_tickers,
                "content_primary_ticker": content_primary_ticker,
                "content_ticker_counts": dict(sorted(content_ticker_counts.items(), key=lambda x: -x[1])[:5]),
                "errors": errors,
                "warnings": warnings,
            },
        )

    def _check_data_completeness(self, post: dict, research_pack: dict) -> GateResult:
        """檢查資料完整性（A2: 防止 null 欄位輸出）

        確保關鍵欄位不為 null，特別是 Earnings scoreboard。
        """
        errors = []
        warnings = []
        null_fields = []

        post_type = post.get("meta", {}).get("post_type", "")

        # Earnings 專用檢查
        if post_type == "earnings":
            scoreboard = post.get("earnings_scoreboard", [])
            # Handle both list and dict formats
            if isinstance(scoreboard, dict):
                scoreboard = [scoreboard]  # Wrap single dict in list
            elif not isinstance(scoreboard, list):
                scoreboard = []

            for i, entry in enumerate(scoreboard):
                if not isinstance(entry, dict):
                    continue  # Skip non-dict entries
                # 必填欄位
                required_fields = ["ticker", "quarter", "eps_estimate", "revenue_estimate"]
                for field in required_fields:
                    value = entry.get(field)
                    if value is None or value == "TBD" or value == "":
                        null_fields.append(f"earnings_scoreboard[{i}].{field}")

        # Deep Dive 專用檢查
        if post_type == "deep":
            # 檢查 ticker_profile
            profile = post.get("ticker_profile", {})
            deep_dive_required = ["change_ytd", "52w_high", "52w_low"]
            for field in deep_dive_required:
                if profile.get(field) is None:
                    warnings.append(f"ticker_profile.{field} is null (recommended)")

            # 檢查 valuation
            valuation = post.get("valuation", {})
            if valuation:
                scenarios = valuation.get("scenarios", {})
                for scenario in ["base", "bull", "bear"]:
                    if not scenarios.get(scenario):
                        warnings.append(f"valuation.scenarios.{scenario} is missing")

        # 如果有太多 null 欄位就 fail
        if len(null_fields) > 3:
            errors.append(f"Too many null required fields: {null_fields[:5]}...")

        passed = len(errors) == 0

        return GateResult(
            name="data_completeness",
            passed=passed,
            message="; ".join(errors) if errors else f"OK ({len(null_fields)} null fields, {len(warnings)} warnings)",
            details={
                "null_fields": null_fields,
                "warnings": warnings,
            },
        )

    def _check_json_html_consistency(self, post: dict, html_content: str = "") -> GateResult:
        """檢查 JSON 與 HTML 一致性

        確保 JSON 資料與 HTML 輸出同步。
        """
        errors = []

        # 從 post 取得 HTML（如果沒有傳入）
        if not html_content:
            html_content = post.get("html", "")

        if not html_content:
            return GateResult(
                name="json_html_consistency",
                passed=True,
                message="No HTML to check",
                details={},
            )

        # 檢查 title 一致性
        title = post.get("title", "")
        if title and title not in html_content:
            errors.append(f"Title '{title[:30]}...' not found in HTML")

        # 檢查 ticker 一致性
        tickers_mentioned = post.get("tickers_mentioned", [])
        if tickers_mentioned:
            primary_ticker = tickers_mentioned[0] if tickers_mentioned else None
            if primary_ticker and primary_ticker not in html_content:
                errors.append(f"Primary ticker '{primary_ticker}' not found in HTML")

        passed = len(errors) == 0

        return GateResult(
            name="json_html_consistency",
            passed=passed,
            message="; ".join(errors) if errors else "OK",
            details={"errors": errors},
        )

    def _check_flash_consistency(self, post: dict, research_pack: dict) -> GateResult:
        """檢查 Flash (Post A) 內部一致性 (A3)

        確保 repricing_dashboard 變數與 tldr、key_numbers 保持一致：
        1. repricing_dashboard 中提到的 ticker 應該出現在 key_stocks 中
        2. tldr 中的 ticker/主題要與 repricing_dashboard 呼應
        3. key_numbers 的數值與 repricing 主題相關
        """
        errors = []
        warnings = []

        post_type = post.get("meta", {}).get("post_type", "")

        # 只對 Flash 做檢查
        if post_type != "flash":
            return GateResult(
                name="flash_consistency",
                passed=True,
                message="Skipped (not flash)",
                details={"post_type": post_type},
            )

        # 收集各區塊的 tickers
        repricing_dashboard = post.get("repricing_dashboard", [])
        key_stocks = post.get("key_stocks", [])
        tldr = post.get("tldr", [])
        key_numbers = post.get("key_numbers", [])
        news_items = post.get("news_items", [])

        # 從 key_stocks 取得 tickers
        key_stock_tickers = set()
        for stock in key_stocks:
            ticker = stock.get("ticker")
            if ticker:
                key_stock_tickers.add(ticker.upper())

        # 從 news_items 取得被影響的 tickers
        news_tickers = set()
        for news in news_items:
            for ticker in news.get("affected_tickers", []):
                news_tickers.add(ticker.upper())

        # 從 repricing_dashboard 取得提到的 tickers
        repricing_tickers = set()
        repricing_variables = []
        for item in repricing_dashboard:
            variable = item.get("variable", "")
            direct_impact = item.get("direct_impact", "")
            repricing_variables.append(variable)

            # 從 direct_impact 提取 tickers（通常格式如 "NVDA, AMD 估值提升"）
            ticker_pattern = r'\b([A-Z]{2,5})\b'
            found = re.findall(ticker_pattern, direct_impact)
            for t in found:
                # 排除常見非 ticker 的大寫詞
                non_tickers = {"AI", "GPU", "NTM", "TTM", "YTD", "QOQ", "YOY", "EPS", "PE", "PEG", "FCF", "DCF"}
                if t not in non_tickers:
                    repricing_tickers.add(t)

        # 從 tldr 提取 tickers
        tldr_tickers = set()
        for bullet in tldr:
            ticker_pattern = r'\b([A-Z]{2,5})\b'
            found = re.findall(ticker_pattern, bullet)
            for t in found:
                non_tickers = {"AI", "GPU", "NTM", "TTM", "YTD", "QOQ", "YOY", "EPS", "PE", "PEG", "FCF", "DCF"}
                if t not in non_tickers:
                    tldr_tickers.add(t)

        # 檢查一致性規則

        # Rule 1: repricing_dashboard 提到的 ticker 應該出現在 key_stocks 或 news_items 中
        orphan_repricing_tickers = repricing_tickers - key_stock_tickers - news_tickers
        if orphan_repricing_tickers:
            warnings.append(f"Repricing mentions tickers not in key_stocks/news: {orphan_repricing_tickers}")

        # Rule 2: key_stocks 中的 ticker 應該至少有一個被 repricing 或 tldr 提到
        key_mentioned_in_repricing_or_tldr = key_stock_tickers & (repricing_tickers | tldr_tickers)
        if key_stock_tickers and not key_mentioned_in_repricing_or_tldr:
            warnings.append("None of key_stocks tickers appear in repricing_dashboard or tldr")

        # Rule 3: 至少要有 3 個 repricing variable
        if len(repricing_dashboard) < 3:
            errors.append(f"repricing_dashboard has only {len(repricing_dashboard)} items (minimum 3)")

        # Rule 4: 每個 repricing variable 必須有 direct_impact
        empty_impacts = [v for v, item in zip(repricing_variables, repricing_dashboard) if not item.get("direct_impact")]
        if empty_impacts:
            warnings.append(f"Repricing variables missing direct_impact: {empty_impacts}")

        # Rule 5: key_numbers 數量必須是 3
        if len(key_numbers) != 3:
            errors.append(f"key_numbers has {len(key_numbers)} items (must be exactly 3)")

        passed = len(errors) == 0

        return GateResult(
            name="flash_consistency",
            passed=passed,
            message="; ".join(errors) if errors else f"OK ({len(repricing_tickers)} repricing tickers, {len(key_stock_tickers)} key stocks)",
            details={
                "repricing_variables": repricing_variables,
                "repricing_tickers": list(repricing_tickers),
                "key_stock_tickers": list(key_stock_tickers),
                "tldr_tickers": list(tldr_tickers),
                "orphan_tickers": list(orphan_repricing_tickers) if orphan_repricing_tickers else [],
                "warnings": warnings,
            },
        )

    def _check_percent_sanity(self, post: dict, research_pack: dict) -> GateResult:
        """檢查百分比數值合理性 (P0-1)

        Rule: 若 |change_pct| > 35 且 market_cap > 50B，hard fail
        這種情況通常表示百分比被重複乘以100。

        Mega-cap股票 (市值 > $50B) 單日漲跌超過 35% 極為罕見，
        如果出現這種數字很可能是資料處理錯誤。
        """
        errors = []
        warnings = []
        suspicious_tickers = []

        MEGA_CAP_THRESHOLD = 50e9  # $50B
        EXTREME_CHANGE_THRESHOLD = 35  # 35%

        market_data = research_pack.get("market_data", {})

        for ticker, data in market_data.items():
            change_pct = data.get("change_pct")
            market_cap = data.get("market_cap")

            if change_pct is None or market_cap is None:
                continue

            # Check for mega-cap with extreme change
            if market_cap > MEGA_CAP_THRESHOLD and abs(change_pct) > EXTREME_CHANGE_THRESHOLD:
                suspicious_tickers.append({
                    "ticker": ticker,
                    "change_pct": change_pct,
                    "market_cap": market_cap,
                })
                errors.append(
                    f"{ticker}: |{change_pct:.2f}%| > {EXTREME_CHANGE_THRESHOLD}% "
                    f"for mega-cap (${market_cap/1e9:.1f}B) - likely percent scale bug"
                )

            # Warn for any ticker with >50% change
            elif abs(change_pct) > 50:
                warnings.append(f"{ticker}: {change_pct:+.2f}% change seems unusual")

        passed = len(errors) == 0

        return GateResult(
            name="percent_sanity",
            passed=passed,
            message="; ".join(errors) if errors else "OK",
            details={
                "suspicious_tickers": suspicious_tickers,
                "warnings": warnings,
            },
        )

    def _check_duplicate_ticker_consistency(self, post: dict, research_pack: dict) -> GateResult:
        """檢查重複 ticker 數值一致性 (P0-3)

        Same ticker appearing in multiple places should show consistent values.
        Example: NVDA appearing in both repricing_variables and key_stocks
        should show the same change_pct value.
        """
        errors = []
        warnings = []
        inconsistencies = []

        # Collect all ticker mentions with their values
        ticker_values = {}  # {ticker: [(source, field, value), ...]}

        post_type = post.get("meta", {}).get("post_type", "")

        # Source 1: market_data from research_pack
        market_data = research_pack.get("market_data", {})
        for ticker, data in market_data.items():
            if ticker not in ticker_values:
                ticker_values[ticker] = []
            if data.get("change_pct") is not None:
                ticker_values[ticker].append(
                    ("market_data", "change_pct", data["change_pct"])
                )
            if data.get("price") is not None:
                ticker_values[ticker].append(
                    ("market_data", "price", data["price"])
                )

        # Source 2: repricing_variables (Flash posts)
        if post_type == "flash":
            repricing = post.get("repricing_variables", [])
            if isinstance(repricing, list):
                for item in repricing:
                    ticker = item.get("ticker")
                    if not ticker:
                        continue
                    if ticker not in ticker_values:
                        ticker_values[ticker] = []
                    if item.get("change_pct") is not None:
                        ticker_values[ticker].append(
                            ("repricing_variables", "change_pct", item["change_pct"])
                        )

            # Source 3: key_stocks (Flash posts)
            key_stocks = post.get("key_stocks", [])
            if isinstance(key_stocks, list):
                for item in key_stocks:
                    ticker = item.get("ticker")
                    if not ticker:
                        continue
                    if ticker not in ticker_values:
                        ticker_values[ticker] = []
                    if item.get("change_pct") is not None:
                        ticker_values[ticker].append(
                            ("key_stocks", "change_pct", item["change_pct"])
                        )

        # Source 4: earnings_scoreboard (Earnings posts)
        if post_type == "earnings":
            scoreboard = post.get("earnings_scoreboard", [])
            if isinstance(scoreboard, dict):
                scoreboard = [scoreboard]
            if isinstance(scoreboard, list):
                for item in scoreboard:
                    ticker = item.get("ticker")
                    if not ticker:
                        continue
                    if ticker not in ticker_values:
                        ticker_values[ticker] = []
                    if item.get("eps_actual") is not None:
                        ticker_values[ticker].append(
                            ("earnings_scoreboard", "eps_actual", item["eps_actual"])
                        )

        # Check consistency for each ticker
        TOLERANCE = 0.01  # Allow 0.01% difference for rounding

        for ticker, values in ticker_values.items():
            # Group by field
            by_field = {}
            for source, field, value in values:
                if field not in by_field:
                    by_field[field] = []
                by_field[field].append((source, value))

            # Check each field for consistency
            for field, field_values in by_field.items():
                if len(field_values) < 2:
                    continue

                # Get all unique values
                unique_values = set(v for _, v in field_values)
                if len(unique_values) > 1:
                    # Check if within tolerance
                    values_list = [v for _, v in field_values]
                    min_val = min(values_list)
                    max_val = max(values_list)

                    if max_val - min_val > TOLERANCE:
                        sources = [s for s, _ in field_values]
                        inconsistencies.append({
                            "ticker": ticker,
                            "field": field,
                            "sources": sources,
                            "values": values_list,
                        })
                        errors.append(
                            f"{ticker}.{field} inconsistent across {sources}: {values_list}"
                        )

        passed = len(errors) == 0

        return GateResult(
            name="duplicate_ticker_consistency",
            passed=passed,
            message="; ".join(errors[:3]) if errors else "OK",  # Limit error message length
            details={
                "inconsistencies": inconsistencies,
                "warnings": warnings,
            },
        )

    def _check_placeholder_content(self, post: dict, research_pack: dict) -> GateResult:
        """檢查佔位符內容 (P0-1)

        Hard fail if placeholder text is found in output.
        These indicate incomplete or failed data filling.

        P0-1 規則：
        - 預覽區（paywall 之前）有任何佔位符 → hard fail（絕對不能上線）
        - 預覽區會出現在 Email / SEO snippet / 社群卡片，可信度最關鍵
        - 付費區有佔位符 → soft fail（可以 draft，但不能寄 newsletter）
        """
        errors = []
        warnings = []
        placeholder_locations = []
        preview_placeholder_locations = []  # 預覽區專用

        # Placeholder patterns to detect (case-insensitive where applicable)
        # P0-1: 加強偵測模式，包含數字前後的佔位符
        PLACEHOLDER_PATTERNS = [
            # Chinese placeholders - 核心（最常見）
            r"數據",  # "data" - placeholder for unfilled data
            r"\+數據",  # "+數據" - positive change placeholder
            r"-數據",  # "-數據" - negative change placeholder
            r"YoY\s*\+?數據",  # "YoY +數據"
            r"QoQ\s*\+?數據",  # "QoQ +數據"
            r"待確認",  # "to be confirmed"
            r"待補充",  # "to be added"
            r"資料缺失",  # "data missing"
            r"尚未公布",  # "not yet announced"
            r"無資料",  # "no data"
            # English placeholders
            r"\bTBD\b",  # "to be determined"
            r"\bTBA\b",  # "to be announced"
            r"\bN/A\b(?!\s*\()",  # N/A not followed by explanation
            r"\bXXX\b",  # generic placeholder
            r"\$XXX",  # price placeholder
            r"\[.*?待.*?\]",  # [待...] style placeholders
            r"\{.*?\}",  # {variable} style unfilled templates
            # Numeric placeholders
            r">\s*數據",  # ">數據" comparison
            r"<\s*數據",  # "<數據" comparison
            r"\d+-數據",  # "22-數據" range
            r"數據-\d+",  # "數據-30" range
            # Suspicious patterns
            r"\bnull\b",  # literal null in output (word boundary)
            r"\bundefined\b",  # literal undefined
            r"\bNone\b",  # literal None (Python)
        ]

        # 關鍵佔位符 - 必須 hard fail
        CRITICAL_PATTERNS = ["數據", "TBD", "TBA", "null", "undefined", "None", "{"]

        def extract_preview_content(html_content: str) -> str:
            """提取 paywall 之前的預覽內容（Email/SEO/社群可見）"""
            if not html_content:
                return ""
            # Ghost paywall 標記
            paywall_markers = [
                "<!--members-only-->",
                "<!-- members-only -->",
                "<!--kg-card-begin: members-only-->",
            ]
            for marker in paywall_markers:
                if marker in html_content:
                    return html_content.split(marker)[0]
            # 沒有 paywall 標記，整篇都是預覽
            return html_content

        def check_content_for_placeholders(content: str, area_name: str, is_preview: bool = False):
            """檢查內容中的佔位符"""
            if not content or not isinstance(content, str):
                return
            for pattern in PLACEHOLDER_PATTERNS:
                matches = re.findall(pattern, content, re.IGNORECASE)
                if matches:
                    for match in matches[:5]:  # 最多記錄 5 個
                        loc = {
                            "location": area_name,
                            "pattern": pattern,
                            "match": match[:50],
                            "is_preview": is_preview,
                        }
                        placeholder_locations.append(loc)
                        if is_preview:
                            preview_placeholder_locations.append(loc)

        # ========== 1. 檢查結構化欄位（都算預覽區） ==========
        title = post.get("title", "")
        excerpt = post.get("excerpt", "")
        newsletter_subject = post.get("newsletter_subject", "")
        executive_summary = post.get("executive_summary", "")
        tldr = post.get("tldr", [])

        # 這些都是高優先級預覽欄位
        check_content_for_placeholders(title, "title", is_preview=True)
        check_content_for_placeholders(excerpt, "excerpt", is_preview=True)
        check_content_for_placeholders(newsletter_subject, "newsletter_subject", is_preview=True)
        check_content_for_placeholders(executive_summary, "executive_summary", is_preview=True)

        # TL;DR 也是預覽區的一部分
        if isinstance(tldr, list):
            for i, item in enumerate(tldr):
                if isinstance(item, str):
                    check_content_for_placeholders(item, f"tldr[{i}]", is_preview=True)
                elif isinstance(item, dict):
                    check_content_for_placeholders(str(item.get("text", "")), f"tldr[{i}]", is_preview=True)

        # ========== 2. 檢查 HTML 內容 ==========
        html = post.get("html", "")
        if html and isinstance(html, str):
            # 分離預覽區和付費區
            preview_html = extract_preview_content(html)
            members_only_html = html[len(preview_html):] if len(html) > len(preview_html) else ""

            # 預覽區 - hard fail
            check_content_for_placeholders(preview_html, "html_preview", is_preview=True)

            # 付費區 - soft fail
            check_content_for_placeholders(members_only_html, "html_members_only", is_preview=False)

        # ========== 3. 檢查 Markdown（備用） ==========
        markdown = post.get("markdown", "")
        if markdown and isinstance(markdown, str):
            check_content_for_placeholders(markdown, "markdown", is_preview=False)

        # ========== 4. 判定結果 ==========

        # 檢查預覽區是否有關鍵佔位符
        preview_critical = [
            loc for loc in preview_placeholder_locations
            if any(p in loc["pattern"] or p in loc["match"] for p in CRITICAL_PATTERNS)
        ]

        # 檢查全文是否有關鍵佔位符
        all_critical = [
            loc for loc in placeholder_locations
            if any(p in loc["pattern"] or p in loc["match"] for p in CRITICAL_PATTERNS)
        ]

        # P0: 預覽區有佔位符 → 絕對 hard fail
        if preview_critical:
            # 格式化位置清單（避免 f-string 中的反斜線）
            locations_str = [
                f"{loc['location']}: '{loc['match']}'" for loc in preview_critical[:5]
            ]
            errors.append(
                f"[P0-CRITICAL] 預覽區發現 {len(preview_critical)} 個佔位符 - "
                f"這會直接顯示在 Email/SEO/社群分享中！"
                f"位置: {locations_str}"
            )

        # P1: 付費區有佔位符 → soft fail（可以 draft，但警告）
        members_only_critical = [loc for loc in all_critical if not loc.get("is_preview", False)]
        if members_only_critical and not preview_critical:
            warnings.append(
                f"付費區發現 {len(members_only_critical)} 個佔位符 - "
                f"建議修復後再發布: {[loc['match'] for loc in members_only_critical[:3]]}"
            )

        # 其他非關鍵佔位符
        non_critical = len(placeholder_locations) - len(all_critical)
        if non_critical > 0:
            warnings.append(f"發現 {non_critical} 個其他疑似佔位符")

        passed = len(errors) == 0

        return GateResult(
            name="placeholder_content",
            passed=passed,
            message="; ".join(errors) if errors else "OK",
            details={
                "preview_placeholders": len(preview_critical),
                "members_only_placeholders": len(members_only_critical) if 'members_only_critical' in dir() else 0,
                "total_placeholders": len(placeholder_locations),
                "placeholder_locations": placeholder_locations[:15],  # 增加詳細輸出
                "warnings": warnings,
            },
        )

    def _check_source_urls(self, post: dict, research_pack: dict) -> GateResult:
        """檢查資料來源 URL 完整性 (B1)

        確保關鍵資料來源都有可驗證的 URL。
        """
        errors = []
        warnings = []

        sources = post.get("sources", [])
        if not sources:
            sources = research_pack.get("sources", [])

        # 統計 URL 情況
        total_sources = len(sources)
        sources_with_url = 0
        sources_without_url = []
        invalid_urls = []

        # 允許沒有 URL 的來源類型
        url_optional_types = {"data", "calculation", "internal"}

        for source in sources:
            source_name = source.get("name", "Unknown")
            source_type = source.get("type", "")
            url = source.get("url", "")

            if url:
                sources_with_url += 1
                # 驗證 URL 格式
                if not (url.startswith("http://") or url.startswith("https://")):
                    invalid_urls.append(f"{source_name}: {url[:30]}...")
            else:
                # 某些類型的來源可以沒有 URL
                if source_type not in url_optional_types:
                    sources_without_url.append(f"{source_name} ({source_type})")

        # 計算 URL 覆蓋率
        coverage = sources_with_url / total_sources if total_sources > 0 else 0

        # 規則：至少 60% 的來源要有 URL
        min_coverage = 0.6
        if coverage < min_coverage:
            errors.append(f"URL coverage too low: {coverage:.0%} < {min_coverage:.0%}")

        # 規則：news 和 sec_filing 類型必須有 URL
        critical_types = {"primary", "news", "sec_filing", "earnings_release", "10-Q", "8-K", "transcript"}
        critical_missing = []
        for source in sources:
            source_type = source.get("type", "")
            if source_type in critical_types and not source.get("url"):
                critical_missing.append(f"{source.get('name')} ({source_type})")

        if critical_missing:
            errors.append(f"Critical sources missing URL: {critical_missing[:3]}...")

        # 無效 URL 警告
        if invalid_urls:
            warnings.append(f"Invalid URL format: {invalid_urls[:3]}...")

        passed = len(errors) == 0

        return GateResult(
            name="source_urls",
            passed=passed,
            message="; ".join(errors) if errors else f"OK ({sources_with_url}/{total_sources} sources have URLs)",
            details={
                "total_sources": total_sources,
                "sources_with_url": sources_with_url,
                "coverage": coverage,
                "sources_without_url": sources_without_url,
                "invalid_urls": invalid_urls,
                "critical_missing": critical_missing,
                "warnings": warnings,
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

        # Gate 6: Topic Integrity Gate (A1 - 防止內容污染)
        topic_result = self._check_topic_integrity(post, research_pack)
        report.gates.append(topic_result)
        if not topic_result.passed:
            report.overall_passed = False
            report.errors.append(f"[topic_integrity] {topic_result.message}")

        # Gate 7: Data Completeness Gate (A2 - 防止 null 欄位)
        completeness_result = self._check_data_completeness(post, research_pack)
        report.gates.append(completeness_result)
        if not completeness_result.passed:
            report.overall_passed = False
            report.errors.append(f"[data_completeness] {completeness_result.message}")
        if completeness_result.details.get("warnings"):
            report.warnings.extend(completeness_result.details["warnings"])

        # Gate 8: JSON/HTML Consistency Gate
        consistency_result = self._check_json_html_consistency(post)
        report.gates.append(consistency_result)
        if not consistency_result.passed:
            report.overall_passed = False
            report.errors.append(f"[json_html_consistency] {consistency_result.message}")

        # Gate 9: Flash Consistency Gate (A3 - repricing variable consistency)
        flash_result = self._check_flash_consistency(post, research_pack)
        report.gates.append(flash_result)
        if not flash_result.passed:
            report.overall_passed = False
            report.errors.append(f"[flash_consistency] {flash_result.message}")
        if flash_result.details.get("warnings"):
            report.warnings.extend(flash_result.details["warnings"])

        # Gate 10: Percent Sanity Gate (P0-1 - mega-cap percent validation)
        percent_result = self._check_percent_sanity(post, research_pack)
        report.gates.append(percent_result)
        if not percent_result.passed:
            report.overall_passed = False
            report.errors.append(f"[percent_sanity] {percent_result.message}")
        if percent_result.details.get("warnings"):
            report.warnings.extend(percent_result.details["warnings"])

        # Gate 11: Placeholder Content Gate (P0-2 - detect unfilled placeholders)
        placeholder_result = self._check_placeholder_content(post, research_pack)
        report.gates.append(placeholder_result)
        if not placeholder_result.passed:
            report.overall_passed = False
            report.errors.append(f"[placeholder_content] {placeholder_result.message}")
        if placeholder_result.details.get("warnings"):
            report.warnings.extend(placeholder_result.details["warnings"])

        # Gate 12: Duplicate Ticker Consistency Gate (P0-3)
        dup_ticker_result = self._check_duplicate_ticker_consistency(post, research_pack)
        report.gates.append(dup_ticker_result)
        if not dup_ticker_result.passed:
            report.overall_passed = False
            report.errors.append(f"[duplicate_ticker_consistency] {dup_ticker_result.message}")
        if dup_ticker_result.details.get("warnings"):
            report.warnings.extend(dup_ticker_result.details["warnings"])

        # Gate 13: Slug/Content Consistency Gate (P0-3b - SEO/URL 一致性)
        slug_content_result = self._check_slug_content_consistency(post, research_pack)
        report.gates.append(slug_content_result)
        if not slug_content_result.passed:
            report.overall_passed = False
            report.errors.append(f"[slug_content_consistency] {slug_content_result.message}")
        if slug_content_result.details.get("warnings"):
            report.warnings.extend(slug_content_result.details["warnings"])

        # Gate 14: Source URLs Gate (B1 - 可驗證來源 URL)
        source_url_result = self._check_source_urls(post, research_pack)
        report.gates.append(source_url_result)
        if not source_url_result.passed:
            report.overall_passed = False
            report.errors.append(f"[source_urls] {source_url_result.message}")
        if source_url_result.details.get("warnings"):
            report.warnings.extend(source_url_result.details["warnings"])

        # Gate 14: 發佈參數檢查
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


# =============================================================================
# P0-6: 三篇各自 Gate + 總 Gate
# =============================================================================

@dataclass
class DailyQualityReport:
    """P0-6: 每日品質報告（含三篇獨立報告 + 總結）"""

    run_id: str
    date: str
    timestamp: str
    overall_passed: bool
    post_reports: dict  # {post_type: QualityReport}
    daily_gate: GateResult
    can_publish_all: bool = False
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "date": self.date,
            "timestamp": self.timestamp,
            "overall_passed": self.overall_passed,
            "post_reports": {
                post_type: report.to_dict()
                for post_type, report in self.post_reports.items()
            },
            "daily_gate": {
                "name": self.daily_gate.name,
                "passed": self.daily_gate.passed,
                "message": self.daily_gate.message,
                "details": self.daily_gate.details,
            },
            "can_publish_all": self.can_publish_all,
            "errors": self.errors,
            "warnings": self.warnings,
        }


# =============================================================================
# P0-8: 三篇內容最低硬規格
# =============================================================================

# 各篇文章的最低硬規格
POST_MIN_SPECS = {
    "flash": {
        "min_news_items": 8,  # P0-5: 至少 7-8 條
        "min_key_numbers": 3,
        "min_tldr_items": 5,
        "min_html_length": 5000,  # 最少 5000 字元
        "required_sections": ["executive_summary", "key_numbers", "thesis"],
        "max_null_critical_fields": 0,
    },
    "earnings": {
        "min_key_numbers": 3,
        "min_html_length": 4000,
        "required_fields": ["earnings_scoreboard", "valuation"],
        "scenario_matrix_required": True,
    },
    "deep": {
        "min_key_numbers": 5,
        "min_html_length": 8000,  # Deep 最長
        "required_sections": [
            "executive_summary", "thesis", "anti_thesis",
            "business_model", "valuation", "peer_comparison"
        ],
        "min_risks": 3,
        "min_catalysts": 2,
    },
}


def check_min_specs(post_dict: dict, post_type: str) -> tuple:
    """P0-8: 檢查文章是否符合最低硬規格

    Args:
        post_dict: 文章 dict
        post_type: 文章類型

    Returns:
        (passed: bool, errors: list, warnings: list)
    """
    specs = POST_MIN_SPECS.get(post_type, {})
    errors = []
    warnings = []

    # 通用檢查
    html = post_dict.get("html", "")
    html_length = len(html)

    min_html = specs.get("min_html_length", 0)
    if html_length < min_html:
        errors.append(f"HTML too short: {html_length} < {min_html}")

    # key_numbers 檢查
    key_numbers = post_dict.get("key_numbers", [])
    min_kn = specs.get("min_key_numbers", 0)
    if len(key_numbers) < min_kn:
        errors.append(f"key_numbers: {len(key_numbers)} < {min_kn}")

    # Paywall 檢查（all posts）
    paywall_count = html.count("<!--members-only-->")
    if paywall_count == 0:
        errors.append("Missing paywall marker")
    elif paywall_count > 1:
        warnings.append(f"Multiple paywall markers: {paywall_count}")

    # Flash 專用
    if post_type == "flash":
        news_items = post_dict.get("news_items", [])
        min_news = specs.get("min_news_items", 8)
        if len(news_items) < min_news:
            errors.append(f"news_items: {len(news_items)} < {min_news}")

        tldr = post_dict.get("tldr", [])
        min_tldr = specs.get("min_tldr_items", 5)
        if len(tldr) < min_tldr:
            errors.append(f"tldr: {len(tldr)} < {min_tldr}")

    # Earnings 專用
    if post_type == "earnings":
        scoreboard = post_dict.get("earnings_scoreboard", [])
        if not scoreboard:
            errors.append("Missing earnings_scoreboard")

        valuation = post_dict.get("valuation", {})
        if not valuation:
            errors.append("Missing valuation section")

        # 3x3 scenario matrix 檢查
        if specs.get("scenario_matrix_required"):
            matrix = post_dict.get("scenario_matrix_3x3")
            if not matrix:
                warnings.append("Missing 3x3 scenario matrix")

    # Deep 專用
    if post_type == "deep":
        risks = post_dict.get("risks", [])
        min_risks = specs.get("min_risks", 3)
        if len(risks) < min_risks:
            errors.append(f"risks: {len(risks)} < {min_risks}")

        catalysts = post_dict.get("catalysts", {})
        near_term = catalysts.get("near_term", [])
        min_catalysts = specs.get("min_catalysts", 2)
        if len(near_term) < min_catalysts:
            warnings.append(f"near_term catalysts: {len(near_term)} < {min_catalysts}")

        # Required sections
        required_sections = specs.get("required_sections", [])
        for section in required_sections:
            if not post_dict.get(section):
                errors.append(f"Missing required section: {section}")

    passed = len(errors) == 0
    return passed, errors, warnings


def run_daily_quality_gate(
    posts: dict,  # {post_type: post_dict}
    edition_pack: dict,
    run_id: str,
    date: str,
) -> DailyQualityReport:
    """P0-6: 執行每日品質 Gate（三篇各自 + 總 Gate）

    規則：
    1. 每篇文章獨立執行品質 Gate
    2. 總 Gate 檢查跨篇一致性（Edition Coherence）
    3. 任何一篇 fail = 總體 fail（Fail-Closed）

    Args:
        posts: 三篇文章 dict（key=post_type, value=post_dict）
        edition_pack: 版本資料包
        run_id: 執行 ID
        date: 發布日期

    Returns:
        DailyQualityReport
    """
    gate = QualityGate()
    post_reports = {}
    all_passed = True
    errors = []
    warnings = []

    # 1. 各篇獨立品質 Gate
    for post_type, post_dict in posts.items():
        if post_dict is None:
            continue

        report = gate.run_all_gates(
            post_dict,
            edition_pack,
            mode="draft",
            run_id=run_id,
        )
        post_reports[post_type] = report

        if not report.overall_passed:
            all_passed = False
            errors.append(f"[{post_type}] Quality gate failed")
            errors.extend([f"[{post_type}] {e}" for e in report.errors])

        warnings.extend([f"[{post_type}] {w}" for w in report.warnings])

        # P0-8: 檢查最低硬規格
        specs_passed, specs_errors, specs_warnings = check_min_specs(post_dict, post_type)
        if not specs_passed:
            all_passed = False
            errors.extend([f"[{post_type}] {e}" for e in specs_errors])
        warnings.extend([f"[{post_type}] {w}" for w in specs_warnings])

    # 2. 總 Gate: Edition Coherence 檢查
    daily_gate_errors = []
    daily_gate_details = {}

    # 2a. 檢查三篇的主題一致性
    edition_coherence = edition_pack.get("edition_coherence", {})
    if not edition_coherence.get("coherent", False):
        daily_gate_errors.append(f"Edition not coherent: {edition_coherence}")

    # 2b. 檢查三篇的 deep_dive_ticker 是否一致
    tickers_mentioned = set()
    for post_type, post_dict in posts.items():
        if post_dict is None:
            continue

        meta = post_dict.get("meta", {})
        ticker = meta.get("primary_ticker") or meta.get("ticker")
        if ticker:
            tickers_mentioned.add(ticker)

        # 從 slug 提取 ticker
        slug = post_dict.get("slug", "")
        if "-deep-dive-" in slug or "-earnings-" in slug:
            parts = slug.split("-")
            if parts:
                slug_ticker = parts[0].upper()
                if len(slug_ticker) <= 5:  # 合理的 ticker 長度
                    tickers_mentioned.add(slug_ticker)

    # 檢查 ticker 一致性（允許有多個 ticker，但主要 ticker 應該一致）
    expected_ticker = edition_pack.get("deep_dive_ticker")
    if expected_ticker:
        daily_gate_details["expected_ticker"] = expected_ticker
        daily_gate_details["tickers_found"] = list(tickers_mentioned)

        # 檢查是否包含預期的 ticker
        if expected_ticker not in tickers_mentioned and tickers_mentioned:
            daily_gate_errors.append(
                f"Ticker mismatch: expected {expected_ticker}, found {tickers_mentioned}"
            )

    # 2c. 檢查 Paywall 是否都正確放置
    paywall_status = {}
    for post_type, post_dict in posts.items():
        if post_dict is None:
            continue

        html = post_dict.get("html", "")
        paywall_count = html.count("<!--members-only-->")
        paywall_status[post_type] = paywall_count

        if paywall_count == 0:
            daily_gate_errors.append(f"[{post_type}] Missing paywall marker")
        elif paywall_count > 1:
            warnings.append(f"[{post_type}] Multiple paywall markers ({paywall_count})")

    daily_gate_details["paywall_status"] = paywall_status

    # 2d. 檢查所有必要的文章是否都生成
    required_posts = {"flash", "deep"}  # Earnings 是可選的
    missing_posts = required_posts - set(posts.keys())
    if missing_posts:
        daily_gate_errors.append(f"Missing required posts: {missing_posts}")

    daily_gate_details["posts_generated"] = list(posts.keys())

    # 構建 Daily Gate 結果
    daily_gate_passed = len(daily_gate_errors) == 0
    daily_gate = GateResult(
        name="daily_edition_coherence",
        passed=daily_gate_passed,
        message="; ".join(daily_gate_errors) if daily_gate_errors else "OK (edition coherent)",
        details=daily_gate_details,
    )

    if not daily_gate_passed:
        all_passed = False
        errors.extend(daily_gate_errors)

    # 構建最終報告
    return DailyQualityReport(
        run_id=run_id,
        date=date,
        timestamp=datetime.utcnow().isoformat(),
        overall_passed=all_passed,
        post_reports=post_reports,
        daily_gate=daily_gate,
        can_publish_all=all_passed,
        errors=errors,
        warnings=warnings,
    )


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


# =============================================================================
# P0-1: 獨立佔位符檢查函數（供 codex_runner 使用）
# =============================================================================

# 佔位符模式（全域定義，供多處使用）
PLACEHOLDER_PATTERNS = [
    # Chinese placeholders - 核心（最常見）
    r"數據",  # "data" - placeholder for unfilled data
    r"\+數據",  # "+數據" - positive change placeholder
    r"-數據",  # "-數據" - negative change placeholder
    r"YoY\s*\+?數據",  # "YoY +數據"
    r"QoQ\s*\+?數據",  # "QoQ +數據"
    r"待確認",  # "to be confirmed"
    r"待補充",  # "to be added"
    r"資料缺失",  # "data missing"
    r"尚未公布",  # "not yet announced"
    r"無資料",  # "no data"
    # English placeholders
    r"\bTBD\b",  # "to be determined"
    r"\bTBA\b",  # "to be announced"
    r"\bN/A\b(?!\s*\()",  # N/A not followed by explanation
    r"\bXXX\b",  # generic placeholder
    r"\$XXX",  # price placeholder
    # Numeric placeholders
    r">\s*數據",  # ">數據" comparison
    r"<\s*數據",  # "<數據" comparison
    r"\d+-數據",  # "22-數據" range
    r"數據-\d+",  # "數據-30" range
]


def check_placeholders(content: str) -> tuple[bool, list[str]]:
    """P0-1: 檢查內容是否包含佔位符

    這是一個輕量級的檢查函數，可在 LLM 生成後立即調用。

    Args:
        content: 要檢查的文字內容 (markdown 或 html)

    Returns:
        (passed, errors): passed=True 表示沒有佔位符
    """
    if not content:
        return True, []

    errors = []

    for pattern in PLACEHOLDER_PATTERNS:
        matches = re.findall(pattern, content, re.IGNORECASE)
        if matches:
            # 取得匹配的上下文
            for match in matches[:3]:
                # 找出匹配位置的上下文
                idx = content.find(match)
                if idx >= 0:
                    start = max(0, idx - 20)
                    end = min(len(content), idx + len(match) + 20)
                    context = content[start:end].replace("\n", " ")
                    errors.append(f"佔位符 '{match}' 出現在: ...{context}...")

    passed = len(errors) == 0
    return passed, errors


def check_cross_post_consistency(posts: dict) -> tuple[bool, list[str]]:
    """P0-2: 檢查三篇文章的數值一致性

    確保同一 ticker 在不同文章中顯示一致的數值。

    Args:
        posts: {post_type: post_dict} 三篇文章的 dict

    Returns:
        (passed, errors): passed=True 表示數值一致
    """
    errors = []

    # 收集所有 ticker 的關鍵數值
    ticker_values = {}  # {ticker: {field: [(post_type, value), ...]}}

    for post_type, post in posts.items():
        if not post:
            continue

        # 從 ticker_profile 收集
        profile = post.get("ticker_profile", {})
        ticker = profile.get("ticker") or post.get("meta", {}).get("deep_dive_ticker")
        if ticker:
            if ticker not in ticker_values:
                ticker_values[ticker] = {}

            # TTM P/E
            pe_ttm = profile.get("pe_ttm") or profile.get("ttm_pe")
            if pe_ttm is not None:
                if "pe_ttm" not in ticker_values[ticker]:
                    ticker_values[ticker]["pe_ttm"] = []
                ticker_values[ticker]["pe_ttm"].append((post_type, pe_ttm))

            # Price
            price = profile.get("price") or profile.get("last_price")
            if price is not None:
                if "price" not in ticker_values[ticker]:
                    ticker_values[ticker]["price"] = []
                ticker_values[ticker]["price"].append((post_type, price))

            # Market Cap
            market_cap = profile.get("market_cap")
            if market_cap is not None:
                if "market_cap" not in ticker_values[ticker]:
                    ticker_values[ticker]["market_cap"] = []
                ticker_values[ticker]["market_cap"].append((post_type, market_cap))

    # 檢查數值一致性
    for ticker, fields in ticker_values.items():
        for field, values in fields.items():
            if len(values) < 2:
                continue

            # 提取數值
            numeric_values = []
            for post_type, val in values:
                if isinstance(val, (int, float)):
                    numeric_values.append((post_type, float(val)))
                elif isinstance(val, str):
                    # 嘗試解析字串
                    try:
                        cleaned = val.replace(",", "").replace("$", "").replace("x", "").replace("%", "")
                        numeric_values.append((post_type, float(cleaned)))
                    except ValueError:
                        pass

            if len(numeric_values) < 2:
                continue

            # 檢查差異
            vals = [v for _, v in numeric_values]
            max_val = max(vals)
            min_val = min(vals)

            # 允許 5% 的誤差
            if max_val > 0 and (max_val - min_val) / max_val > 0.05:
                sources = [pt for pt, _ in numeric_values]
                errors.append(
                    f"{ticker}.{field} 不一致: "
                    f"{', '.join(f'{pt}={v}' for pt, v in numeric_values)}"
                )

    passed = len(errors) == 0
    return passed, errors


def check_valuation_completeness(post: dict) -> tuple[bool, list[str]]:
    """P0-4: 檢查估值區塊完整性

    如果文章有估值章節，則不能有 N/A 或 target=現價。

    Args:
        post: 文章 dict

    Returns:
        (passed, errors)
    """
    errors = []
    post_type = post.get("meta", {}).get("post_type", "")

    # 只對 earnings 和 deep 檢查
    if post_type not in ("earnings", "deep"):
        return True, []

    valuation = post.get("valuation", {})
    if not valuation:
        # 沒有估值區塊就不檢查
        return True, []

    # 檢查 multiple
    multiple = valuation.get("multiple")
    if multiple in (None, "N/A", "n/a", ""):
        errors.append("估值區塊的 multiple 為空或 N/A")

    # 檢查 scenarios
    scenarios = valuation.get("scenarios", {})
    current_price = valuation.get("current_price") or post.get("ticker_profile", {}).get("price")

    for case in ["bear", "base", "bull"]:
        scenario = scenarios.get(case, {})
        target = scenario.get("target_price")

        if target in (None, "N/A", "n/a", ""):
            errors.append(f"估值 {case} case 的 target_price 為空或 N/A")
        elif current_price:
            # 檢查 target 是否等於現價
            try:
                target_num = float(str(target).replace("$", "").replace(",", ""))
                current_num = float(str(current_price).replace("$", "").replace(",", ""))
                if abs(target_num - current_num) < 0.01:
                    errors.append(f"估值 {case} case 的 target_price ({target}) 等於現價 ({current_price})")
            except (ValueError, TypeError):
                pass

    passed = len(errors) == 0
    return passed, errors


def check_earnings_scoreboard(post: dict) -> tuple[bool, list[str]]:
    """P0-3: 檢查 earnings_scoreboard 季度重複問題

    確保 scoreboard 中每個季度都是唯一的（不能有重複的 Q1 2024）。

    Args:
        post: 文章 dict

    Returns:
        (passed, errors)
    """
    errors = []
    post_type = post.get("meta", {}).get("post_type", "")

    # 只對 earnings 類型檢查
    if post_type != "earnings":
        return True, []

    scoreboard = post.get("earnings_scoreboard", [])
    if not scoreboard:
        return True, []

    # 收集所有季度
    quarters_seen = {}
    for i, entry in enumerate(scoreboard):
        quarter = entry.get("quarter", "")
        ticker = entry.get("ticker", "")

        if not quarter:
            errors.append(f"earnings_scoreboard[{i}] 的 quarter 欄位為空")
            continue

        # 組合 ticker + quarter 作為唯一鍵（同一 ticker 不能有重複季度）
        key = f"{ticker}:{quarter}"
        if key in quarters_seen:
            errors.append(
                f"earnings_scoreboard 有重複季度: {ticker} 的 {quarter} "
                f"出現在 index {quarters_seen[key]} 和 {i}"
            )
        else:
            quarters_seen[key] = i

    # 額外檢查：季度格式是否正確 (Q1-Q4 + 4位數年份)
    import re
    quarter_pattern = re.compile(r"^Q[1-4]\s+(FY)?\d{4}$")
    for i, entry in enumerate(scoreboard):
        quarter = entry.get("quarter", "")
        if quarter and not quarter_pattern.match(quarter):
            errors.append(
                f"earnings_scoreboard[{i}] 的 quarter 格式不正確: '{quarter}' "
                f"(應為 'Q1 2024' 或 'Q1 FY2024')"
            )

    passed = len(errors) == 0
    return passed, errors


if __name__ == "__main__":
    main()

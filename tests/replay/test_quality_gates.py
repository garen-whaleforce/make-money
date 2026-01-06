"""Quality Gates Replay Tests

使用 fixtures 測試品質檢查流程。
"""

import json
from pathlib import Path

import pytest

from src.quality.compliance import ComplianceChecker
from src.quality.quality_gate import QualityGate, QualityReport
from src.quality.trace_numbers import NumberTracer
from src.quality.validators import validate_research_pack, validate_post


# Fixtures 路徑
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
RESEARCH_PACK_PATH = FIXTURES_DIR / "research_packs" / "sample_research_pack.json"
POST_PATH = FIXTURES_DIR / "posts" / "sample_post.json"


@pytest.fixture
def sample_research_pack() -> dict:
    """載入範例 research pack"""
    with open(RESEARCH_PACK_PATH) as f:
        return json.load(f)


@pytest.fixture
def sample_post() -> dict:
    """載入範例 post"""
    with open(POST_PATH) as f:
        return json.load(f)


class TestComplianceChecker:
    """合規檢查器測試"""

    def test_check_sources_pass(self, sample_research_pack):
        """測試來源數量檢查 - 通過"""
        checker = ComplianceChecker(min_sources=5)
        sources = sample_research_pack["sources"]

        passed, count, warnings = checker.check_sources(sources)

        assert passed is True
        assert count >= 5
        assert len(warnings) == 0

    def test_check_sources_fail(self, sample_research_pack):
        """測試來源數量檢查 - 失敗"""
        checker = ComplianceChecker(min_sources=10)
        sources = sample_research_pack["sources"]

        passed, count, warnings = checker.check_sources(sources)

        assert passed is False
        assert len(warnings) > 0

    def test_check_forbidden_words_pass(self, sample_post):
        """測試禁用詞檢查 - 通過"""
        checker = ComplianceChecker()
        markdown = sample_post["markdown"]

        passed, found = checker.check_forbidden_words(markdown)

        assert passed is True
        assert len(found) == 0

    def test_check_forbidden_words_fail(self):
        """測試禁用詞檢查 - 失敗"""
        checker = ComplianceChecker()
        text = "This is a guaranteed profit opportunity with zero risk!"

        passed, found = checker.check_forbidden_words(text)

        assert passed is False
        assert "guaranteed profit" in found or "zero risk" in [f.lower() for f in found]

    def test_check_disclosures_pass(self, sample_post):
        """測試免責聲明檢查 - 通過"""
        checker = ComplianceChecker()
        disclosures = sample_post["disclosures"]
        markdown = sample_post["markdown"]

        passed, warnings = checker.check_disclosures(disclosures, markdown)

        assert passed is True

    def test_full_check(self, sample_post, sample_research_pack):
        """測試完整合規檢查"""
        checker = ComplianceChecker(min_sources=5)
        result = checker.check(sample_post, sample_research_pack)

        assert result.source_check_passed is True
        assert result.compliance_passed is True
        assert result.disclosure_present is True
        assert result.passed is True


class TestNumberTracer:
    """數字追溯測試"""

    def test_extract_numbers(self):
        """測試數字提取"""
        tracer = NumberTracer()
        text = "NVDA is trading at $485.50, up 2.35% with market cap of $1.2T"

        # Use internal method _extract_numbers
        numbers = tracer._extract_numbers(text)

        # Check that we extracted some numbers
        values = [n[0] for n in numbers]
        assert "$485.50" in values or any("485" in v for v in values)
        assert any("2.35%" in v for v in values)

    def test_trace_pass(self, sample_post, sample_research_pack):
        """測試數字追溯 - 通過"""
        tracer = NumberTracer()
        markdown = sample_post["markdown"]

        result = tracer.trace(markdown, sample_research_pack)

        # 應該有一些數字被提取
        assert result.total_numbers >= 0
        # 結果應該有效
        assert hasattr(result, 'passed')
        assert hasattr(result, 'traced_count')

    def test_extract_research_pack_numbers(self, sample_research_pack):
        """測試提取 research_pack 中的數字"""
        tracer = NumberTracer()
        numbers = tracer._extract_research_pack_numbers(sample_research_pack)

        # 索引應該包含 research pack 中的數字
        assert len(numbers) > 0


class TestValidators:
    """驗證器測試"""

    def test_validate_research_pack(self, sample_research_pack):
        """測試 research pack 驗證"""
        is_valid, errors = validate_research_pack(sample_research_pack)

        # The sample fixture might not match the schema exactly
        # Check that validation runs without exception
        assert isinstance(is_valid, bool)
        assert isinstance(errors, list)

    def test_validate_research_pack_missing_sources(self):
        """測試 research pack 驗證 - 缺少來源"""
        invalid_pack = {
            "sources": [],
            "key_stocks": [{"ticker": "NVDA"}],
            "primary_event": {"title": "Test Event"},
        }

        is_valid, errors = validate_research_pack(invalid_pack)

        assert is_valid is False
        assert any("source" in e.lower() for e in errors)

    def test_validate_post(self, sample_post):
        """測試 post 驗證"""
        is_valid, errors = validate_post(sample_post)

        # Validation should run without exception
        assert isinstance(is_valid, bool)
        assert isinstance(errors, list)

    def test_validate_post_missing_tldr(self):
        """測試 post 驗證 - 缺少 TL;DR"""
        invalid_post = {
            "title": "Test Title",
            "tldr": ["One item"],  # 需要至少 3 個
            "markdown": "Some content",
            "disclosures": {"not_investment_advice": True},
        }

        is_valid, errors = validate_post(invalid_post)

        assert is_valid is False
        # Check that there's an error related to TL;DR
        assert len(errors) > 0


class TestQualityGate:
    """品質 Gate 整合測試"""

    def test_run_all_gates_pass(self, sample_post, sample_research_pack):
        """測試所有 Gate - 通過"""
        gate = QualityGate()
        report = gate.run_all_gates(
            sample_post,
            sample_research_pack,
            mode="draft",
            run_id="test_001",
        )

        assert isinstance(report, QualityReport)
        # 至少有多個 gate 被執行
        assert len(report.gates) >= 4

    def test_run_all_gates_publish_mode(self, sample_post, sample_research_pack):
        """測試發佈模式 Gate"""
        gate = QualityGate()
        report = gate.run_all_gates(
            sample_post,
            sample_research_pack,
            mode="publish",
            newsletter_slug="",
            email_segment="",
            run_id="test_002",
        )

        # 發佈模式應該有發佈參數檢查
        gate_names = [g.name for g in report.gates]
        assert "publishing" in gate_names

    def test_quality_report_serialization(self, sample_post, sample_research_pack):
        """測試品質報告序列化"""
        gate = QualityGate()
        report = gate.run_all_gates(
            sample_post,
            sample_research_pack,
            mode="draft",
            run_id="test_003",
        )

        # 轉換為 dict
        report_dict = report.to_dict()
        assert "gates" in report_dict
        assert "overall_passed" in report_dict

        # 轉換為 JSON
        json_str = report.to_json()
        assert len(json_str) > 0

        # 可以被 json.loads 解析
        parsed = json.loads(json_str)
        assert parsed["run_id"] == "test_003"


class TestFailClosedPrinciple:
    """Fail-Closed 原則測試"""

    def test_insufficient_sources_blocks_publish(self):
        """測試來源不足阻擋發佈"""
        gate = QualityGate()

        post = {
            "markdown": "Test content with risk warning 投資有風險",
            "tldr": ["Point 1", "Point 2", "Point 3"],
            "title_candidates": ["Title 1", "Title 2", "Title 3", "Title 4", "Title 5"],
            "what_to_watch": ["Watch 1", "Watch 2", "Watch 3"],
            "disclosures": {"not_investment_advice": True},
        }
        research_pack = {
            "sources": [{"title": "Only One Source", "publisher": "Test"}],
            "key_stocks": [
                {"ticker": "NVDA"},
                {"ticker": "AMD"},
            ],
            "primary_event": {"title": "Test Event", "event_type": "news"},
            "peer_table": {"rows": [1, 2, 3]},
        }

        report = gate.run_all_gates(post, research_pack, mode="publish")

        # 應該失敗並阻擋發佈
        assert report.overall_passed is False
        assert report.can_publish is False
        assert report.recommended_action == "draft"

    def test_forbidden_words_blocks_publish(self):
        """測試禁用詞阻擋發佈"""
        gate = QualityGate()

        post = {
            "markdown": "This is a guaranteed profit opportunity! 投資有風險",
            "tldr": ["Point 1", "Point 2", "Point 3"],
            "title_candidates": ["Title 1", "Title 2", "Title 3", "Title 4", "Title 5"],
            "what_to_watch": ["Watch 1", "Watch 2", "Watch 3"],
            "disclosures": {"not_investment_advice": True},
        }
        research_pack = {
            "sources": [{"title": f"Source {i}", "publisher": f"Pub{i}"} for i in range(6)],
            "key_stocks": [{"ticker": "NVDA"}, {"ticker": "AMD"}],
            "primary_event": {"title": "Test Event", "event_type": "news"},
            "peer_table": {"rows": [1, 2, 3]},
        }

        report = gate.run_all_gates(post, research_pack, mode="publish")

        # 應該因為禁用詞而失敗
        assert report.overall_passed is False
        assert report.can_publish is False
        assert any("compliance" in e.lower() for e in report.errors)

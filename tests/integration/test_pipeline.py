"""Pipeline Integration Tests

端到端測試完整 pipeline。
"""

import json
from pathlib import Path

import pytest

from src.quality.quality_gate import QualityGate
from src.quality.run_report import RunReportBuilder
from src.replay.fixture_manager import FixtureManager


# Fixtures 路徑
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def research_pack():
    """載入 research pack fixture"""
    with open(FIXTURES_DIR / "research_packs" / "sample_research_pack.json") as f:
        return json.load(f)


@pytest.fixture
def post():
    """載入 post fixture"""
    with open(FIXTURES_DIR / "posts" / "sample_post.json") as f:
        return json.load(f)


class TestPipelineIntegration:
    """Pipeline 整合測試"""

    def test_quality_gate_with_run_report(self, post, research_pack):
        """測試品質 Gate 與 Run Report 整合"""
        run_id = "integration_test_001"

        # 建立 Run Report Builder
        builder = RunReportBuilder(run_id=run_id, edition="postclose")

        # 設定候選事件
        builder.set_candidate_events(
            events=[research_pack["primary_event"]],
            scored_events=[],
        )

        # 設定選題結果
        builder.set_selection(
            event=research_pack["primary_event"],
            reason="Highest relevance score",
            theme=research_pack.get("theme"),
            tickers=[s["ticker"] for s in research_pack["key_stocks"]],
        )

        # 執行品質 Gate
        gate = QualityGate()
        quality_report = gate.run_all_gates(
            post,
            research_pack,
            mode="draft",
            run_id=run_id,
        )

        # 設定品質結果
        builder.set_quality_result(quality_report.to_dict())

        # 設定內容統計
        builder.set_content_stats(post, research_pack)

        # 完成報告
        report = builder.complete("completed")

        # 驗證報告
        assert report.run_id == run_id
        assert report.edition == "postclose"
        assert report.status == "completed"
        assert report.duration_seconds > 0
        assert len(report.quality_gates) > 0

    def test_fixture_manager(self, tmp_path, post, research_pack):
        """測試 Fixture Manager"""
        manager = FixtureManager(base_dir=str(tmp_path))

        # 儲存 fixtures
        manager.save_fixture("research_packs", "test_pack", research_pack)
        manager.save_fixture("posts", "test_post", post)

        # 載入 fixtures
        loaded_pack = manager.load_fixture("research_packs", "test_pack")
        loaded_post = manager.load_fixture("posts", "test_post")

        assert loaded_pack is not None
        assert loaded_post is not None
        assert loaded_pack["meta"]["run_id"] == research_pack["meta"]["run_id"]

    def test_daily_snapshot(self, tmp_path, post, research_pack):
        """測試每日快照"""
        manager = FixtureManager(base_dir=str(tmp_path))

        # 建立快照
        snapshot_dir = manager.create_daily_snapshot(
            "2024-01-01",
            research_pack,
            post,
        )

        assert snapshot_dir.exists()

        # 載入快照
        snapshot = manager.load_daily_snapshot("2024-01-01")

        assert snapshot is not None
        assert "research_pack" in snapshot
        assert "post" in snapshot
        assert snapshot["date"] == "2024-01-01"

    def test_latest_snapshot(self, tmp_path, post, research_pack):
        """測試取得最新快照"""
        manager = FixtureManager(base_dir=str(tmp_path))

        # 建立多個快照
        manager.create_daily_snapshot("2024-01-01", research_pack, post)
        manager.create_daily_snapshot("2024-01-02", research_pack, post)
        manager.create_daily_snapshot("2024-01-03", research_pack, post)

        # 取得最新
        latest = manager.get_latest_snapshot()

        assert latest is not None
        assert latest["date"] == "2024-01-03"

    def test_list_fixtures(self, tmp_path, post, research_pack):
        """測試列出 fixtures"""
        manager = FixtureManager(base_dir=str(tmp_path))

        # 儲存一些 fixtures
        manager.save_fixture("research_packs", "pack1", research_pack)
        manager.save_fixture("research_packs", "pack2", research_pack)
        manager.save_fixture("posts", "post1", post)

        # 列出所有
        all_fixtures = manager.list_fixtures()
        assert len(all_fixtures) == 3

        # 列出特定類別
        packs = manager.list_fixtures("research_packs")
        assert len(packs) == 2

        posts = manager.list_fixtures("posts")
        assert len(posts) == 1


class TestEndToEndFlow:
    """端到端流程測試"""

    def test_draft_mode_flow(self, post, research_pack):
        """測試 draft 模式流程"""
        # 模擬完整的 draft 流程
        gate = QualityGate()

        # 執行品質檢查
        report = gate.run_all_gates(
            post,
            research_pack,
            mode="draft",
            run_id="e2e_draft_001",
        )

        # Draft 模式下即使通過也不會自動發佈
        assert report.recommended_action == "draft"
        # 應該可以發佈 (作為 draft)
        if report.overall_passed:
            assert report.can_publish is True

    def test_publish_mode_flow_without_newsletter(self, post, research_pack):
        """測試發佈模式流程 (不含 newsletter)"""
        gate = QualityGate()

        report = gate.run_all_gates(
            post,
            research_pack,
            mode="publish",
            newsletter_slug="",
            email_segment="",
            run_id="e2e_publish_001",
        )

        # 檢查發佈相關的 gate
        gate_names = [g.name for g in report.gates]
        assert "publishing" in gate_names

        # 如果品質通過，應該可以發佈
        if report.overall_passed:
            assert report.can_publish is True
            assert report.recommended_action == "publish"

    def test_run_report_json_output(self, post, research_pack, tmp_path):
        """測試 Run Report JSON 輸出"""
        builder = RunReportBuilder(run_id="e2e_json_001", edition="postclose")

        # 執行品質檢查
        gate = QualityGate()
        quality_report = gate.run_all_gates(
            post,
            research_pack,
            mode="draft",
            run_id="e2e_json_001",
        )

        builder.set_quality_result(quality_report.to_dict())
        builder.set_content_stats(post, research_pack)

        report = builder.complete("completed")

        # 儲存報告
        output_path = str(tmp_path / "run_report.json")
        saved_path = builder.save(output_path)

        # 驗證輸出
        assert saved_path.exists()

        with open(saved_path) as f:
            saved_report = json.load(f)

        assert saved_report["run_id"] == "e2e_json_001"
        assert saved_report["status"] == "completed"
        assert "quality" in saved_report
        assert "content_stats" in saved_report


class TestRegressionScenarios:
    """回歸測試場景"""

    def test_empty_sources_should_fail(self):
        """測試空來源應該失敗"""
        gate = QualityGate()

        post = {
            "markdown": "Test content 投資有風險",
            "tldr": ["1", "2", "3"],
            "title_candidates": ["1", "2", "3", "4", "5"],
            "what_to_watch": ["1", "2", "3"],
            "disclosures": {"not_investment_advice": True},
        }
        research_pack = {
            "sources": [],
            "key_stocks": [{"ticker": "TEST"}, {"ticker": "TEST2"}],
            "primary_event": {"title": "Test"},
            "peer_table": {"rows": [1, 2, 3]},
        }

        report = gate.run_all_gates(post, research_pack)

        assert report.overall_passed is False
        assert report.can_publish is False

    def test_rumor_as_primary_should_warn(self):
        """測試 rumor 作為主要事件應該警告或失敗"""
        gate = QualityGate()

        post = {
            "markdown": "Test content 投資有風險",
            "tldr": ["1", "2", "3"],
            "title_candidates": ["1", "2", "3", "4", "5"],
            "what_to_watch": ["1", "2", "3"],
            "disclosures": {"not_investment_advice": True},
        }
        research_pack = {
            "sources": [{"title": f"S{i}", "publisher": f"P{i}"} for i in range(6)],
            "key_stocks": [{"ticker": "TEST"}, {"ticker": "TEST2"}],
            "primary_event": {"title": "Rumor: Possible Acquisition", "event_type": "rumor"},
            "peer_table": {"rows": [1, 2, 3]},
        }

        report = gate.run_all_gates(post, research_pack)

        # 根據設定，rumor 可能失敗或產生警告
        sources_gate = next((g for g in report.gates if g.name == "sources"), None)
        assert sources_gate is not None
        # 如果 rumor 不被允許，應該失敗
        if "rumor" in sources_gate.message.lower():
            assert sources_gate.passed is False

    def test_missing_disclosure_should_fail(self):
        """測試缺少免責聲明應該失敗"""
        gate = QualityGate()

        post = {
            "markdown": "Test content without any risk warning",  # 沒有風險警告
            "tldr": ["1", "2", "3"],
            "title_candidates": ["1", "2", "3", "4", "5"],
            "what_to_watch": ["1", "2", "3"],
            "disclosures": {},  # 缺少 not_investment_advice
        }
        research_pack = {
            "sources": [{"title": f"S{i}", "publisher": f"P{i}"} for i in range(6)],
            "key_stocks": [{"ticker": "TEST"}, {"ticker": "TEST2"}],
            "primary_event": {"title": "Test"},
            "peer_table": {"rows": [1, 2, 3]},
        }

        report = gate.run_all_gates(post, research_pack)

        # 應該因為缺少免責聲明而失敗
        compliance_gate = next((g for g in report.gates if g.name == "compliance"), None)
        assert compliance_gate is not None
        assert compliance_gate.passed is False

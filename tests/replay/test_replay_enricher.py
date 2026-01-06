"""Enricher Replay Tests

使用 fixtures 測試 enricher，不呼叫外部 API。
"""

import json
from pathlib import Path

import pytest

from src.replay.recorder import ReplayMode, ReplayRecorder, init_recorder, get_recorder, set_recorder


# Fixtures 路徑
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
API_RESPONSES_DIR = FIXTURES_DIR / "api_responses"


@pytest.fixture
def replay_recorder():
    """建立 replay 模式的 recorder"""
    recorder = ReplayRecorder(
        mode=ReplayMode.REPLAY,
        fixture_dir=str(API_RESPONSES_DIR),
    )
    set_recorder(recorder)
    yield recorder
    set_recorder(None)


@pytest.fixture
def record_recorder(tmp_path):
    """建立 record 模式的 recorder"""
    recorder = ReplayRecorder(
        mode=ReplayMode.RECORD,
        fixture_dir=str(tmp_path),
        run_id="test_record",
    )
    set_recorder(recorder)
    yield recorder
    set_recorder(None)


class TestReplayRecorder:
    """Replay Recorder 測試"""

    def test_init_replay_mode(self, replay_recorder):
        """測試 replay 模式初始化"""
        assert replay_recorder.mode == ReplayMode.REPLAY
        # 應該載入了一些 fixtures
        assert len(replay_recorder._cache) > 0

    def test_generate_key(self, replay_recorder):
        """測試 key 生成"""
        key1 = replay_recorder._generate_key("fmp", "quote/NVDA", {})
        key2 = replay_recorder._generate_key("fmp", "quote/NVDA", {})
        key3 = replay_recorder._generate_key("fmp", "quote/AMD", {})

        # 相同參數應該生成相同 key
        assert key1 == key2
        # 不同參數應該生成不同 key
        assert key1 != key3

    def test_get_or_call_replay_hit(self, replay_recorder):
        """測試 replay 命中"""
        call_count = 0

        def mock_call():
            nonlocal call_count
            call_count += 1
            return {"data": "from_api"}, 200, 100

        # 如果有對應的 fixture，應該不會呼叫 mock_call
        # 這裡我們手動加入一個快取項目來測試
        replay_recorder._cache["test_key_123"] = type("MockResponse", (), {
            "response": {"cached": True},
            "status_code": 200,
        })()

        # 模擬對應的 key
        original_generate_key = replay_recorder._generate_key
        replay_recorder._generate_key = lambda p, e, params: "test_key_123"

        try:
            response, status = replay_recorder.get_or_call(
                "test_provider",
                "test_endpoint",
                {},
                mock_call,
            )

            # 應該返回快取的回應
            assert response == {"cached": True}
            assert status == 200
            # 不應該呼叫實際的 API
            assert call_count == 0
            # 統計應該更新
            assert replay_recorder.stats["cache_hits"] >= 1

        finally:
            replay_recorder._generate_key = original_generate_key

    def test_get_or_call_replay_miss(self, replay_recorder):
        """測試 replay 未命中"""
        call_count = 0

        def mock_call():
            nonlocal call_count
            call_count += 1
            return {"data": "from_api"}, 200, 100

        # 使用不存在於 fixtures 的 endpoint
        response, status = replay_recorder.get_or_call(
            "nonexistent_provider",
            "nonexistent_endpoint",
            {"nonexistent": "param"},
            mock_call,
        )

        # Replay 模式下 cache miss 應該返回 None
        assert response is None
        assert status == 404
        # 不應該呼叫實際的 API (replay 模式)
        assert call_count == 0
        # cache miss 統計應該更新
        assert replay_recorder.stats["cache_misses"] >= 1

    def test_record_mode(self, record_recorder):
        """測試 record 模式"""
        call_count = 0

        def mock_call():
            nonlocal call_count
            call_count += 1
            return {"data": "recorded"}, 200, 150.5

        response, status = record_recorder.get_or_call(
            "test_provider",
            "test_endpoint",
            {"ticker": "TEST"},
            mock_call,
        )

        # 應該呼叫實際的 API
        assert call_count == 1
        assert response == {"data": "recorded"}
        # 應該有記錄
        assert len(record_recorder._recorded) == 1
        assert record_recorder.stats["recorded"] == 1

    def test_save_recordings(self, record_recorder, tmp_path):
        """測試儲存記錄"""
        def mock_call():
            return {"data": "test"}, 200, 100

        # 記錄一些回應
        record_recorder.get_or_call("p1", "e1", {}, mock_call)
        record_recorder.get_or_call("p2", "e2", {}, mock_call)

        # 儲存
        output_path = record_recorder.save_recordings()

        # 應該建立檔案
        assert output_path.exists()

        # 檔案內容應該正確
        with open(output_path) as f:
            saved = json.load(f)
        assert len(saved) == 2

    def test_stats(self, replay_recorder):
        """測試統計"""
        stats = replay_recorder.get_stats()

        assert "cache_hits" in stats
        assert "cache_misses" in stats
        assert "mode" in stats
        assert stats["mode"] == "replay"


class TestInitRecorder:
    """init_recorder 函數測試"""

    def test_init_live_mode(self):
        """測試初始化 live 模式"""
        try:
            recorder = init_recorder(mode="live")
            assert recorder.mode == ReplayMode.LIVE
            assert get_recorder() == recorder
        finally:
            set_recorder(None)

    def test_init_replay_mode(self):
        """測試初始化 replay 模式"""
        try:
            recorder = init_recorder(
                mode="replay",
                fixture_dir=str(API_RESPONSES_DIR),
            )
            assert recorder.mode == ReplayMode.REPLAY
            assert get_recorder() == recorder
        finally:
            set_recorder(None)

    def test_init_record_mode(self, tmp_path):
        """測試初始化 record 模式"""
        try:
            recorder = init_recorder(
                mode="record",
                fixture_dir=str(tmp_path),
                run_id="test_init",
            )
            assert recorder.mode == ReplayMode.RECORD
            assert recorder.run_id == "test_init"
            assert get_recorder() == recorder
        finally:
            set_recorder(None)

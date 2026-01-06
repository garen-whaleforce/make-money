"""Replay Recorder

記錄與重播外部 API 回應。
"""

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from ..utils.logging import get_logger

logger = get_logger(__name__)


class ReplayMode(Enum):
    """重播模式"""
    LIVE = "live"           # 正常執行，呼叫外部 API
    RECORD = "record"       # 執行並記錄回應
    REPLAY = "replay"       # 從 fixtures 讀取，不呼叫外部 API


@dataclass
class RecordedResponse:
    """記錄的回應"""

    request_key: str
    provider: str
    endpoint: str
    params: dict
    response: Any
    status_code: int
    recorded_at: str
    response_time_ms: float

    def to_dict(self) -> dict:
        return {
            "request_key": self.request_key,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "params": self.params,
            "response": self.response,
            "status_code": self.status_code,
            "recorded_at": self.recorded_at,
            "response_time_ms": self.response_time_ms,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RecordedResponse":
        return cls(
            request_key=data["request_key"],
            provider=data["provider"],
            endpoint=data["endpoint"],
            params=data["params"],
            response=data["response"],
            status_code=data["status_code"],
            recorded_at=data["recorded_at"],
            response_time_ms=data.get("response_time_ms", 0),
        )


class ReplayRecorder:
    """重播記錄器"""

    def __init__(
        self,
        mode: ReplayMode = ReplayMode.LIVE,
        fixture_dir: Optional[str] = None,
        run_id: Optional[str] = None,
    ):
        """初始化重播記錄器

        Args:
            mode: 重播模式
            fixture_dir: Fixture 目錄
            run_id: 執行 ID (用於記錄模式)
        """
        self.mode = mode
        self.run_id = run_id or datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        # 設定 fixture 目錄
        if fixture_dir:
            self.fixture_dir = Path(fixture_dir)
        else:
            self.fixture_dir = Path("tests/fixtures/api_responses")

        # 快取已載入的 fixtures
        self._cache: dict[str, RecordedResponse] = {}

        # 記錄模式的緩衝區
        self._recorded: list[RecordedResponse] = []

        # 統計
        self.stats = {
            "cache_hits": 0,
            "cache_misses": 0,
            "recorded": 0,
            "replayed": 0,
        }

        if self.mode == ReplayMode.REPLAY:
            self._load_fixtures()

    def _generate_key(self, provider: str, endpoint: str, params: dict) -> str:
        """生成請求的唯一 key

        Args:
            provider: 提供者名稱 (fmp, alpha_vantage, etc.)
            endpoint: API endpoint
            params: 請求參數

        Returns:
            唯一識別的 key
        """
        # 排序參數以確保一致性
        sorted_params = json.dumps(params, sort_keys=True)
        raw = f"{provider}:{endpoint}:{sorted_params}"
        return hashlib.md5(raw.encode()).hexdigest()[:16]

    def _load_fixtures(self) -> None:
        """載入所有 fixtures"""
        if not self.fixture_dir.exists():
            logger.warning(f"Fixture directory not found: {self.fixture_dir}")
            return

        # 載入所有 JSON 檔案
        for json_file in self.fixture_dir.glob("**/*.json"):
            try:
                with open(json_file) as f:
                    data = json.load(f)

                # 支援單一回應或回應列表
                if isinstance(data, list):
                    for item in data:
                        response = RecordedResponse.from_dict(item)
                        self._cache[response.request_key] = response
                else:
                    response = RecordedResponse.from_dict(data)
                    self._cache[response.request_key] = response

            except Exception as e:
                logger.warning(f"Failed to load fixture {json_file}: {e}")

        logger.info(f"Loaded {len(self._cache)} fixtures from {self.fixture_dir}")

    def get_or_call(
        self,
        provider: str,
        endpoint: str,
        params: dict,
        call_fn: Callable[[], tuple[Any, int, float]],
    ) -> tuple[Any, int]:
        """取得回應 (從快取或呼叫 API)

        Args:
            provider: 提供者名稱
            endpoint: API endpoint
            params: 請求參數
            call_fn: 實際呼叫 API 的函數，回傳 (response, status_code, response_time_ms)

        Returns:
            (response, status_code)
        """
        key = self._generate_key(provider, endpoint, params)

        if self.mode == ReplayMode.REPLAY:
            # 從快取讀取
            if key in self._cache:
                self.stats["cache_hits"] += 1
                self.stats["replayed"] += 1
                cached = self._cache[key]
                logger.debug(f"Replay hit: {provider}/{endpoint} -> {key}")
                return cached.response, cached.status_code
            else:
                self.stats["cache_misses"] += 1
                logger.warning(f"Replay miss: {provider}/{endpoint} -> {key}")
                # 在 replay 模式下，cache miss 應該回傳空回應
                return None, 404

        # LIVE 或 RECORD 模式：呼叫實際 API
        response, status_code, response_time = call_fn()

        if self.mode == ReplayMode.RECORD:
            # 記錄回應
            recorded = RecordedResponse(
                request_key=key,
                provider=provider,
                endpoint=endpoint,
                params=params,
                response=response,
                status_code=status_code,
                recorded_at=datetime.utcnow().isoformat(),
                response_time_ms=response_time,
            )
            self._recorded.append(recorded)
            self.stats["recorded"] += 1
            logger.debug(f"Recorded: {provider}/{endpoint} -> {key}")

        return response, status_code

    def save_recordings(self, output_path: Optional[str] = None) -> Path:
        """儲存所有記錄

        Args:
            output_path: 輸出路徑

        Returns:
            輸出檔案路徑
        """
        if not self._recorded:
            logger.info("No recordings to save")
            return Path("")

        if output_path:
            path = Path(output_path)
        else:
            path = self.fixture_dir / f"recorded_{self.run_id}.json"

        path.parent.mkdir(parents=True, exist_ok=True)

        data = [r.to_dict() for r in self._recorded]

        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved {len(self._recorded)} recordings to {path}")
        return path

    def get_stats(self) -> dict:
        """取得統計資訊"""
        return {
            **self.stats,
            "mode": self.mode.value,
            "fixture_count": len(self._cache),
        }


# 全域 recorder 實例 (用於單例模式)
_global_recorder: Optional[ReplayRecorder] = None


def get_recorder() -> Optional[ReplayRecorder]:
    """取得全域 recorder"""
    return _global_recorder


def set_recorder(recorder: ReplayRecorder) -> None:
    """設定全域 recorder"""
    global _global_recorder
    _global_recorder = recorder


def init_recorder(
    mode: str = "live",
    fixture_dir: Optional[str] = None,
    run_id: Optional[str] = None,
) -> ReplayRecorder:
    """初始化並設定全域 recorder

    Args:
        mode: 模式 (live/record/replay)
        fixture_dir: Fixture 目錄
        run_id: 執行 ID

    Returns:
        ReplayRecorder 實例
    """
    replay_mode = ReplayMode(mode)
    recorder = ReplayRecorder(
        mode=replay_mode,
        fixture_dir=fixture_dir,
        run_id=run_id,
    )
    set_recorder(recorder)
    return recorder

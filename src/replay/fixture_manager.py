"""Fixture Manager

管理測試 fixtures 的建立與維護。
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..utils.logging import get_logger

logger = get_logger(__name__)


class FixtureManager:
    """Fixture 管理器"""

    def __init__(self, base_dir: str = "tests/fixtures"):
        """初始化 Fixture 管理器

        Args:
            base_dir: Fixtures 基礎目錄
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_fixture_path(self, category: str, name: str) -> Path:
        """取得 fixture 路徑

        Args:
            category: 類別 (api_responses, research_packs, posts)
            name: Fixture 名稱

        Returns:
            Fixture 檔案路徑
        """
        return self.base_dir / category / f"{name}.json"

    def load_fixture(self, category: str, name: str) -> Optional[dict]:
        """載入 fixture

        Args:
            category: 類別
            name: Fixture 名稱

        Returns:
            Fixture 資料或 None
        """
        path = self.get_fixture_path(category, name)
        if not path.exists():
            logger.warning(f"Fixture not found: {path}")
            return None

        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load fixture {path}: {e}")
            return None

    def save_fixture(
        self,
        category: str,
        name: str,
        data: dict,
        overwrite: bool = False,
    ) -> Path:
        """儲存 fixture

        Args:
            category: 類別
            name: Fixture 名稱
            data: 資料
            overwrite: 是否覆蓋現有檔案

        Returns:
            Fixture 檔案路徑
        """
        path = self.get_fixture_path(category, name)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists() and not overwrite:
            # 備份現有檔案
            backup_path = path.with_suffix(f".{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak")
            shutil.copy(path, backup_path)
            logger.info(f"Backed up existing fixture to {backup_path}")

        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved fixture to {path}")
        return path

    def list_fixtures(self, category: Optional[str] = None) -> list[dict]:
        """列出所有 fixtures

        Args:
            category: 類別 (可選，None 表示所有)

        Returns:
            Fixture 資訊列表
        """
        fixtures = []

        if category:
            search_dirs = [self.base_dir / category]
        else:
            search_dirs = [d for d in self.base_dir.iterdir() if d.is_dir()]

        for dir_path in search_dirs:
            if not dir_path.exists():
                continue

            for json_file in dir_path.glob("**/*.json"):
                # 跳過備份檔案
                if ".bak" in json_file.suffixes:
                    continue

                rel_path = json_file.relative_to(self.base_dir)
                fixtures.append({
                    "category": dir_path.name,
                    "name": json_file.stem,
                    "path": str(rel_path),
                    "size_bytes": json_file.stat().st_size,
                    "modified_at": datetime.fromtimestamp(
                        json_file.stat().st_mtime
                    ).isoformat(),
                })

        return fixtures

    def create_daily_snapshot(
        self,
        date: str,
        research_pack: dict,
        post: dict,
        api_responses: Optional[dict] = None,
    ) -> Path:
        """建立每日快照

        Args:
            date: 日期 (YYYY-MM-DD)
            research_pack: Research pack 資料
            post: Post 資料
            api_responses: API 回應 (可選)

        Returns:
            快照目錄路徑
        """
        snapshot_dir = self.base_dir / "daily_snapshots" / date
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        # 儲存 research pack
        with open(snapshot_dir / "research_pack.json", "w") as f:
            json.dump(research_pack, f, indent=2, ensure_ascii=False)

        # 儲存 post
        with open(snapshot_dir / "post.json", "w") as f:
            json.dump(post, f, indent=2, ensure_ascii=False)

        # 儲存 API 回應
        if api_responses:
            with open(snapshot_dir / "api_responses.json", "w") as f:
                json.dump(api_responses, f, indent=2, ensure_ascii=False)

        logger.info(f"Created daily snapshot at {snapshot_dir}")
        return snapshot_dir

    def load_daily_snapshot(self, date: str) -> Optional[dict]:
        """載入每日快照

        Args:
            date: 日期 (YYYY-MM-DD)

        Returns:
            快照資料或 None
        """
        snapshot_dir = self.base_dir / "daily_snapshots" / date
        if not snapshot_dir.exists():
            return None

        snapshot = {"date": date}

        for filename in ["research_pack.json", "post.json", "api_responses.json"]:
            filepath = snapshot_dir / filename
            if filepath.exists():
                with open(filepath) as f:
                    key = filename.replace(".json", "")
                    snapshot[key] = json.load(f)

        return snapshot

    def get_latest_snapshot(self) -> Optional[dict]:
        """取得最新的每日快照

        Returns:
            快照資料或 None
        """
        snapshots_dir = self.base_dir / "daily_snapshots"
        if not snapshots_dir.exists():
            return None

        # 找最新的日期目錄
        dates = sorted([
            d.name for d in snapshots_dir.iterdir()
            if d.is_dir() and len(d.name) == 10
        ], reverse=True)

        if not dates:
            return None

        return self.load_daily_snapshot(dates[0])

    def cleanup_old_fixtures(self, keep_days: int = 30) -> int:
        """清理舊的 fixtures

        Args:
            keep_days: 保留天數

        Returns:
            刪除的檔案數量
        """
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(days=keep_days)
        deleted = 0

        for json_file in self.base_dir.glob("**/*.json"):
            # 只清理備份檔案和舊的每日快照
            if ".bak" in str(json_file):
                mtime = datetime.fromtimestamp(json_file.stat().st_mtime)
                if mtime < cutoff:
                    json_file.unlink()
                    deleted += 1
                    logger.debug(f"Deleted old backup: {json_file}")

        # 清理舊的每日快照
        snapshots_dir = self.base_dir / "daily_snapshots"
        if snapshots_dir.exists():
            for date_dir in snapshots_dir.iterdir():
                if not date_dir.is_dir():
                    continue
                try:
                    snapshot_date = datetime.strptime(date_dir.name, "%Y-%m-%d")
                    if snapshot_date < cutoff:
                        shutil.rmtree(date_dir)
                        deleted += 1
                        logger.info(f"Deleted old snapshot: {date_dir}")
                except ValueError:
                    pass

        logger.info(f"Cleaned up {deleted} old fixtures")
        return deleted


def create_sample_fixtures() -> None:
    """建立範例 fixtures"""
    manager = FixtureManager()

    # 建立範例 research pack
    sample_research_pack = {
        "meta": {
            "run_id": "sample_20240101",
            "edition": "postclose",
            "generated_at": "2024-01-01T12:00:00Z",
        },
        "primary_event": {
            "id": "sample_event_1",
            "title": "NVIDIA Announces New AI Chip",
            "event_type": "product_launch",
            "tickers": ["NVDA"],
        },
        "sources": [
            {"title": "Source 1", "publisher": "Reuters", "url": "https://example.com/1"},
            {"title": "Source 2", "publisher": "Bloomberg", "url": "https://example.com/2"},
            {"title": "Source 3", "publisher": "CNBC", "url": "https://example.com/3"},
            {"title": "Source 4", "publisher": "WSJ", "url": "https://example.com/4"},
            {"title": "Source 5", "publisher": "FT", "url": "https://example.com/5"},
        ],
        "key_stocks": [
            {"ticker": "NVDA", "name": "NVIDIA Corporation", "role": "primary"},
            {"ticker": "AMD", "name": "Advanced Micro Devices", "role": "peer"},
            {"ticker": "INTC", "name": "Intel Corporation", "role": "peer"},
        ],
        "peer_table": {
            "columns": ["ticker", "name", "market_cap", "pe_ratio"],
            "rows": [
                {"ticker": "NVDA", "name": "NVIDIA", "market_cap": "1.2T", "pe_ratio": 60.5},
                {"ticker": "AMD", "name": "AMD", "market_cap": "200B", "pe_ratio": 45.2},
                {"ticker": "INTC", "name": "Intel", "market_cap": "150B", "pe_ratio": 15.8},
            ],
        },
        "valuations": {
            "NVDA": {
                "fair_value": {"bear": 400, "base": 500, "bull": 650},
                "current_price": 480,
                "upside": {"bear": -16.7, "base": 4.2, "bull": 35.4},
                "method": "peer_multiple",
                "rationale": "Based on forward P/E multiple relative to peers",
            },
        },
    }

    # 建立範例 post
    sample_post = {
        "meta": {
            "run_id": "sample_20240101",
            "generated_at": "2024-01-01T12:00:00Z",
        },
        "title": "NVIDIA's New AI Chip: What It Means for the Industry",
        "title_candidates": [
            "NVIDIA's New AI Chip: What It Means for the Industry",
            "Breaking: NVIDIA Unveils Next-Gen AI Hardware",
            "The AI Chip War Heats Up: NVIDIA's Latest Move",
            "NVIDIA's Bold Bet on AI: A Deep Dive",
            "What NVIDIA's New Chip Means for Your Portfolio",
        ],
        "slug": "nvidia-new-ai-chip-2024-01-01",
        "excerpt": "NVIDIA announced a new AI chip that could reshape the semiconductor landscape.",
        "tldr": [
            "NVIDIA unveiled its next-generation AI chip with 50% better performance",
            "The new chip targets enterprise AI workloads",
            "AMD and Intel face increased competitive pressure",
        ],
        "what_to_watch": [
            "NVIDIA earnings call for chip demand signals",
            "AMD's competitive response timeline",
            "Enterprise AI adoption rates in Q1 2024",
        ],
        "markdown": "# NVIDIA's New AI Chip\n\nThis is sample markdown content...",
        "html": "<h1>NVIDIA's New AI Chip</h1><p>This is sample HTML content...</p>",
        "tags": ["AI", "Semiconductors", "NVIDIA"],
        "tickers_mentioned": ["NVDA", "AMD", "INTC"],
        "disclosures": {
            "not_investment_advice": True,
            "risk_warning": "投資有風險，請審慎評估。",
        },
    }

    # 儲存 fixtures
    manager.save_fixture("research_packs", "sample_research_pack", sample_research_pack)
    manager.save_fixture("posts", "sample_post", sample_post)

    # 建立每日快照範例
    manager.create_daily_snapshot(
        "2024-01-01",
        sample_research_pack,
        sample_post,
    )

    logger.info("Created sample fixtures")


if __name__ == "__main__":
    create_sample_fixtures()

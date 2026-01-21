"""
Output Manager - 統一管理 Pipeline 輸出路徑和 Manifest

P0-1: 每次 run 輸出到獨立目錄
- out/{run_id}/edition_pack.json
- out/{run_id}/{post_type}/post.json
- out/{run_id}/{post_type}/post.html
- out/{run_id}/{post_type}/artifacts/
- out/{run_id}/manifest.json
- out/{run_id}/checkpoint.json

確保：
1. 不同 run 的輸出不會混淆
2. Publish 只讀取 manifest 指定的文件
3. 每次 run 有完整的 audit trail
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict

from ..utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PostManifestEntry:
    """Manifest entry for a single post"""
    post_type: str
    json_path: str
    html_path: str
    feature_image_path: Optional[str] = None
    title: str = ""
    slug: str = ""
    generated_at: str = ""
    quality_passed: bool = False


@dataclass
class RunManifest:
    """Manifest for a complete pipeline run"""
    run_id: str
    date: str
    created_at: str
    completed_at: Optional[str] = None

    # Paths
    edition_pack_path: str = ""
    checkpoint_path: str = ""

    # Posts
    posts: Dict[str, PostManifestEntry] = field(default_factory=dict)

    # Status
    stage: str = "init"  # init, ingest, pack, write, qa, publish, archive, complete
    qa_passed: bool = False
    errors: List[str] = field(default_factory=list)

    # Metrics
    duration_seconds: float = 0.0

    def to_dict(self) -> Dict:
        d = asdict(self)
        # Convert PostManifestEntry to dict
        d["posts"] = {k: asdict(v) for k, v in self.posts.items()}
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> "RunManifest":
        posts = {}
        for k, v in d.get("posts", {}).items():
            posts[k] = PostManifestEntry(**v)
        d["posts"] = posts
        return cls(**d)


class OutputManager:
    """
    統一管理 Pipeline 輸出

    目錄結構：
    out/
    ├── {run_id}/
    │   ├── manifest.json       # 本次 run 的完整資訊
    │   ├── checkpoint.json     # 斷點續跑狀態
    │   ├── edition_pack.json   # 資料源
    │   ├── fact_pack.json      # 事實包
    │   ├── quality_report.json # 品質報告
    │   ├── flash/
    │   │   ├── post.json
    │   │   ├── post.html
    │   │   └── artifacts/      # feature images, etc.
    │   ├── earnings/
    │   │   └── ...
    │   └── deep/
    │       └── ...
    └── latest -> {run_id}/     # Symlink to latest run
    """

    def __init__(self, run_id: str, run_date: str, base_dir: str = "out"):
        self.run_id = run_id
        self.run_date = run_date
        self.base_dir = Path(base_dir)
        self.run_dir = self.base_dir / run_id

        # Create directories
        self._ensure_dirs()

        # Initialize manifest
        self.manifest = RunManifest(
            run_id=run_id,
            date=run_date,
            created_at=datetime.now().isoformat(),
            edition_pack_path=str(self.edition_pack_path),
            checkpoint_path=str(self.checkpoint_path),
        )

    def _ensure_dirs(self) -> None:
        """Create all necessary directories"""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        for post_type in ["morning", "flash", "earnings", "deep"]:
            post_dir = self.run_dir / post_type
            post_dir.mkdir(parents=True, exist_ok=True)
            (post_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # Path Properties
    # =========================================================================

    @property
    def edition_pack_path(self) -> Path:
        return self.run_dir / "edition_pack.json"

    @property
    def fact_pack_path(self) -> Path:
        return self.run_dir / "fact_pack.json"

    @property
    def research_pack_path(self) -> Path:
        return self.run_dir / "research_pack.json"

    @property
    def checkpoint_path(self) -> Path:
        return self.run_dir / "checkpoint.json"

    @property
    def manifest_path(self) -> Path:
        return self.run_dir / "manifest.json"

    @property
    def quality_report_path(self) -> Path:
        return self.run_dir / "quality_report.json"

    def post_dir(self, post_type: str) -> Path:
        return self.run_dir / post_type

    def post_json_path(self, post_type: str) -> Path:
        return self.post_dir(post_type) / "post.json"

    def post_html_path(self, post_type: str) -> Path:
        return self.post_dir(post_type) / "post.html"

    def post_artifacts_dir(self, post_type: str) -> Path:
        return self.post_dir(post_type) / "artifacts"

    def feature_image_path(self, post_type: str, filename: str) -> Path:
        return self.post_artifacts_dir(post_type) / filename

    # =========================================================================
    # Save Operations
    # =========================================================================

    def save_edition_pack(self, edition_pack: Dict) -> Path:
        """Save edition_pack.json"""
        with open(self.edition_pack_path, "w", encoding="utf-8") as f:
            json.dump(edition_pack, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved edition_pack to {self.edition_pack_path}")
        return self.edition_pack_path

    def save_fact_pack(self, fact_pack: Dict) -> Path:
        """Save fact_pack.json"""
        with open(self.fact_pack_path, "w", encoding="utf-8") as f:
            json.dump(fact_pack, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved fact_pack to {self.fact_pack_path}")
        return self.fact_pack_path

    def save_research_pack(self, research_pack: Dict) -> Path:
        """Save research_pack.json"""
        with open(self.research_pack_path, "w", encoding="utf-8") as f:
            json.dump(research_pack, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved research_pack to {self.research_pack_path}")
        return self.research_pack_path

    def save_post(
        self,
        post_type: str,
        post_dict: Dict,
        html_content: str,
        feature_image_src: Optional[str] = None,
    ) -> PostManifestEntry:
        """
        Save post JSON, HTML, and optionally feature image

        Returns manifest entry for this post
        """
        # Save JSON
        json_path = self.post_json_path(post_type)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(post_dict, f, indent=2, ensure_ascii=False)

        # Save HTML
        html_path = self.post_html_path(post_type)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        # Copy feature image if provided
        feature_image_dest = None
        if feature_image_src and Path(feature_image_src).exists():
            filename = Path(feature_image_src).name
            feature_image_dest = self.feature_image_path(post_type, filename)
            shutil.copy2(feature_image_src, feature_image_dest)

        # Create manifest entry
        entry = PostManifestEntry(
            post_type=post_type,
            json_path=str(json_path.relative_to(self.base_dir)),
            html_path=str(html_path.relative_to(self.base_dir)),
            feature_image_path=str(feature_image_dest.relative_to(self.base_dir)) if feature_image_dest else None,
            title=post_dict.get("title", ""),
            slug=post_dict.get("slug", ""),
            generated_at=datetime.now().isoformat(),
        )

        # Update manifest
        self.manifest.posts[post_type] = entry
        self.save_manifest()

        logger.info(f"Saved {post_type} post to {json_path}")
        return entry

    def save_quality_report(self, report: Dict) -> Path:
        """Save quality_report.json"""
        with open(self.quality_report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        # Update manifest with QA status
        self.manifest.qa_passed = report.get("all_gates_passed", False)
        self.save_manifest()

        logger.info(f"Saved quality_report to {self.quality_report_path}")
        return self.quality_report_path

    def save_manifest(self) -> Path:
        """Save manifest.json"""
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(self.manifest.to_dict(), f, indent=2, ensure_ascii=False)
        return self.manifest_path

    # =========================================================================
    # Checkpoint Operations
    # =========================================================================

    def load_checkpoint(self) -> Optional[Dict]:
        """Load checkpoint if exists"""
        if not self.checkpoint_path.exists():
            return None
        try:
            with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {e}")
            return None

    def save_checkpoint(self, checkpoint: Dict) -> Path:
        """Save checkpoint.json"""
        with open(self.checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, indent=2, ensure_ascii=False)
        return self.checkpoint_path

    def update_checkpoint(
        self,
        stage: str,
        completed: bool = True,
        error: Optional[str] = None,
    ) -> None:
        """Update checkpoint with stage status"""
        ckpt = self.load_checkpoint() or {
            "run_id": self.run_id,
            "date": self.run_date,
            "started_at": datetime.now().isoformat(),
            "stages": {},
        }

        ckpt["stages"][stage] = {
            "completed": completed,
            "timestamp": datetime.now().isoformat(),
        }
        if error:
            ckpt["stages"][stage]["error"] = error

        self.save_checkpoint(ckpt)

        # Also update manifest stage
        self.manifest.stage = stage
        if error:
            self.manifest.errors.append(f"{stage}: {error}")
        self.save_manifest()

    def is_stage_completed(self, stage: str) -> bool:
        """Check if a stage is completed"""
        ckpt = self.load_checkpoint()
        if not ckpt:
            return False
        return ckpt.get("stages", {}).get(stage, {}).get("completed", False)

    # =========================================================================
    # Load Operations
    # =========================================================================

    def load_edition_pack(self) -> Optional[Dict]:
        """Load edition_pack.json"""
        if not self.edition_pack_path.exists():
            return None
        with open(self.edition_pack_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_post(self, post_type: str) -> Optional[Dict]:
        """Load a post JSON"""
        json_path = self.post_json_path(post_type)
        if not json_path.exists():
            return None
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_manifest(self) -> Optional[RunManifest]:
        """Load manifest from file"""
        if not self.manifest_path.exists():
            return None
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            return RunManifest.from_dict(json.load(f))

    # =========================================================================
    # Finalization
    # =========================================================================

    def finalize(self, duration_seconds: float = 0.0) -> Path:
        """
        Finalize the run - update manifest and create symlink
        """
        self.manifest.completed_at = datetime.now().isoformat()
        self.manifest.stage = "complete"
        self.manifest.duration_seconds = duration_seconds
        self.save_manifest()

        # Create/update 'latest' symlink
        latest_link = self.base_dir / "latest"
        try:
            if latest_link.is_symlink():
                latest_link.unlink()
            elif latest_link.exists():
                # If it's a directory, remove it
                shutil.rmtree(latest_link)
            latest_link.symlink_to(self.run_id)
            logger.info(f"Updated 'latest' symlink to {self.run_id}")
        except Exception as e:
            logger.warning(f"Failed to create 'latest' symlink: {e}")

        return self.manifest_path

    # =========================================================================
    # Backward Compatibility - 同時輸出到 out/ 根目錄
    # =========================================================================

    def copy_to_legacy_paths(self) -> None:
        """
        Copy outputs to legacy paths for backward compatibility

        This allows existing scripts and the publish stage to work
        while we transition to the new structure.
        """
        legacy_mapping = [
            (self.edition_pack_path, self.base_dir / "edition_pack.json"),
            (self.fact_pack_path, self.base_dir / "fact_pack.json"),
            (self.research_pack_path, self.base_dir / "research_pack.json"),
            (self.quality_report_path, self.base_dir / "quality_report.json"),
        ]

        for src, dst in legacy_mapping:
            if src.exists():
                shutil.copy2(src, dst)

        # Copy post files
        for post_type in ["morning", "flash", "earnings", "deep"]:
            json_src = self.post_json_path(post_type)
            html_src = self.post_html_path(post_type)

            if json_src.exists():
                shutil.copy2(json_src, self.base_dir / f"post_{post_type}.json")
            if html_src.exists():
                shutil.copy2(html_src, self.base_dir / f"post_{post_type}.html")

        logger.info("Copied outputs to legacy paths for backward compatibility")


# =============================================================================
# Factory Functions
# =============================================================================

def get_output_manager(run_id: str, run_date: str) -> OutputManager:
    """Get or create an OutputManager for the given run"""
    return OutputManager(run_id, run_date)


def find_latest_run() -> Optional[OutputManager]:
    """Find the latest run from the 'latest' symlink"""
    latest_link = Path("out/latest")
    if not latest_link.exists():
        return None

    run_id = latest_link.resolve().name
    manifest_path = latest_link / "manifest.json"

    if not manifest_path.exists():
        return None

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = RunManifest.from_dict(json.load(f))

    return OutputManager(manifest.run_id, manifest.date)


def find_run_for_date(run_date: str) -> Optional[OutputManager]:
    """Find runs for a specific date"""
    out_dir = Path("out")

    # Look for directories that match the date pattern
    for d in out_dir.iterdir():
        if not d.is_dir() or d.name in ["latest", "feature_images"]:
            continue

        manifest_path = d / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = RunManifest.from_dict(json.load(f))
            if manifest.date == run_date:
                return OutputManager(manifest.run_id, manifest.date)

    return None

"""MinIO Archiver for Daily Posts

自動將每日生成的文章備份到 MinIO 存儲。

目錄結構:
daily-brief/
├── 2026/
│   ├── 01/
│   │   ├── 08/
│   │   │   ├── edition_pack.json
│   │   │   ├── post_flash.json
│   │   │   ├── post_flash.html
│   │   │   ├── post_earnings.json
│   │   │   ├── post_earnings.html
│   │   │   ├── post_deep.json
│   │   │   ├── post_deep.html
│   │   │   ├── quality_report.json
│   │   │   └── feature_images/
│   │   │       ├── flash_*.png
│   │   │       └── ...
│   │   └── 09/
│   │       └── ...
│   └── 02/
│       └── ...
└── 2027/
    └── ...
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from ..utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ArchiveResult:
    """Archive operation result"""
    success: bool
    files_uploaded: int
    total_bytes: int
    bucket: str
    prefix: str
    error: Optional[str] = None
    uploaded_files: List[str] = None

    def __post_init__(self):
        if self.uploaded_files is None:
            self.uploaded_files = []


class MinIOArchiver:
    """MinIO archiver for daily posts"""

    DEFAULT_BUCKET = "daily-brief"

    def __init__(
        self,
        endpoint: str = None,
        access_key: str = None,
        secret_key: str = None,
        bucket: str = None,
    ):
        """Initialize MinIO archiver

        Args:
            endpoint: MinIO endpoint URL
            access_key: Access key
            secret_key: Secret key
            bucket: Target bucket name
        """
        self.endpoint = endpoint or os.getenv(
            "MINIO_ENDPOINT", "https://minio.api.gpu5090.whaleforce.dev"
        )
        self.access_key = access_key or os.getenv("MINIO_ACCESS_KEY", "whaleforce")
        self.secret_key = secret_key or os.getenv("MINIO_SECRET_KEY", "whaleforce.ai")
        self.bucket = bucket or os.getenv("MINIO_DAILY_BUCKET", self.DEFAULT_BUCKET)

        self._client = None

    def _get_client(self):
        """Get or create S3 client"""
        if self._client is None:
            # Use verify=False for internal endpoints with self-signed certs
            verify_ssl = os.getenv("MINIO_VERIFY_SSL", "true").lower() == "true"

            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                config=Config(signature_version="s3v4"),
                verify=verify_ssl,
            )
        return self._client

    def _ensure_bucket(self) -> bool:
        """Ensure bucket exists, create if not"""
        client = self._get_client()
        try:
            client.head_bucket(Bucket=self.bucket)
            return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code == "404":
                # Bucket doesn't exist, create it
                try:
                    client.create_bucket(Bucket=self.bucket)
                    logger.info(f"Created bucket: {self.bucket}")
                    return True
                except Exception as create_err:
                    logger.error(f"Failed to create bucket: {create_err}")
                    return False
            else:
                logger.error(f"Bucket check failed: {e}")
                return False

    def _get_date_prefix(self, run_date: str) -> str:
        """Convert run_date to directory prefix

        Args:
            run_date: Date in YYYY-MM-DD format

        Returns:
            Prefix like "2026/01/08/"
        """
        parts = run_date.split("-")
        if len(parts) != 3:
            # Fallback to today
            now = datetime.now()
            return f"{now.year}/{now.month:02d}/{now.day:02d}/"
        return f"{parts[0]}/{parts[1]}/{parts[2]}/"

    def upload_file(self, local_path: Path, key: str) -> bool:
        """Upload a single file to MinIO

        Args:
            local_path: Local file path
            key: S3 object key

        Returns:
            True if successful
        """
        client = self._get_client()
        try:
            # Determine content type
            content_type = "application/octet-stream"
            suffix = local_path.suffix.lower()
            if suffix == ".json":
                content_type = "application/json"
            elif suffix == ".html":
                content_type = "text/html"
            elif suffix == ".png":
                content_type = "image/png"
            elif suffix == ".jpg" or suffix == ".jpeg":
                content_type = "image/jpeg"

            client.upload_file(
                str(local_path),
                self.bucket,
                key,
                ExtraArgs={"ContentType": content_type},
            )
            logger.debug(f"Uploaded: {key}")
            return True
        except Exception as e:
            logger.error(f"Upload failed for {key}: {e}")
            return False

    def archive_daily_run(
        self,
        run_date: str,
        out_dir: str = "out",
        include_feature_images: bool = True,
    ) -> ArchiveResult:
        """Archive all files from a daily run

        Args:
            run_date: Date in YYYY-MM-DD format
            out_dir: Output directory containing files
            include_feature_images: Whether to include feature images

        Returns:
            ArchiveResult with upload status
        """
        out_path = Path(out_dir)
        prefix = self._get_date_prefix(run_date)

        # Ensure bucket exists
        if not self._ensure_bucket():
            return ArchiveResult(
                success=False,
                files_uploaded=0,
                total_bytes=0,
                bucket=self.bucket,
                prefix=prefix,
                error="Failed to ensure bucket exists",
            )

        # Files to archive
        files_to_upload = []

        # Main files
        main_files = [
            "edition_pack.json",
            "post_flash.json",
            "post_flash.html",
            "post_earnings.json",
            "post_earnings.html",
            "post_deep.json",
            "post_deep.html",
            "quality_report.json",
            "checkpoint.json",
        ]

        for filename in main_files:
            filepath = out_path / filename
            if filepath.exists():
                files_to_upload.append((filepath, f"{prefix}{filename}"))

        # Feature images
        if include_feature_images:
            feature_dir = out_path / "feature_images"
            if feature_dir.exists():
                for img_file in feature_dir.glob("*.png"):
                    key = f"{prefix}feature_images/{img_file.name}"
                    files_to_upload.append((img_file, key))
                for img_file in feature_dir.glob("*.jpg"):
                    key = f"{prefix}feature_images/{img_file.name}"
                    files_to_upload.append((img_file, key))

        # Upload files
        uploaded = []
        total_bytes = 0

        for local_path, key in files_to_upload:
            if self.upload_file(local_path, key):
                uploaded.append(key)
                total_bytes += local_path.stat().st_size

        success = len(uploaded) > 0
        error = None if success else "No files uploaded"

        result = ArchiveResult(
            success=success,
            files_uploaded=len(uploaded),
            total_bytes=total_bytes,
            bucket=self.bucket,
            prefix=prefix,
            error=error,
            uploaded_files=uploaded,
        )

        logger.info(
            f"Archive complete: {len(uploaded)} files, "
            f"{total_bytes / 1024:.1f} KB to {self.bucket}/{prefix}"
        )

        return result

    def list_archives(self, year: int = None, month: int = None) -> List[str]:
        """List archived dates

        Args:
            year: Optional year filter
            month: Optional month filter (requires year)

        Returns:
            List of date prefixes (e.g., ["2026/01/08/", "2026/01/09/"])
        """
        client = self._get_client()

        prefix = ""
        if year:
            prefix = f"{year}/"
            if month:
                prefix = f"{year}/{month:02d}/"

        try:
            paginator = client.get_paginator("list_objects_v2")
            dates = set()

            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix, Delimiter="/"):
                for cp in page.get("CommonPrefixes", []):
                    dates.add(cp["Prefix"])

            return sorted(dates)
        except Exception as e:
            logger.error(f"List failed: {e}")
            return []

    def download_archive(self, run_date: str, output_dir: str = "download") -> bool:
        """Download archived files for a specific date

        Args:
            run_date: Date in YYYY-MM-DD format
            output_dir: Local directory to download to

        Returns:
            True if successful
        """
        client = self._get_client()
        prefix = self._get_date_prefix(run_date)
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        try:
            paginator = client.get_paginator("list_objects_v2")
            downloaded = 0

            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    # Relative path from prefix
                    rel_path = key[len(prefix):]
                    local_file = output_path / rel_path

                    # Create parent dirs
                    local_file.parent.mkdir(parents=True, exist_ok=True)

                    client.download_file(self.bucket, key, str(local_file))
                    downloaded += 1
                    logger.debug(f"Downloaded: {key}")

            logger.info(f"Downloaded {downloaded} files to {output_dir}")
            return downloaded > 0
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return False


def archive_to_minio(
    run_date: str,
    out_dir: str = "out",
) -> ArchiveResult:
    """Convenience function to archive daily run to MinIO

    Args:
        run_date: Date in YYYY-MM-DD format
        out_dir: Output directory

    Returns:
        ArchiveResult
    """
    archiver = MinIOArchiver()
    return archiver.archive_daily_run(run_date, out_dir)


@dataclass
class PublishResult:
    """Result of publishing from MinIO to Ghost"""
    success: bool
    posts_published: int
    results: Dict[str, Dict]
    error: Optional[str] = None


def publish_from_minio(
    run_date: str,
    status: str = "draft",
    send_newsletter: bool = False,
    email_segment: str = "status:-free",
    visibility: str = "members",
) -> PublishResult:
    """Fetch posts from MinIO and publish to Ghost

    完整流程:
    1. 從 MinIO 下載指定日期的文章
    2. 上傳 feature images 到 Ghost
    3. 發佈文章到 Ghost

    Args:
        run_date: Date in YYYY-MM-DD format (e.g., "2026-01-08")
        status: Ghost post status ("draft" or "published")
        send_newsletter: Whether to send newsletter (only for flash)
        email_segment: Newsletter segment ("status:free", "status:-free", etc.)
        visibility: Post visibility ("members", "paid", "public")

    Returns:
        PublishResult with publish status for each post
    """
    import tempfile
    from pathlib import Path

    # Download from MinIO to temp dir
    archiver = MinIOArchiver()

    with tempfile.TemporaryDirectory() as temp_dir:
        logger.info(f"Downloading {run_date} from MinIO...")

        if not archiver.download_archive(run_date, temp_dir):
            return PublishResult(
                success=False,
                posts_published=0,
                results={},
                error=f"Failed to download {run_date} from MinIO",
            )

        temp_path = Path(temp_dir)

        # Load posts
        posts = {}
        for post_type in ["flash", "earnings", "deep"]:
            json_path = temp_path / f"post_{post_type}.json"
            if json_path.exists():
                with open(json_path, "r", encoding="utf-8") as f:
                    posts[post_type] = json.load(f)
                logger.info(f"Loaded {post_type}: {posts[post_type].get('slug')}")

        if not posts:
            return PublishResult(
                success=False,
                posts_published=0,
                results={},
                error=f"No posts found for {run_date}",
            )

        # Publish to Ghost
        from .ghost_admin import GhostPublisher

        results = {}
        published_count = 0

        with GhostPublisher() as publisher:
            # Publish order: earnings -> deep -> flash (flash last for newsletter)
            for post_type in ["earnings", "deep", "flash"]:
                if post_type not in posts:
                    continue

                post = posts[post_type]
                logger.info(f"Publishing {post_type} ({post.get('slug')})...")

                # Upload feature image if exists
                feature_dir = temp_path / "feature_images"
                # Try to find matching feature image
                for img_file in feature_dir.glob("*.png") if feature_dir.exists() else []:
                    if post_type in img_file.name or post.get("slug", "") in img_file.name:
                        image_url = publisher.upload_image(img_file)
                        if image_url:
                            post["feature_image"] = image_url
                            logger.info(f"  Feature image uploaded: {img_file.name}")
                        break

                # Send newsletter only for flash (and only if requested)
                should_send = send_newsletter and post_type == "flash"

                result = publisher.upsert_by_slug(
                    post=post,
                    status=status,
                    send_newsletter=should_send,
                    email_segment=email_segment if should_send else None,
                    visibility=visibility,
                )

                results[post_type] = {
                    "success": result.success,
                    "url": result.url,
                    "error": result.error,
                    "newsletter_sent": result.newsletter_sent,
                }

                if result.success:
                    published_count += 1
                    logger.info(f"  ✓ Published: {result.url}")
                else:
                    logger.error(f"  ✗ Failed: {result.error}")

        return PublishResult(
            success=published_count > 0,
            posts_published=published_count,
            results=results,
        )


# CLI for publishing from MinIO
if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="Publish posts from MinIO to Ghost")
    parser.add_argument("date", help="Date to publish (YYYY-MM-DD)")
    parser.add_argument("--status", default="draft", choices=["draft", "published"])
    parser.add_argument("--send-newsletter", action="store_true")
    parser.add_argument("--segment", default="status:-free")
    parser.add_argument("--visibility", default="members")

    args = parser.parse_args()

    result = publish_from_minio(
        run_date=args.date,
        status=args.status,
        send_newsletter=args.send_newsletter,
        email_segment=args.segment,
        visibility=args.visibility,
    )

    print(f"\nPublished {result.posts_published} posts")
    for post_type, r in result.results.items():
        status = "✓" if r["success"] else "✗"
        print(f"  {status} {post_type}: {r.get('url') or r.get('error')}")

    sys.exit(0 if result.success else 1)

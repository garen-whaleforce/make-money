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

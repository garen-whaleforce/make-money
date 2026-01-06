"""Time utilities"""

import uuid
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo


def get_now(tz: str = "America/New_York") -> datetime:
    """Get current datetime in specified timezone.

    Args:
        tz: Timezone string (default: America/New_York)

    Returns:
        Current datetime with timezone info
    """
    return datetime.now(ZoneInfo(tz))


def get_run_id(prefix: str = "run") -> str:
    """Generate a unique run ID.

    Args:
        prefix: Prefix for the run ID

    Returns:
        Unique run ID string
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    return f"{prefix}_{timestamp}_{short_uuid}"


def format_datetime(dt: datetime, fmt: str = "iso") -> str:
    """Format datetime to string.

    Args:
        dt: Datetime object
        fmt: Format type ('iso', 'date', 'time', 'full')

    Returns:
        Formatted datetime string
    """
    formats = {
        "iso": "%Y-%m-%dT%H:%M:%S%z",
        "date": "%Y-%m-%d",
        "time": "%H:%M:%S",
        "full": "%Y-%m-%d %H:%M:%S %Z",
    }
    return dt.strftime(formats.get(fmt, fmt))


def parse_datetime(dt_str: str, fmt: Optional[str] = None) -> Optional[datetime]:
    """Parse datetime string to datetime object.

    Args:
        dt_str: Datetime string
        fmt: Optional format string (auto-detect if None)

    Returns:
        Datetime object or None if parsing fails
    """
    if fmt:
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            return None

    # Try common formats
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
    ]

    for format_str in formats:
        try:
            return datetime.strptime(dt_str, format_str)
        except ValueError:
            continue

    return None

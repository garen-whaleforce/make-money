"""Caching utilities"""

import json
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional

from ..utils.logging import get_logger
from ..utils.text import hash_text

logger = get_logger(__name__)


class FileCache:
    """File-based cache"""

    def __init__(self, cache_dir: str = "data/cache", default_ttl: int = 3600):
        """Initialize file cache.

        Args:
            cache_dir: Directory for cache files
            default_ttl: Default TTL in seconds
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl = default_ttl

    def _get_cache_path(self, key: str) -> Path:
        """Get cache file path for key"""
        hashed = hash_text(key, length=32)
        return self.cache_dir / f"{hashed}.json"

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        cache_path = self._get_cache_path(key)

        if not cache_path.exists():
            return None

        try:
            with open(cache_path) as f:
                data = json.load(f)

            if time.time() > data.get("expires_at", 0):
                cache_path.unlink(missing_ok=True)
                return None

            return data.get("value")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Cache read error: {e}")
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: TTL in seconds (uses default if None)
        """
        cache_path = self._get_cache_path(key)
        ttl = ttl if ttl is not None else self.default_ttl

        try:
            data = {
                "key": key,
                "value": value,
                "created_at": time.time(),
                "expires_at": time.time() + ttl,
            }
            with open(cache_path, "w") as f:
                json.dump(data, f)
        except (OSError, TypeError) as e:
            logger.warning(f"Cache write error: {e}")

    def delete(self, key: str) -> None:
        """Delete value from cache"""
        cache_path = self._get_cache_path(key)
        cache_path.unlink(missing_ok=True)

    def clear(self) -> None:
        """Clear all cache"""
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink(missing_ok=True)


def cache_result(
    cache: FileCache,
    key_func: Optional[Callable[..., str]] = None,
    ttl: Optional[int] = None,
) -> Callable:
    """Decorator to cache function results.

    Args:
        cache: FileCache instance
        key_func: Function to generate cache key from args
        ttl: Cache TTL in seconds

    Returns:
        Decorator function
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Generate cache key
            if key_func:
                key = key_func(*args, **kwargs)
            else:
                key = f"{func.__name__}:{args}:{kwargs}"

            # Try cache
            cached = cache.get(key)
            if cached is not None:
                logger.debug(f"Cache hit: {key[:50]}...")
                return cached

            # Call function
            result = func(*args, **kwargs)

            # Store in cache
            if result is not None:
                cache.set(key, result, ttl)

            return result

        return wrapper

    return decorator

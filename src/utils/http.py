"""HTTP utilities"""

import time
from typing import Any, Optional

import httpx

from .logging import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """Simple rate limiter"""

    def __init__(self, requests_per_minute: int = 60):
        self.rpm = requests_per_minute
        self.interval = 60.0 / requests_per_minute
        self.last_request = 0.0

    def wait(self) -> None:
        """Wait if necessary to respect rate limit"""
        now = time.time()
        elapsed = now - self.last_request
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self.last_request = time.time()


def create_http_client(
    timeout: float = 30.0,
    max_retries: int = 3,
    headers: Optional[dict[str, str]] = None,
) -> httpx.Client:
    """Create an HTTP client with retry logic.

    Args:
        timeout: Request timeout in seconds
        max_retries: Maximum number of retries
        headers: Additional headers

    Returns:
        Configured httpx.Client
    """
    transport = httpx.HTTPTransport(retries=max_retries)

    default_headers = {
        "User-Agent": "DailyDeepBrief/0.1.0",
        "Accept": "application/json",
    }
    if headers:
        default_headers.update(headers)

    return httpx.Client(
        timeout=httpx.Timeout(timeout),
        transport=transport,
        headers=default_headers,
        follow_redirects=True,
    )


def fetch_with_retry(
    url: str,
    client: Optional[httpx.Client] = None,
    max_retries: int = 3,
    timeout: float = 30.0,
    rate_limiter: Optional[RateLimiter] = None,
    **kwargs: Any,
) -> Optional[httpx.Response]:
    """Fetch URL with retry logic.

    Args:
        url: URL to fetch
        client: Optional httpx client
        max_retries: Maximum retries
        timeout: Request timeout
        rate_limiter: Optional rate limiter
        **kwargs: Additional arguments for httpx.get

    Returns:
        Response object or None
    """
    if rate_limiter:
        rate_limiter.wait()

    own_client = client is None
    if own_client:
        client = create_http_client(timeout=timeout, max_retries=max_retries)

    try:
        for attempt in range(max_retries):
            try:
                response = client.get(url, **kwargs)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    # Rate limited - wait and retry
                    wait_time = 2 ** attempt
                    logger.warning(f"Rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
                elif e.response.status_code >= 500:
                    # Server error - retry
                    wait_time = 2 ** attempt
                    logger.warning(f"Server error {e.response.status_code}, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    raise
            except httpx.RequestError as e:
                logger.warning(f"Request error: {e}, attempt {attempt + 1}/{max_retries}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        return None
    finally:
        if own_client:
            client.close()

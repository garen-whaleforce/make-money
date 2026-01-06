"""Text utilities"""

import hashlib
import re
import unicodedata
from typing import Optional


def slugify(text: str, max_length: int = 100) -> str:
    """Convert text to URL-friendly slug.

    Args:
        text: Input text
        max_length: Maximum slug length

    Returns:
        URL-friendly slug
    """
    # Normalize unicode
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")

    # Convert to lowercase and replace spaces
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)

    # Truncate
    if len(text) > max_length:
        text = text[:max_length].rsplit("-", 1)[0]

    return text.strip("-")


def truncate(text: str, max_length: int = 300, suffix: str = "...") -> str:
    """Truncate text to specified length.

    Args:
        text: Input text
        max_length: Maximum length
        suffix: Suffix to append if truncated

    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text

    truncated = text[: max_length - len(suffix)]
    # Try to break at word boundary
    last_space = truncated.rfind(" ")
    if last_space > max_length * 0.7:
        truncated = truncated[:last_space]

    return truncated + suffix


def hash_text(text: str, length: int = 16) -> str:
    """Generate a hash of the text.

    Args:
        text: Input text
        length: Hash length (max 64 for sha256)

    Returns:
        Hash string
    """
    return hashlib.sha256(text.encode()).hexdigest()[:length]


def extract_tickers(text: str) -> list[str]:
    """Extract stock tickers from text.

    Args:
        text: Input text

    Returns:
        List of potential tickers
    """
    # Pattern for stock tickers (1-5 uppercase letters)
    pattern = r"\b([A-Z]{1,5})\b"
    matches = re.findall(pattern, text)

    # Filter out common words
    common_words = {
        "A", "I", "IT", "AT", "OR", "IS", "ON", "TO", "BY", "IN", "AN",
        "AS", "OF", "IF", "THE", "FOR", "AND", "CEO", "CFO", "IPO",
        "GDP", "CPI", "FED", "SEC", "USA", "NYSE", "ETF", "PE", "EPS",
        "AI", "US", "UK", "EU", "AM", "PM",
    }

    return [m for m in matches if m not in common_words]


def clean_html(html: str) -> str:
    """Remove HTML tags from text.

    Args:
        html: HTML string

    Returns:
        Plain text
    """
    clean = re.compile("<.*?>")
    return re.sub(clean, "", html)


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace in text.

    Args:
        text: Input text

    Returns:
        Text with normalized whitespace
    """
    return " ".join(text.split())

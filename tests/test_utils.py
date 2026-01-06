"""Tests for utility modules"""

import pytest
from src.utils.text import slugify, truncate, hash_text, extract_tickers
from src.utils.time import get_run_id, parse_datetime


class TestSlugify:
    def test_basic_slug(self):
        assert slugify("Hello World") == "hello-world"

    def test_special_characters(self):
        assert slugify("NVDA: AI Chip Leader!") == "nvda-ai-chip-leader"

    def test_unicode(self):
        assert slugify("AI 晶片市場") == "ai"

    def test_max_length(self):
        long_text = "This is a very long title that should be truncated"
        result = slugify(long_text, max_length=20)
        assert len(result) <= 20


class TestTruncate:
    def test_no_truncate(self):
        text = "Short text"
        assert truncate(text, 100) == text

    def test_truncate_at_word(self):
        text = "This is a longer text that needs truncation"
        result = truncate(text, 25)
        assert len(result) <= 25
        assert result.endswith("...")


class TestHashText:
    def test_consistent_hash(self):
        text = "test input"
        assert hash_text(text) == hash_text(text)

    def test_different_hash(self):
        assert hash_text("text1") != hash_text("text2")

    def test_hash_length(self):
        result = hash_text("test", length=8)
        assert len(result) == 8


class TestExtractTickers:
    def test_basic_tickers(self):
        text = "NVDA and TSLA are leading AI stocks"
        tickers = extract_tickers(text)
        assert "NVDA" in tickers
        assert "TSLA" in tickers

    def test_filter_common_words(self):
        text = "AI is the future for NVDA"
        tickers = extract_tickers(text)
        assert "AI" not in tickers
        assert "NVDA" in tickers


class TestGetRunId:
    def test_run_id_format(self):
        run_id = get_run_id()
        assert run_id.startswith("run_")
        parts = run_id.split("_")
        assert len(parts) == 4  # run, date, time, uuid

    def test_unique_ids(self):
        id1 = get_run_id()
        id2 = get_run_id()
        assert id1 != id2


class TestParseDatetime:
    def test_iso_format(self):
        dt = parse_datetime("2025-01-05T10:30:00")
        assert dt is not None
        assert dt.year == 2025
        assert dt.month == 1
        assert dt.day == 5

    def test_date_only(self):
        dt = parse_datetime("2025-01-05")
        assert dt is not None
        assert dt.year == 2025

    def test_invalid_format(self):
        dt = parse_datetime("invalid")
        assert dt is None

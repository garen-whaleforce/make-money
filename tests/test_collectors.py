"""Tests for collectors"""

import pytest
from unittest.mock import Mock, patch
from src.collectors.google_news_rss import GoogleNewsCollector, CandidateEvent


class TestCandidateEvent:
    def test_to_dict(self):
        event = CandidateEvent(
            id="test123",
            title="Test Event",
            url="https://example.com",
            publisher="Test Publisher",
            related_tickers=["NVDA"],
            related_themes=["ai_chips"],
        )
        result = event.to_dict()

        assert result["id"] == "test123"
        assert result["title"] == "Test Event"
        assert result["url"] == "https://example.com"
        assert "NVDA" in result["related_tickers"]


class TestGoogleNewsCollector:
    def test_build_url(self):
        collector = GoogleNewsCollector()
        url = collector._build_url("NVDA stock")

        assert "news.google.com" in url
        assert "NVDA" in url
        assert "hl=en" in url
        assert "gl=US" in url

    def test_generate_event_id(self):
        collector = GoogleNewsCollector()
        id1 = collector._generate_event_id("Title", "https://example.com")
        id2 = collector._generate_event_id("Title", "https://example.com")
        id3 = collector._generate_event_id("Different", "https://example.com")

        assert id1 == id2  # Same input -> same ID
        assert id1 != id3  # Different input -> different ID
        assert len(id1) == 16

    def test_parse_publisher(self):
        collector = GoogleNewsCollector()

        assert collector._parse_publisher("Reuters") == "Reuters"
        assert collector._parse_publisher("  Bloomberg  ") == "Bloomberg"
        assert collector._parse_publisher("") == "Unknown"
        assert collector._parse_publisher(None) == "Unknown"

    @patch("feedparser.parse")
    def test_fetch_query_with_cache(self, mock_parse):
        """Test that cache is used when available"""
        from src.storage.cache import FileCache

        cache = FileCache(cache_dir="data/cache/test", default_ttl=600)
        collector = GoogleNewsCollector(cache=cache, cache_ttl=600)

        # Pre-populate cache
        cache_key = "gnews:NVDA stock:10"
        cached_data = [{
            "id": "cached123",
            "title": "Cached Event",
            "url": "https://example.com",
            "published_at": None,
            "publisher": "Test",
            "related_tickers": ["NVDA"],
            "related_themes": [],
            "query": "NVDA stock",
            "snippet": None,
        }]
        cache.set(cache_key, cached_data, ttl=600)

        # Fetch should use cache
        events = collector.fetch_query("NVDA stock", limit=10)

        # feedparser should not be called
        mock_parse.assert_not_called()

        assert len(events) == 1
        assert events[0].id == "cached123"

        # Cleanup
        cache.delete(cache_key)

    @patch("feedparser.parse")
    def test_fetch_query_parses_feed(self, mock_parse):
        """Test feed parsing"""
        mock_parse.return_value = Mock(
            bozo=False,
            entries=[
                {
                    "title": "NVIDIA Q4 Earnings Beat",
                    "link": "https://news.example.com/nvda",
                    "published": "Mon, 01 Jan 2025 10:00:00 GMT",
                    "source": {"title": "Reuters"},
                    "summary": "NVIDIA reported strong Q4 results...",
                }
            ],
        )

        collector = GoogleNewsCollector(cache_ttl=0)  # Disable cache
        events = collector.fetch_query("NVDA stock", limit=10, ticker="NVDA")

        assert len(events) == 1
        assert "NVIDIA" in events[0].title
        assert events[0].publisher == "Reuters"
        assert "NVDA" in events[0].related_tickers

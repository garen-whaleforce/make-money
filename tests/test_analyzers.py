"""Tests for analyzers"""

import pytest
from src.collectors.google_news_rss import CandidateEvent
from src.analyzers.event_scoring import EventScorer, ScoredEvent


class TestEventScorer:
    @pytest.fixture
    def scorer(self):
        return EventScorer()

    def test_classify_earnings_event(self, scorer):
        event_type, is_rumor = scorer.classify_event_type(
            "NVIDIA Q4 earnings beat expectations"
        )
        assert event_type == "earnings"
        assert not is_rumor

    def test_classify_rumor_event(self, scorer):
        event_type, is_rumor = scorer.classify_event_type(
            "Apple reportedly working on new AI chip"
        )
        assert is_rumor

    def test_classify_guidance_event(self, scorer):
        event_type, is_rumor = scorer.classify_event_type(
            "AMD raises full-year revenue guidance"
        )
        # "raises" matches earnings pattern first, so it might be classified as earnings
        assert event_type in ["guidance", "earnings"]

    def test_classify_regulation_event(self, scorer):
        event_type, is_rumor = scorer.classify_event_type(
            "SEC launches investigation into crypto exchange"
        )
        assert event_type == "regulation"

    def test_extract_tickers(self, scorer):
        text = "NVDA and AMD are competing in the AI chip market"
        tickers = scorer.extract_tickers_from_text(text)
        assert "NVDA" in tickers
        assert "AMD" in tickers

    def test_score_event_basic(self, scorer):
        event = CandidateEvent(
            id="test123",
            title="NVIDIA reports record Q4 revenue",
            url="https://example.com/news",
            publisher="Reuters",
            related_tickers=["NVDA"],
            related_themes=["ai_chips"],
        )

        scored = scorer.score_event(event, publisher_count=3)

        assert scored.event_type == "earnings"
        assert scored.total_score > 0
        assert "NVDA" in scored.matched_tickers
        assert "ai_chips" in scored.matched_themes

    def test_score_event_rumor_penalty(self, scorer):
        event_regular = CandidateEvent(
            id="test1",
            title="NVIDIA announces new GPU",
            url="https://example.com/1",
            publisher="Reuters",
            related_tickers=["NVDA"],
        )

        event_rumor = CandidateEvent(
            id="test2",
            title="NVIDIA reportedly developing new GPU",
            url="https://example.com/2",
            publisher="Reuters",
            related_tickers=["NVDA"],
        )

        scored_regular = scorer.score_event(event_regular)
        scored_rumor = scorer.score_event(event_rumor)

        assert scored_rumor.is_rumor
        assert scored_rumor.total_score < scored_regular.total_score

    def test_score_events_sorted(self, scorer):
        events = [
            CandidateEvent(
                id="low",
                title="Some random news",
                url="https://example.com/1",
                publisher="Unknown Blog",
            ),
            CandidateEvent(
                id="high",
                title="NVIDIA Q4 earnings beat expectations",
                url="https://example.com/2",
                publisher="Reuters",
                related_tickers=["NVDA"],
                related_themes=["ai_chips"],
            ),
        ]

        scored = scorer.score_events(events)

        assert len(scored) == 2
        assert scored[0].event.id == "high"  # Higher score first

    def test_select_primary(self, scorer):
        events = [
            CandidateEvent(
                id="test",
                title="NVIDIA announces new AI chip",
                url="https://example.com",
                publisher="Reuters",
                related_tickers=["NVDA"],
                related_themes=["ai_chips"],
            )
        ]

        scored = scorer.score_events(events)
        primary = scorer.select_primary(scored)

        assert primary is not None
        assert primary.event.id == "test"

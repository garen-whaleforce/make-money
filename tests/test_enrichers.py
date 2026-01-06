"""Tests for enrichers"""

import pytest
from unittest.mock import Mock, patch
from src.enrichers.base import PriceData, Fundamentals, Estimates, CompanyData
from src.enrichers.fmp import FMPEnricher


class TestPriceData:
    def test_to_dict(self):
        price = PriceData(
            last=150.0,
            change_pct_1d=2.5,
            volume=1000000,
            market_cap=1e12,
        )
        result = price.to_dict()

        assert result["last"] == 150.0
        assert result["change_pct_1d"] == 2.5
        assert result["volume"] == 1000000


class TestFundamentals:
    def test_to_dict(self):
        fund = Fundamentals(
            revenue_ttm=100e9,
            gross_margin=0.65,
            operating_margin=0.35,
        )
        result = fund.to_dict()

        assert result["revenue_ttm"] == 100e9
        assert result["gross_margin"] == 0.65


class TestCompanyData:
    def test_to_dict(self):
        company = CompanyData(
            ticker="NVDA",
            name="NVIDIA Corporation",
            sector="Technology",
            price=PriceData(last=150.0),
            peers=["AMD", "INTC"],
        )
        result = company.to_dict()

        assert result["ticker"] == "NVDA"
        assert result["name"] == "NVIDIA Corporation"
        assert result["price"]["last"] == 150.0
        assert "AMD" in result["peers"]

    def test_error_handling(self):
        company = CompanyData(
            ticker="INVALID",
            error="API error",
        )
        result = company.to_dict()

        assert result["error"] == "API error"


class TestFMPEnricher:
    def test_init_without_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            enricher = FMPEnricher(api_key=None)
            # Should not raise, just log warning

    def test_init_with_api_key(self):
        enricher = FMPEnricher(api_key="test_key")
        assert enricher.api_key == "test_key"

    @patch("httpx.Client.get")
    def test_get_quote_success(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = [{
            "price": 150.0,
            "changesPercentage": 2.5,
            "volume": 1000000,
            "marketCap": 1e12,
        }]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        enricher = FMPEnricher(api_key="test_key", cache_ttl=0)
        price = enricher.get_quote("NVDA")

        assert price is not None
        assert price.last == 150.0
        assert price.change_pct_1d == 2.5

    @patch("httpx.Client.get")
    def test_get_quote_empty_response(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        enricher = FMPEnricher(api_key="test_key", cache_ttl=0)
        price = enricher.get_quote("INVALID")

        assert price is None

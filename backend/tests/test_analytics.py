"""Tests for the optional Google Analytics integration placeholder.

The GA integration must never fabricate data: without configuration or
credentials it returns a clear configuration error, not fake numbers.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import app.config as config
from app.main import app


def _reload_config() -> None:
    importlib.reload(config)
    import app.services.analytics as analytics

    importlib.reload(analytics)


class TestAnalyticsPlaceholder:
    def test_status_reports_not_configured(self):
        # Ensure env vars are cleared for this test.
        config.GA_PROPERTY_ID = ""
        config.GA_CREDENTIALS_PATH = ""
        import app.services.analytics as analytics

        analytics.GA_PROPERTY_ID = ""
        analytics.GA_CREDENTIALS_PATH = ""

        client = TestClient(app)
        r = client.get("/api/analytics/status")
        assert r.status_code == 200
        body = r.json()
        assert body["configured"] is False
        assert "GA_PROPERTY_ID" in body["error"]

    def test_overview_returns_config_error_when_unconfigured(self):
        config.GA_PROPERTY_ID = ""
        config.GA_CREDENTIALS_PATH = ""
        import app.services.analytics as analytics

        analytics.GA_PROPERTY_ID = ""
        analytics.GA_CREDENTIALS_PATH = ""

        client = TestClient(app)
        r = client.get("/api/analytics/overview")
        assert r.status_code == 503
        body = r.json()
        assert "not configured" in body["detail"]

    def test_analytics_service_never_fabricates_data(self):
        """Without credentials the service raises, it never returns fake rows."""
        from app.services.analytics import AnalyticsUnavailableError, run_ga_report

        config.GA_PROPERTY_ID = ""
        config.GA_CREDENTIALS_PATH = ""
        import app.services.analytics as analytics

        analytics.GA_PROPERTY_ID = ""
        analytics.GA_CREDENTIALS_PATH = ""

        with pytest.raises(AnalyticsUnavailableError):
            run_ga_report(["date"], ["activeUsers"], "30daysAgo", "today")

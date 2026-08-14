"""Optional Google Analytics 4 integration (safe placeholder).

The manager asked whether GA data can be retrieved via a Python library. It
can — the official client is ``google-analytics-data``:

    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        DateRange, Dimension, Metric, RunReportRequest,
    )

    client = BetaAnalyticsDataClient()          # uses GOOGLE_APPLICATION_CREDENTIALS
    response = client.run_report(RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date="2026-01-01", end_date="today")],
        dimensions=[Dimension(name="pagePath")],
        metrics=[Metric(name="screenPageViews")],
    ))

Requirements (all on the Google side):
1. A GA4 property (e.g. Deccan Herald's) the authenticated account can access.
2. The Google Analytics Data API v1 enabled on the Google Cloud project.
3. Credentials via Application Default Credentials (service account JSON or
   ``gcloud auth application-default login``) with the
   ``analytics.readonly`` scope.

This module deliberately does NOT fabricate data and does NOT hardcode
credentials. It reads ``GA_PROPERTY_ID`` and ``GA_CREDENTIALS_PATH`` from the
environment; if either is missing, every endpoint returns a clear
configuration error so the app never claims GA data it cannot access.
"""
from __future__ import annotations

import os
from typing import Any, Dict

from ..config import GA_CREDENTIALS_PATH, GA_PROPERTY_ID


class AnalyticsUnavailableError(Exception):
    """Raised when GA integration is not configured / authenticated."""


def _credentials_available() -> bool:
    if GA_CREDENTIALS_PATH:
        return os.path.isfile(GA_CREDENTIALS_PATH)
    # Application Default Credentials may also come from the well-known ADC
    # file or gcloud login — treat GOOGLE_APPLICATION_CREDENTIALS as available
    # too (set by the runtime environment).
    return bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))


def check_ga_config() -> None:
    """Raise AnalyticsUnavailableError with a clear reason when GA cannot work."""
    if not GA_PROPERTY_ID:
        raise AnalyticsUnavailableError(
            "Google Analytics is not configured: GA_PROPERTY_ID is not set. "
            "Set GA_PROPERTY_ID to the GA4 property id and provide credentials."
        )
    if not _credentials_available():
        raise AnalyticsUnavailableError(
            "Google Analytics credentials are not available. Set "
            "GA_CREDENTIALS_PATH to a service-account JSON file or configure "
            "Application Default Credentials (GOOGLE_APPLICATION_CREDENTIALS)."
        )


def run_ga_report(
    dimensions: list[str],
    metrics: list[str],
    start_date: str,
    end_date: str,
) -> Dict[str, Any]:
    """Query the GA4 Data API via the official Python client.

    Only called after check_ga_config() passes. Returns a plain dict of the
    runReport response. Never returns fabricated data.
    """
    check_ga_config()

    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise AnalyticsUnavailableError(
            "The 'google-analytics-data' package is not installed. "
            "Install it (pip install google-analytics-data) to enable GA4 queries."
        ) from exc

    client = BetaAnalyticsDataClient()  # uses Application Default Credentials
    request = RunReportRequest(
        property=f"properties/{GA_PROPERTY_ID}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
    )
    response = client.run_report(request)

    rows = [
        {
            "dimensions": [dv.value for dv in row.dimension_values],
            "metrics": [mv.value for mv in row.metric_values],
        }
        for row in response.rows
    ]
    return {
        "property_id": GA_PROPERTY_ID,
        "dimensions": [h.name for h in response.dimension_headers],
        "metrics": [h.name for h in response.metric_headers],
        "rows": rows,
        "row_count": response.row_count,
    }

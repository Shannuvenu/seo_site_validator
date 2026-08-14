"""Optional Google Analytics 4 routes (safe placeholder).

These endpoints return a clear configuration/authentication error until
GA_PROPERTY_ID and GA credentials are provided — they never fabricate data.
No frontend integration exists yet; these are for the manager's GA
investigation and future wiring.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..services.analytics import (
    AnalyticsUnavailableError,
    check_ga_config,
    run_ga_report,
)

router = APIRouter(tags=["analytics"])


def _ga_or_404(fn):
    try:
        return fn()
    except AnalyticsUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/analytics/status")
async def analytics_status() -> dict:
    """Whether GA integration is configured (never returns fake data)."""
    try:
        check_ga_config()
        return {"configured": True, "property_id": None}
    except AnalyticsUnavailableError as exc:
        return {"configured": False, "error": str(exc)}


@router.get("/analytics/overview")
async def analytics_overview() -> dict:
    """GA4 overview report (active users / page views over 30 days)."""
    return _ga_or_404(
        lambda: run_ga_report(
            dimensions=["date"],
            metrics=["activeUsers", "screenPageViews"],
            start_date="30daysAgo",
            end_date="today",
        )
    )


@router.get("/analytics/events")
async def analytics_events() -> dict:
    """GA4 top events over 30 days."""
    return _ga_or_404(
        lambda: run_ga_report(
            dimensions=["eventName"],
            metrics=["eventCount"],
            start_date="30daysAgo",
            end_date="today",
        )
    )


@router.get("/analytics/pageviews")
async def analytics_pageviews() -> dict:
    """GA4 top pages by views over 30 days."""
    return _ga_or_404(
        lambda: run_ga_report(
            dimensions=["pagePath"],
            metrics=["screenPageViews"],
            start_date="30daysAgo",
            end_date="today",
        )
    )

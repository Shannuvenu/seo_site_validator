"""Scan and structured-data validation routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models.schemas import ScanRequest, ScanResponse
from ..services.pipeline import analyze_structured_data, scan_urls
from ..services.fetcher import Fetcher

router = APIRouter(tags=["scan"])


@router.post("/scan", response_model=ScanResponse)
async def scan(request: ScanRequest) -> ScanResponse:
    """Fetch and analyze up to 15 URLs concurrently.

    Each URL is processed independently: one failure never stops the others.
    """
    urls = [u.strip() for u in request.urls if u and u.strip()]
    if not urls:
        raise HTTPException(status_code=422, detail="At least one URL is required.")
    results = await scan_urls(
        urls,
        include_html=request.include_html,
        timeout_seconds=request.timeout_seconds,
        max_concurrent=5,
    )
    return ScanResponse(results=results, scan_id="")


@router.post("/structured-data/validate", response_model=ScanResponse)
async def validate_structured_data(request: ScanRequest) -> ScanResponse:
    """Validate structured data for one or more URLs (same pipeline as /scan,
    kept as a dedicated endpoint for the Structured Data module)."""
    urls = [u.strip() for u in request.urls if u and u.strip()]
    if not urls:
        raise HTTPException(status_code=422, detail="At least one URL is required.")
    results = await scan_urls(
        urls,
        include_html=request.include_html,
        timeout_seconds=request.timeout_seconds,
        max_concurrent=5,
    )
    return ScanResponse(results=results, scan_id="")


@router.post("/structured-data/validate-html")
async def validate_html(payload: dict) -> dict:
    """Validate structured data directly from a raw HTML body (used by tests
    and the HTML-paste workflow)."""
    html = payload.get("html", "")
    if not html:
        raise HTTPException(status_code=422, detail="'html' is required.")
    result = analyze_structured_data(html)
    return {"structured_data": result.model_dump()}

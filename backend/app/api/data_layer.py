"""Data Layer routes: persistent browser session for dataLayer capture.

A session stays alive between calls: start opens the browser (and injects the
observer automatically), events/status poll the capture, click/click-element
drive the page, clear wipes the history, export downloads the full session,
close frees the browser.

Method/route contract (frontend must match EXACTLY):
  POST  /api/data-layer/start
  POST  /api/data-layer/click
  POST  /api/data-layer/click-element
  GET   /api/data-layer/status?session_id=...
  GET   /api/data-layer/events?session_id=...
  POST  /api/data-layer/clear
  POST  /api/data-layer/export
  POST  /api/data-layer/close
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..models.schemas import (
    DataLayerClearRequest,
    DataLayerClickElementRequest,
    DataLayerClickElementResponse,
    DataLayerClickRequest,
    DataLayerClickResponse,
    DataLayerCloseRequest,
    DataLayerExportResponse,
    DataLayerStartRequest,
    DataLayerStartResponse,
    DataLayerStatusResponse,
)
from ..services.data_layer import DataLayerService

router = APIRouter(tags=["data-layer"])

_service = DataLayerService()


@router.post("/data-layer/start", response_model=DataLayerStartResponse)
async def start_capture(request: DataLayerStartRequest) -> DataLayerStartResponse:
    """Open a real Chromium browser and navigate to the URL.

    The observer is injected automatically (before any page script runs), so
    dataLayer events and user interactions are captured without any manual
    script. The returned ``session_id`` is used for all subsequent data-layer
    calls.
    """
    session = await _service.start(
        request.url,
        navigation_pause_ms=request.navigation_pause_ms or 2500,
        click_text=request.click_text,
        click_selector=request.click_selector,
        headless=True,  # server has no display — visible/non-headless mode can never work here
    )
    return DataLayerStartResponse(
        session_id=session.id, url=session.url, status=session.status, error=session.error
    )


@router.post("/data-layer/click", response_model=DataLayerClickResponse)
async def click_element(request: DataLayerClickRequest) -> DataLayerClickResponse:
    """Click a visible element containing the given text in the live page."""
    result = await _service.click(request.session_id, request.text)
    return DataLayerClickResponse(
        session_id=request.session_id,
        clicked=result["clicked"],
        message=result["message"],
    )


@router.post("/data-layer/ingest", response_model=dict)
async def ingest_record(payload: dict) -> dict:
    """Accept a record beaconed directly from a monitored page (best-effort
    fast path for events right before a cross-origin navigation)."""
    session_id = str(payload.get("session_id") or "")
    record = payload.get("record")
    if not session_id or not isinstance(record, dict):
        return {"ok": False, "message": "session_id and record are required."}
    return await _service.ingest(session_id, record)


@router.post("/data-layer/click-element", response_model=DataLayerClickElementResponse)
async def click_element_by_selector(
    request: DataLayerClickElementRequest,
) -> DataLayerClickElementResponse:
    """Click an element by selector and return rich element info about it."""
    result = await _service.click_element(request.session_id, request.selector, request.text)
    return DataLayerClickElementResponse(**result)


@router.get("/data-layer/events", response_model=DataLayerStatusResponse)
async def get_events(
    session_id: str = Query(..., description="Data layer session id"),
) -> DataLayerStatusResponse:
    """Return the current session status and captured records."""
    data = await _service.get_events(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Data layer session not found.")
    return DataLayerStatusResponse(**data)


@router.get("/data-layer/status", response_model=DataLayerStatusResponse)
async def get_status(
    session_id: str = Query(..., description="Data layer session id"),
) -> DataLayerStatusResponse:
    """Return the current session status (without the full event history)."""
    data = await _service.status(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Data layer session not found.")
    return DataLayerStatusResponse(**data)


@router.post("/data-layer/clear", response_model=dict)
async def clear_events(request: DataLayerClearRequest) -> dict:
    """Clear the captured event history (browser localStorage + backend log).
    The browser stays open."""
    result = await _service.clear(request.session_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("message", "Session not found."))
    return result


@router.post("/data-layer/export", response_model=DataLayerExportResponse)
async def export_session(request: DataLayerCloseRequest) -> DataLayerExportResponse:
    """Export the complete captured session as JSON (all metadata included)."""
    data = await _service.export(request.session_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Data layer session not found.")
    return DataLayerExportResponse(**data)


@router.get("/data-layer/source")
async def view_source(
    session_id: str = Query(..., description="Data layer session id"),
    max_chars: int = Query(2_000_000, ge=1000, le=5_000_000),
) -> dict:
    """Return the CURRENT page's live HTML (source viewer for the timeline).

    The live DOM is serialized so the source reflects the page the user is
    looking at (after client-side rendering / navigation), not the raw bytes.
    """
    result = await _service.view_source(session_id, max_chars=max_chars)
    if result is None:
        raise HTTPException(status_code=404, detail="Data layer session not found.")
    return result


@router.post("/data-layer/close", response_model=dict)
async def close_session(request: DataLayerCloseRequest) -> dict:
    """Close the browser session and free all resources."""
    return await _service.close(request.session_id)
"""API router: wires all module routes together."""
from __future__ import annotations

from fastapi import APIRouter

from .analytics import router as analytics_router
from .data_layer import router as data_layer_router
from .scan import router as scan_router
from .site_structure import router as site_structure_router
from .vocab import router as vocab_router

api_router = APIRouter()

api_router.include_router(scan_router)
api_router.include_router(vocab_router)
api_router.include_router(data_layer_router)
api_router.include_router(site_structure_router)
api_router.include_router(analytics_router)


@api_router.get("/health")
async def health():
    return {"status": "ok", "backend": "fastapi", "version": "1.0.0"}

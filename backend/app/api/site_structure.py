"""Site Structure route: build the section tree from Quintype config."""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..models.schemas import SiteStructureResult
from ..services.site_structure import SiteStructureService

router = APIRouter(tags=["site-structure"])

_service = SiteStructureService()


@router.get("/site-structure/config", response_model=SiteStructureResult)
async def site_config(site: str = Query("deccanherald")) -> SiteStructureResult:
    """Return the Quintype section tree for a site ('deccanherald' | 'prajavani')."""
    return await _service.fetch_config(site)

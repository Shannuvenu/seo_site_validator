```python
"""FastAPI application entry point.

Serves the REST API plus (optionally) the built React frontend from
frontend/dist when present — the frontend also works standalone with Vite dev
server + CORS.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes import api_router
from .config import FRONTEND_DIST

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="SEO & Structured Data Health Check API",
    version="1.0.0",
    description=(
        "Technical SEO, Schema.org validation, data layer inspection, and "
        "Quintype site structure for news sites (Deccan Herald, Prajavani)."
    ),
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
# Local development + deployed Vercel frontend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "https://seo-site-validator.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------
app.include_router(api_router, prefix="/api")


# ---------------------------------------------------------------------------
# Optional production frontend
# ---------------------------------------------------------------------------
# If frontend/dist exists, FastAPI can serve the built React frontend.
# In the current deployment architecture, Vercel serves the frontend
# separately, while Render serves this FastAPI backend.
_dist = Path(FRONTEND_DIST)

if _dist.exists() and (_dist / "index.html").exists():
    from fastapi.responses import FileResponse

    @app.get("/", include_in_schema=False)
    async def serve_index():
        return FileResponse(str(_dist / "index.html"))

    app.mount(
        "/",
        StaticFiles(directory=str(_dist), html=True),
        name="frontend",
    )

else:

    @app.get("/")
    async def root():
        return {
            "name": "SEO & Structured Data Health Check",
            "docs": "/docs",
            "health": "/api/health",
        }
```

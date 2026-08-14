"""Application configuration."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Root of the whole project (frontend/ and backend/ live here).
PROJECT_ROOT = BASE_DIR.parent

# Where the built frontend assets live, when served by FastAPI.
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

# Schema.org vocabulary cache.
VOCAB_DIR = BASE_DIR / "app" / "vocab"
SCHEMAORG_URL = "https://schema.org/version/latest/schemaorg-current-https.jsonld"
VOCAB_CACHE_FILE = VOCAB_DIR / "schemaorg-current.jsonld"
VOCAB_META_FILE = VOCAB_DIR / "vocab_meta.json"

# Networking.
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("SEO_FETCH_TIMEOUT", "20"))
MAX_FETCH_SIZE_BYTES = int(os.environ.get("SEO_MAX_FETCH_BYTES", str(8 * 1024 * 1024)))
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 "
    "SEO-StructuredData-HealthCheck/1.0"
)

# Scanning.
MAX_URLS_PER_SCAN = 15
MAX_CONCURRENT_FETCHES = 5
DATA_LAYER_MAX_EVENTS = 200
DATA_LAYER_MAX_BYTES = 2 * 1024 * 1024

# Data Layer browser session timeout (seconds).
DATA_LAYER_BROWSER_TIMEOUT = 90

# Public base URL the monitored pages can beacon records to (optional).
# The in-page observer uses navigator.sendBeacon as a best-effort fast path for
# events that occur right before a (possibly cross-origin) navigation, where
# the page's localStorage becomes unreachable. This only works when the backend
# is reachable from the page WITHOUT mixed-content blocking (i.e. an HTTPS
# backend URL in production). Local dev over http://127.0.0.1 is gracefully
# skipped — the localStorage sweep remains the primary transport.
DL_BEACON_URL = os.environ.get("DL_BEACON_URL", "").strip()

# Google Analytics 4 (optional integration — NO hardcoded credentials).
# When GA_PROPERTY_ID is set AND credentials are available via Application
# Default Credentials (GOOGLE_APPLICATION_CREDENTIALS), /api/analytics/* can
# query the GA4 Data API. Without them the endpoints return a clear
# configuration error — they never fabricate data.
GA_PROPERTY_ID = os.environ.get("GA_PROPERTY_ID", "").strip()
GA_CREDENTIALS_PATH = os.environ.get("GA_CREDENTIALS_PATH", "").strip()

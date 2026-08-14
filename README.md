# SEO & Structured Data Health Check

A production-quality internal tool for auditing news websites (Deccan Herald, Prajavani)
with **four modules**:

1. **Technical SEO** — titles, meta, canonical, robots, headings, images, links, Open Graph, Twitter, hreflang.
2. **Structured Data / Schema.org Validator** — real Schema.org validation with **error → exact source location navigation**.
3. **Data Layer Inspector** — real-browser `window.dataLayer` capture with `push` hooking and `localStorage` persistence.
4. **Site Structure** — Quintype section tree built from the site's own config API.

**No Streamlit. No paywall.**

---

## Architecture

```
project/
├── frontend/                 # React + TypeScript + Vite
│   ├── src/
│   │   ├── components/       # UrlInputBar, SourceViewer (CodeMirror)
│   │   ├── pages/            # TechnicalSeo, StructuredData, DataLayer, SiteStructure
│   │   ├── services/         # api.ts (REST client)
│   │   ├── types/            # backend models mirrored as TS types
│   │   └── styles/           # global.css + per-page css
│   └── vite.config.ts        # /api proxy → backend :8000
│
├── backend/                  # Python + FastAPI
│   ├── app/
│   │   ├── api/              # routes: scan, data-layer, site-structure, vocab
│   │   ├── models/           # Pydantic response models
│   │   ├── parsers/          # sourceloc, extractor, sourcemap, normalizer, jsonld_parser
│   │   ├── validators/       # vocabulary (Schema.org vocab), schema_org
│   │   ├── services/         # fetcher (SSRF-guarded), pipeline, technical_seo, data_layer, site_structure
│   │   ├── vocab/            # cached schemaorg-current.jsonld (auto-downloaded once)
│   │   └── main.py
│   └── tests/                # pytest (43 tests)
│
└── README.md
```

```
React (Vite :5173) ──REST──▶ FastAPI (:8000) ──▶ async fetch (httpx)
                                          ├──▶ Schema.org vocab + validator
                                          ├──▶ Technical SEO analyzer
                                          ├──▶ Playwright browser (data layer)
                                          └──▶ Quintype config API (site structure)
```

---

## Running

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# .venv/bin/activate            # macOS/Linux
pip install -r requirements.txt
python -m playwright install chromium   # required for the Data Layer module
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- First startup downloads the official Schema.org vocabulary
  (`schemaorg-current-https.jsonld`) and caches it under `app/vocab/`.
- API docs: http://127.0.0.1:8000/docs

### Frontend (development)

```bash
cd frontend
npm install          # note: use `npm install --include=dev` if dev deps are omitted
npm run dev          # http://localhost:5173
```

### Frontend (production, served by FastAPI)

```bash
cd frontend
npm run build        # creates frontend/dist
# restart uvicorn; FastAPI serves the SPA at http://127.0.0.1:8000/
```

---

## API

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/scan` | Fetch + analyze up to 15 URLs (Technical SEO + Structured Data) |
| POST | `/api/structured-data/validate` | Structured Data validation for 1–15 URLs |
| POST | `/api/structured-data/validate-html` | Validate a raw HTML body |
| POST | `/api/data-layer/start` | Launch a persistent Chromium session, auto-inject the observer, open the URL; returns a `session_id` (browser stays open) |
| POST | `/api/data-layer/click` | Click a visible element by text (e.g. `Logout`) to trigger push events |
| POST | `/api/data-layer/click-element` | Click an element by selector/text and return rich element info |
| GET | `/api/data-layer/status?session_id=...` | Live session status (no event payload) |
| GET | `/api/data-layer/events?session_id=...` | Session status + full captured record history (seq, type, timestamp, url, data) |
| POST | `/api/data-layer/clear` | Clear captured history (browser localStorage + backend log); browser stays open |
| POST | `/api/data-layer/export` | Export the complete session as JSON (all metadata) |
| POST | `/api/data-layer/close` | Close the browser session and free resources |
| GET | `/api/analytics/status` | Whether the optional GA4 integration is configured (never fake data) |
| GET | `/api/analytics/overview` | GA4 overview (returns 503 config error until credentials/property are set) |
| GET | `/api/site-structure/config?site=deccanherald\|prajavani` | Quintype section tree |
| GET | `/api/vocab/status` | Schema.org vocabulary load status |
| GET | `/api/health` | Health check |

Every structured-data `finding` carries source metadata so the UI can jump to the
exact location:

```json
{
  "severity": "ERROR",
  "message": "Invalid property: id",
  "item_type": "Organization",
  "json_path": "0.publisher.id",
  "block_index": 0,
  "source": {
    "html_line": 5,
    "html_column": 4091,
    "start_offset": 4133,
    "end_offset": 4140,
    "json_line": 1,
    "json_column": 4087,
    "block_index": 0
  }
}
```

---

## Structured Data / Source Navigation (the defining feature)

```
URL → fetch → preserve ORIGINAL HTML → locate <script type="application/ld+json">
→ parse JSON while recording char/token positions → JSON-AST/source map
→ validate against the real Schema.org vocabulary → attach source range to finding
→ frontend: click error → source panel scrolls to exact line → property highlighted
```

- The **left panel** shows the complete original fetched HTML (CodeMirror, read-only,
  line numbers, syntax highlighting, scrollable) — JSON-LD stays at its original position.
- The **right panel** lists detected items (like validator.schema.org):
  `NewsMediaOrganization`, `NewsArticle`, `BreadcrumbList`, `Article`, `SiteNavigationElement`
  with per-item `0 ERRORS` counts.
- Clicking a finding switches focus to the source panel, scrolls to the exact line
  and **highlights the exact property/value range** using character offsets.
- Validation semantics:
  - `@context`, `@type`, `@id`, `@graph`, `@value` are JSON-LD keywords — never validated as properties.
  - Unknown **types** are reported honestly, never as a flood of property errors.
  - Unknown **properties** on a known type are errors (checked against the type's
    own properties *and* every ancestor type).
  - Value **ranges** are checked loosely, the way validator.schema.org behaves
    (ISO dates, numeric strings, URL references, and inheritance all pass).
  - Missing properties are never fabricated as errors.

### Schema.org vocabulary

The validator uses the **official Schema.org vocabulary** (1000+ types, 1600+ properties)
from `https://schema.org/version/latest/schemaorg-current-https.jsonld`, cached locally.
Type inheritance (`subClassOf`) and property domains/ranges come straight from the
vocabulary — nothing is hand-maintained, so new Schema.org additions keep working.

### Source mapping

The JSON-LD block locator + a cursor-based JSON scanner record exact line/column
and character offsets for **every property path** (`$.newsArticle.author.@type`),
including nested objects, arrays, `@graph`, and multiple blocks. Paths resolve
from findings to HTML source precisely.

---

## Data Layer

The Data Layer module **requires a real browser** (Playwright Chromium). A plain HTTP
request cannot see runtime `window.dataLayer`, so the backend holds a **persistent
browser session** per capture:

```
React ──▶ FastAPI ──▶ Playwright ──▶ real Chromium page ──▶ window.dataLayer
   ◀────────────────────────── events ──────────────────────────┘
```

Two capture streams are kept **strictly separate**:

1. **DATA LAYER events** — real `window.dataLayer.push(...)` calls. The observer
   hooks `push` **before any page script runs** (`add_init_script`), preserves the
   original `push` (site functionality is never broken), and records the EXACT
   pushed object (existing entries + future pushes, nested structure intact).
2. **USER INTERACTIONS** — clicks / scrolls / inputs / submits / page loads the user
   performs in the page. These are recorded as `interaction` records with rich
   element info (tag, text, id, class, href, role, aria-label...) — never presented
   as dataLayer events.

Workflow in the UI:

1. Enter a URL → **Start Capture** (launches Chromium, opens the page, browser stays
   open). Instrumentation is **automatic** — no manual logger script needed.
2. Interact with the site in the controlled browser: clicks, scrolls (throttled to
   meaningful positions: 25/50/75/90/100%), inputs, navigation. Each appears as a
   human-readable USER INTERACTION record ("User clicked \"Read More\"",
   "User scrolled to 50%"). If the site also fires `dataLayer.push(...)`, that
   appears separately as a DATA LAYER record.
3. **Dump Events** pulls the complete chronological timeline into the React UI
   (# / Time / Type / Event / URL, expandable rows showing the full JSON, search
   across event names/actions/URLs/JSON, filters for Data Layer / Interaction /
   Navigation / Click / Scroll / Page Load / Input / Submit). No DevTools needed.
4. **Clear History** wipes the application history (localStorage `dataLayerHistory`)
   and the backend session log without closing the browser — the next event starts a
   fresh timeline. **Export JSON** downloads the full session (`session_id`,
   `started_at`, all events across navigation). **Close Browser** closes the session
   — no orphan Chromium processes.
5. The timeline persists across navigation, re-renders and tab switches via
   application localStorage (`dataLayerHistory`). The backend session log remains
   the authoritative capture source; application localStorage is only a UI history
   cache, deduplicated by event identity so one real event never appears twice.

Events survive navigation, redirects and reloads: every record is stamped with an
ISO timestamp + URL and streamed to the **backend session log** (authoritative), so
the timeline stays complete across pages.

The status panel shows live state (`● Capturing`, current URL, `Events captured: N`,
`dataLayer detected: YES/NO`, `Capture: Listening/Stopped`, actual backend errors).

Example real capture from deccanherald.com: `gtm.js`, `gtm.dom`, `page_view` —
all with full expandable JSON.

## Google Analytics (optional, placeholder)

The manager asked whether GA data can be retrieved via a Python library. Yes — the
official client is **`google-analytics-data`**:

```python
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest

client = BetaAnalyticsDataClient()          # uses Application Default Credentials
response = client.run_report(RunReportRequest(
    property=f"properties/{property_id}",
    date_ranges=[DateRange(start_date="30daysAgo", end_date="today")],
    dimensions=[Dimension(name="pagePath")],
    metrics=[Metric(name="screenPageViews")],
))
```

To actually query GA4 data you need (all Google-side):
1. A GA4 property the authenticated account can access (e.g. Deccan Herald's).
2. The **Google Analytics Data API v1** enabled on the Google Cloud project.
3. Credentials via Application Default Credentials with the `analytics.readonly`
   scope (service-account JSON via `GOOGLE_APPLICATION_CREDENTIALS`, or
   `gcloud auth application-default login`).

This repo ships a **safe placeholder** — no hardcoded credentials, no fake data.
Set `GA_PROPERTY_ID` (and `GA_CREDENTIALS_PATH` or ADC) and the backend exposes:

- `GET /api/analytics/status` — configured or not
- `GET /api/analytics/overview` — active users / page views, 30 days
- `GET /api/analytics/events` — top events, 30 days
- `GET /api/analytics/pageviews` — top pages, 30 days

Until credentials + property access exist, these return a clear 503
configuration error — the app never claims GA data it cannot access.

## Security

The fetcher is **SSRF-guarded**: it blocks localhost, loopback, private (RFC 1918),
link-local, multicast, and reserved addresses — including DNS-rebinding cases where a
public hostname resolves to a blocked IP — and only allows `http`/`https` schemes.
Redirects are re-validated on every hop.

## Prajavani DataLayer QA Monitor

A standalone browser-side QA tool for **prajavani.net** that observes and validates
every `window.dataLayer` event against the **Paywall Data Layer specification**
(28 event variants), plus click→event matching, sequence validation
(`page_view/purchase/sign_up/login/logout → user_properties_update`), sessionStorage
persistence, and CSV/JSON export — in a floating draggable panel.

It ships as three installable options (console paste, bookmarklet, Tampermonkey
userscript) built from `frontend/src/qa/*` into `frontend/dist-qa/*`. It is a pure
**observer** — it never manufactures analytics events and never breaks the site's
`dataLayer.push`.

```
npm run build:qa     # rebuild dist-qa bundles
npm test             # includes 59 QA tests (validation engine + monitor behavior)
```

See `frontend/src/qa/README.md` for full usage instructions, supported events,
validation rules, and the documented source-spec inconsistencies.

## Tests

```bash
# Backend (43 tests)
cd backend
.venv\Scripts\python.exe -m pytest -q

# Frontend (3 tests)
cd frontend
npm run test
```

Coverage includes: extraction, multi-block + `@graph` + nested parsing, source mapping
(exact line/offset), Schema.org validation semantics, error grouping per item,
malformed-JSON isolation, SSRF blocking, Technical SEO analysis, Quintype tree building,
real network integration, and a real Playwright dataLayer capture.

## Known limitations

- The site-structure tree is built from the Quintype `sections` array; some parent/child
  edges flatten when the config references sections by id without nesting (350 nodes
  total on Deccan Herald, with correct primary hierarchy).
- The Data Layer capture runs a single page-load session with an optional click; it does
  not yet replay multi-step user journeys across many pages.
- The HTML source viewer loads the full page into the browser (up to 8 MB); very large
  pages may feel heavy — the source is served as a string in the scan response.
- Value-range checks are intentionally permissive to match validator.schema.org behavior;
  they surface as warnings, not errors.

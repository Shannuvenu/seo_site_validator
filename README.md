# SEO & Structured Data Health Check

A production-quality internal tool for auditing news websites (Deccan Herald, Prajavani)
with **two modules**:

1. **Technical SEO** — titles, meta, canonical, robots, headings, images, links, Open Graph, Twitter, hreflang.
2. **Structured Data** — real Schema.org validation (error → exact source location navigation)
   **plus** a separate Google Search structured-data eligibility layer based on Google's
   publicly documented rich-result requirements.

**No Streamlit. No paywall.**

---

## Architecture

```
project/
├── frontend/                 # React + TypeScript + Vite
│   ├── src/
│   │   ├── components/       # UrlInputBar, SourceViewer (CodeMirror), UrlSelector
│   │   ├── pages/            # TechnicalSeoPage, StructuredDataPage
│   │   ├── services/         # api.ts (REST client)
│   │   ├── types/            # backend models mirrored as TS types
│   │   └── styles/           # global.css + per-page css
│   └── vite.config.ts        # /api proxy → backend :8000
│
├── backend/                  # Python + FastAPI
│   ├── app/
│   │   ├── api/              # routes: scan, site-structure, vocab, analytics
│   │   ├── models/           # Pydantic response models
│   │   ├── parsers/          # sourceloc, extractor, sourcemap, normalizer, jsonld_parser
│   │   ├── validators/       # vocabulary (Schema.org vocab), schema_org,
│   │   │                     # google_rules (rule registry), google_search (eligibility validator)
│   │   ├── services/         # fetcher (SSRF-guarded), pipeline, technical_seo, site_structure
│   │   ├── vocab/            # cached schemaorg-current.jsonld (auto-downloaded once)
│   │   └── main.py
│   └── tests/                # pytest

└── README.md
```

```
React (Vite :5173) ──REST──▶ FastAPI (:8000) ──▶ async fetch (httpx)
                                          ├──▶ Schema.org vocab + validator
                                          ├──▶ Google Search eligibility validator
                                          ├──▶ Technical SEO analyzer
                                          └──▶ Quintype config API (site structure, backend-only)
```

> **Note:** the Data Layer inspection module (Playwright-based `window.dataLayer`
> capture) has been **removed as a product feature**. There is no Data Layer tab,
> page, route, or API endpoint any more. The unrelated `frontend/src/qa/*` bundle
> (a standalone browser-console QA script users paste into the *live production
> site's* console) is a separate distributable tool, not part of this app's UI,
> and was left untouched.

---

## Running

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# .venv/bin/activate            # macOS/Linux
pip install -r requirements.txt
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
| GET | `/api/analytics/status` | Whether the optional GA4 integration is configured (never fake data) |
| GET | `/api/analytics/overview` | GA4 overview (returns 503 config error until credentials/property are set) |
| GET | `/api/site-structure/config?site=deccanherald\|prajavani` | Quintype section tree (backend-only; not exposed as a UI tab) |
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

Each result's `structured_data.google` field carries the **separate** Google Search
eligibility report:

```json
{
  "google": {
    "items": [
      {
        "item_type": "Product",
        "support_status": "SUPPORTED",
        "rich_result_type": "Product snippet / Merchant listing",
        "eligible": false,
        "status": "FAIL",
        "errors": 1,
        "warnings": 3
      }
    ],
    "findings": [
      {
        "severity": "ERROR",
        "category": "GOOGLE_SEARCH_ERROR",
        "code": "GOOGLE_ONE_OF_MISSING",
        "message": "Either \"offers\", \"review\" or \"aggregateRating\" should be specified for the Product snippet / Merchant listing rich result."
      }
    ]
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

## Google Search structured-data eligibility

Schema.org validity and Google Search eligibility are **deliberately kept separate**.
A Schema.org-valid item is not automatically eligible for a Google Search rich result,
and this tool never claims to reproduce Google's proprietary internal ranking/eligibility
algorithm — only its publicly documented structured-data requirements
(https://developers.google.com/search/docs/appearance/structured-data).

```
Schema.org-valid items
        │
        ▼
GoogleSearchValidator (backend/app/validators/google_search.py)
        │  looks up the item's type in the rule registry
        ▼
backend/app/validators/google_rules.py  ← single source of truth
        │
        ├── SUPPORTED    → required / required-one-of / recommended / format checks
        ├── DEPRECATED   → Google publicly retired this rich result (dated explanation,
        │                  no error/warning noise generated)
        ├── NOT_SUPPORTED→ valid Schema.org type, but never was a Google Search feature
        └── UNKNOWN      → the Schema.org type itself isn't recognised
```

- Findings are tagged `GOOGLE_SEARCH_ERROR` / `GOOGLE_SEARCH_WARNING` and kept in a
  separate list (`structured_data.google.findings`) from Schema.org's
  `structured_data.findings` — the two are never merged into one generic list.
- Currently registered rich-result types: Article/NewsArticle/BlogPosting, Product,
  Recipe, BreadcrumbList, JobPosting, Event, VideoObject, LocalBusiness, Organization
  (logo), SoftwareApplication, Review, WebSite (sitelinks search box).
- Explicitly marked **deprecated** (not silently validated as if still live): FAQPage
  (FAQ rich results ended for all sites 2026-05-07), HowTo (deprecated 2023-09),
  ClaimReview and SpecialAnnouncement (retired 2025-06).
- To add a new Google-supported type, add one `GoogleTypeRule` entry to
  `GOOGLE_TYPE_RULES` in `google_rules.py` — nothing else needs to change.
- Format/value checks (`google_rules.PropertyFormat`) are intentionally
  non-aggressive (URL/date/datetime/number/price/image shape only) and findings
  derived from them are marked `heuristic=True` where they go beyond a literal
  "field is present" check from Google's docs.

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
# Backend
cd backend
.venv\Scripts\python.exe -m pytest -q

# Frontend
cd frontend
npm run test
```

Backend coverage includes: extraction, multi-block + `@graph` + nested parsing, source
mapping (exact line/offset), Schema.org validation semantics, error grouping per item,
malformed-JSON isolation, SSRF blocking, Technical SEO analysis, Quintype tree building,
real network integration, and the Google Search eligibility layer (required /
required-one-of / recommended fields, deprecated-type handling, Schema.org-vs-Google
separation, per-item error+warning coexistence, source location, overview counts).

## Known limitations

- The site-structure tree is built from the Quintype `sections` array; some parent/child
  edges flatten when the config references sections by id without nesting (350 nodes
  total on Deccan Herald, with correct primary hierarchy). The Site Structure feature
  remains available as a backend API for internal tooling but is not exposed as a UI tab.
- The HTML source viewer loads the full page into the browser (up to 8 MB); very large
  pages may feel heavy — the source is served as a string in the scan response.
- Schema.org value-range checks are intentionally permissive to match validator.schema.org
  behavior; they surface as warnings, not errors.
- The Google Search eligibility layer implements the publicly documented required /
  recommended property lists for a curated set of common rich-result types (see
  `backend/app/validators/google_rules.py`); it is not an exhaustive reproduction of
  every Google Search feature, and it never claims to replicate Google's proprietary
  ranking/eligibility algorithm.

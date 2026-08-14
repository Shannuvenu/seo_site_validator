"""Shared Pydantic models returned by the API.

One strongly-typed result model per module so the frontend has a single
contract. Findings always carry source-location metadata (block, JSON path,
HTML line/column, character offsets) so the UI can jump the source viewer to
the exact property that caused the finding.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["ERROR", "WARNING", "INFO"]


class SourceLocation(BaseModel):
    """Exact location of a JSON-LD property/value inside the ORIGINAL HTML."""

    html_line: int = 0
    html_column: int = 0
    start_offset: Optional[int] = None  # char offset in original HTML
    end_offset: Optional[int] = None
    json_path: Optional[str] = None  # e.g. $.newsArticle.author.@type
    json_line: Optional[int] = None  # line within the JSON-LD script text
    json_column: Optional[int] = None
    block_index: Optional[int] = None
    script_line: Optional[int] = None  # line of the <script ...> tag


class ValidationFinding(BaseModel):
    """One Schema.org validation finding, grouped to a specific item.

    ``error_code`` mirrors the official validator.schema.org error taxonomy
    (e.g. INVALID_PREDICATE / UNKNOWN_FIELD, MISSING_FIELD, INVALID_ITEMTYPE).
    ``item_type`` / ``item_index`` always reference a TOP-LEVEL detected item
    (the one the error belongs to), so per-item counts and the global count are
    computed from the same findings (single source of truth).
    """

    id: str
    severity: Severity
    message: str
    error_code: Optional[str] = None
    detail: Optional[str] = None
    item_type: Optional[str] = None  # top-level Schema.org type the error belongs to
    item_index: Optional[int] = None
    block_index: int = 0
    json_path: Optional[str] = None
    property: Optional[str] = None
    expected: Optional[str] = None  # what the validator expected (for display)
    actual: Optional[str] = None  # what was actually provided (for display)
    source: Optional[SourceLocation] = None


class DetectedItem(BaseModel):
    """One detected Schema.org entity in the page."""

    type: str
    id: Optional[str] = None
    index: int = 0
    block_index: int = 0
    json_path: str = ""
    errors: int = 0
    warnings: int = 0
    infos: int = 0
    status: Literal["PASS", "WARN", "FAIL"] = "PASS"
    properties: List[str] = Field(default_factory=list)  # property names found on the item
    source_start_line: int = 0
    source_end_line: int = 0
    source_start_offset: Optional[int] = None
    source_end_offset: Optional[int] = None


class JsonLdBlock(BaseModel):
    """One extracted <script type="application/ld+json"> block."""

    index: int = 0
    parsed: bool = False
    malformed: bool = False
    error: Optional[str] = None
    error_detail: Optional[str] = None
    entities: List[DetectedItem] = Field(default_factory=list)
    raw: Optional[Any] = None  # parsed JSON payload (needed for validation walks)
    html_start_line: int = 0
    html_end_line: int = 0
    text_start_line: int = 0
    json_error_line: Optional[int] = None
    json_error_column: Optional[int] = None


class StructuredDataResult(BaseModel):
    """Everything the Structured Data module computed for one URL."""

    status: Literal["PASS", "WARN", "FAIL", "SKIPPED", "UNKNOWN"] = "UNKNOWN"
    item_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    blocks: List[JsonLdBlock] = Field(default_factory=list)
    items: List[DetectedItem] = Field(default_factory=list)
    findings: List[ValidationFinding] = Field(default_factory=list)


class TechnicalSeoFinding(BaseModel):
    """One technical-SEO check result."""

    category: str = "general"
    name: str
    severity: Severity = "INFO"
    message: str
    detail: Optional[str] = None


class TechnicalSeoResult(BaseModel):
    """Full Technical SEO output for one URL."""

    url: str = ""
    final_url: str = ""
    status_code: int = 0
    content_type: str = ""
    fetch_duration_ms: float = 0.0
    title: Optional[str] = None
    title_length: Optional[int] = None
    meta_description: Optional[str] = None
    meta_description_length: Optional[int] = None
    canonical: Optional[str] = None
    robots_meta: Optional[str] = None
    robots_directives: List[str] = Field(default_factory=list)
    viewport: Optional[str] = None
    h1: List[str] = Field(default_factory=list)
    h2: List[str] = Field(default_factory=list)
    h3: List[str] = Field(default_factory=list)
    image_count: int = 0
    images_missing_alt: int = 0
    link_count: int = 0
    internal_links: int = 0
    external_links: int = 0
    broken_anchors: int = 0
    og_tags: Dict[str, str] = Field(default_factory=dict)
    twitter_tags: Dict[str, str] = Field(default_factory=dict)
    hreflang_tags: List[str] = Field(default_factory=list)
    canonical_https: bool = True
    has_jsonld: bool = False
    structured_data_blocks: int = 0
    findings: List[TechnicalSeoFinding] = Field(default_factory=list)


class UrlScanStatus(BaseModel):
    """Per-URL status inside a multi-URL scan."""

    url: str
    status: Literal["ok", "fetch_error", "skipped"] = "ok"
    error: Optional[str] = None
    detail: Optional[str] = None


class UrlScanResult(BaseModel):
    """Full scan output for ONE URL."""

    url: str
    final_url: str = ""
    status_code: int = 0
    content_type: str = ""
    fetch_duration_ms: float = 0.0
    fetch_error: Optional[str] = None
    fetch_error_type: Optional[str] = None
    technical_seo: Optional[TechnicalSeoResult] = None
    structured_data: Optional[StructuredDataResult] = None
    html: Optional[str] = None  # full original HTML, for the source viewer
    html_size: Optional[int] = None


class ScanRequest(BaseModel):
    """Request body for a scan of 1..N URLs."""

    urls: List[str] = Field(min_length=1, max_length=15)
    include_html: bool = True
    timeout_seconds: Optional[float] = None


class ScanResponse(BaseModel):
    """Multi-URL scan response: one result per URL, independent of the others."""

    results: List[UrlScanResult]
    scan_id: str = ""


class DataLayerRecord(BaseModel):
    """One captured event in a dataLayer session.

    Two capture streams, never mixed:

    - ``type == "dataLayer"``    — a REAL ``window.dataLayer.push(...)`` call;
      ``data`` is the EXACT object that was pushed (source: existing|push).
    - ``type == "interaction"``  — something the user did in the page
      (click / scroll / input / change / submit / page_load / pointer); ``data``
      holds the action + element info. This is an OBSERVED interaction, NOT a
      dataLayer event.
    - ``type == "navigation"``   — the page navigated / reloaded / redirected;
      ``data`` holds from_url / to_url.

    ``page_title`` is captured at event time so the timeline can show which
    page an event happened on even after the browser navigated away.
    """

    seq: int = 0
    type: Literal["dataLayer", "interaction", "navigation", "page"] = "dataLayer"
    timestamp: Optional[str] = None  # ISO timestamp
    url: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)
    page_title: Optional[str] = None


class DataLayerResult(BaseModel):
    """Full dataLayer inspection output for one URL."""

    url: str
    final_url: str = ""
    data_layer_found: bool = False
    declared_before_load: bool = False
    existing_events: List[DataLayerRecord] = Field(default_factory=list)
    pushed_events: List[DataLayerRecord] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    page_title: Optional[str] = None
    local_storage_events: int = 0
    duration_ms: float = 0.0


class DataLayerStartRequest(BaseModel):
    """Request body to start a persistent browser dataLayer capture session."""

    url: str
    navigation_pause_ms: Optional[int] = Field(default=2500, ge=0, le=15000)
    click_text: Optional[str] = None
    click_selector: Optional[str] = None
    headless: Optional[bool] = True


class DataLayerStartResponse(BaseModel):
    """A started browser session."""

    session_id: str
    url: str
    status: str = "starting"


class DataLayerClickRequest(BaseModel):
    """Request body to click a visible element by its text in the live page."""

    session_id: str = ""
    text: str = Field(min_length=1)


class DataLayerClickResponse(BaseModel):
    """Outcome of the automated click."""

    session_id: str
    clicked: bool = True
    message: str = ""


class DataLayerClickElementRequest(BaseModel):
    """Request body to click an element via selector / text in the live page."""

    session_id: str = ""
    selector: Optional[str] = None
    text: Optional[str] = None


class DataLayerClickElementResponse(BaseModel):
    """Result of clicking an element: whether it worked plus element info."""

    session_id: str
    clicked: bool = False
    message: str = ""
    element: Optional[Dict[str, Any]] = None


class DataLayerClearRequest(BaseModel):
    """Request body to clear the captured event history."""

    session_id: str = ""


class DataLayerCloseRequest(BaseModel):
    """Request body to close the browser session."""

    session_id: str = ""


class DataLayerStatusResponse(BaseModel):
    """Live browser-session status + captured records."""

    session_id: str
    status: str = "not_started"  # starting | open | capturing | error | closed
    url: str = ""
    current_url: str = ""
    page_title: Optional[str] = None
    data_layer_found: bool = False
    instrumented: bool = False
    events: List[DataLayerRecord] = Field(default_factory=list)
    event_count: int = 0
    started_at: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


class DataLayerExportResponse(BaseModel):
    """Complete capture session as JSON (export / download)."""

    session_id: str
    started_at: Optional[str] = None
    url: str = ""
    current_url: str = ""
    page_title: Optional[str] = None
    data_layer_found: bool = False
    events: List[DataLayerRecord] = Field(default_factory=list)
    event_count: int = 0


class SiteNode(BaseModel):
    """One node of the Quintype section tree."""

    section_id: str = ""
    name: str = ""
    slug: str = ""
    parent_id: Optional[str] = None
    children: List["SiteNode"] = Field(default_factory=list)
    collection_type: Optional[str] = None
    display_name: Optional[str] = None


class SiteStructureResult(BaseModel):
    """Section tree for a Quintype site."""

    site: str = ""
    config_url: str = ""
    root: Optional[SiteNode] = None
    nodes: List[SiteNode] = Field(default_factory=list)
    node_count: int = 0
    error: Optional[str] = None
    fetched_at: Optional[str] = None


SiteNode.model_rebuild()


class HealthResponse(BaseModel):
    status: str = "ok"
    backend: str = "fastapi"
    version: str = "1.0.0"

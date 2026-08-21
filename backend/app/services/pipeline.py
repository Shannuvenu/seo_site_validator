"""Structured Data pipeline: fetch -> extract -> source map -> normalize -> validate."""
from __future__ import annotations

import asyncio
import traceback
from typing import Any, Dict, List, Optional

from ..models.schemas import StructuredDataResult, UrlScanResult
from ..parsers.extractor import ExtractedBlock, JsonLdExtractor
from ..parsers.normalizer import JsonLdNormalizer
from ..parsers.sourcemap import SourceMap
from ..validators.google_search import GoogleSearchValidator
from ..validators.schema_org import SchemaOrgValidator
from .fetcher import Fetcher
from .technical_seo import TechnicalSeoAnalyzer


def analyze_structured_data(html: str, source_map: Optional[SourceMap] = None) -> StructuredDataResult:
    """Run the full structured-data analysis over raw HTML (synchronous).

    Pipeline: extract -> source map -> normalize -> Schema.org validation ->
    Google Search eligibility validation (a SEPARATE layer built on top of,
    never instead of, Schema.org validity — see validators/google_search.py).
    """
    extractor = JsonLdExtractor()
    blocks = extractor.extract(html)
    sm = source_map or SourceMap().build(html)
    normalizer = JsonLdNormalizer()
    block_models = normalizer.normalize_blocks(blocks, sm)
    validator = SchemaOrgValidator()
    result = validator.validate(block_models, sm)
    result.google = GoogleSearchValidator().validate(result.blocks, result.items, sm)
    return result


async def scan_urls(
    urls: List[str],
    include_html: bool = True,
    timeout_seconds: Optional[float] = None,
    max_concurrent: int = 5,
) -> List[UrlScanResult]:
    """Scan many URLs concurrently; one failure never blocks the others."""
    sem = asyncio.Semaphore(max_concurrent)

    async def one(url: str) -> UrlScanResult:
        async with sem:
            return await scan_one(url, include_html=include_html, timeout_seconds=timeout_seconds)

    return list(await asyncio.gather(*(one(u) for u in urls)))


async def scan_one(
    url: str,
    include_html: bool = True,
    timeout_seconds: Optional[float] = None,
) -> UrlScanResult:
    """Scan a single URL end-to-end."""
    result = UrlScanResult(url=url)
    try:
        async with Fetcher(timeout_seconds=timeout_seconds or 20.0) as fetcher:
            fetched = await fetcher.fetch(url)
    except Exception as exc:  # noqa: BLE001 - network errors become fetch_error
        result.fetch_error = str(exc)
        result.fetch_error_type = getattr(exc, "error_type", "fetch_error")
        result.status_code = 0
        return result

    html = fetched["content"]
    result.final_url = fetched["final_url"]
    result.status_code = fetched["status_code"]
    result.content_type = fetched["content_type"]
    result.fetch_duration_ms = fetched["fetch_duration_ms"]
    result.html_size = len(html)

    if result.status_code >= 400:
        result.fetch_error = f"HTTP {result.status_code} returned by server."
        result.fetch_error_type = "http_error"
        return result

    # Build the source map once, share it between SEO and structured data.
    source_map = SourceMap().build(html)

    # NOTE: analysis failures are caught per-stage so one broken page (odd
    # markup, an analyzer edge case) never turns into a blank 500 for the
    # whole /scan request - the URL still comes back with everything that DID
    # succeed, plus a clear fetch_error describing what failed and why.
    try:
        result.technical_seo = TechnicalSeoAnalyzer().analyze(
            html=html,
            url=url,
            final_url=result.final_url,
            status_code=result.status_code,
            content_type=result.content_type,
            fetch_duration_ms=result.fetch_duration_ms,
        )
    except Exception as exc:  # noqa: BLE001 - never let one analyzer kill the scan
        print(f"[technical_seo] {url}: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        result.fetch_error = f"Technical SEO analysis failed: {type(exc).__name__}: {exc}"
        result.fetch_error_type = "analysis_error"

    try:
        result.structured_data = analyze_structured_data(html, source_map=source_map)
    except Exception as exc:  # noqa: BLE001 - never let one analyzer kill the scan
        print(f"[structured_data] {url}: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        prefix = f"{result.fetch_error} | " if result.fetch_error else ""
        result.fetch_error = f"{prefix}Structured data analysis failed: {type(exc).__name__}: {exc}"
        result.fetch_error_type = result.fetch_error_type or "analysis_error"

    if include_html:
        result.html = html
    return result
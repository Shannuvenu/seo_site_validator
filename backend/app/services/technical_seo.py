"""Technical SEO analysis service.

Separate module from Structured Data: no Schema.org findings here. Checks cover
title/meta/canonical/robots, headings, images, links, Open Graph, Twitter cards,
hreflang, and indexability signals.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from ..models.schemas import TechnicalSeoFinding, TechnicalSeoResult

MAX_H_COUNT = 30
ROBOT_DIRECTIVE_RE = re.compile(r"\b(noindex|nofollow|noarchive|nosnippet|noimageindex|index|follow)\b", re.I)


def _normalize_url(base: str, href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    href = href.strip()
    if not href:
        return None
    if href.startswith(("javascript:", "mailto:", "tel:", "data:", "#")):
        return None
    try:
        return urljoin(base, href)
    except Exception:  # noqa: BLE001
        return None


class TechnicalSeoAnalyzer:
    """Runs technical-SEO checks over fetched HTML."""

    def analyze(self, html: str, url: str, final_url: str, status_code: int, content_type: str, fetch_duration_ms: float) -> TechnicalSeoResult:
        soup = BeautifulSoup(html, "lxml")
        result = TechnicalSeoResult(
            url=url,
            final_url=final_url or url,
            status_code=status_code,
            content_type=content_type,
            fetch_duration_ms=fetch_duration_ms,
        )
        findings: List[TechnicalSeoFinding] = []

        title_tag = soup.find("title")
        if title_tag and title_tag.get_text(strip=True):
            result.title = title_tag.get_text(strip=True)
            result.title_length = len(result.title)
            if result.title_length > 60:
                findings.append(
                    TechnicalSeoFinding(
                        name="Title length",
                        severity="WARNING",
                        message=f"Title is {result.title_length} characters (recommended max ~60).",
                        detail=result.title,
                    )
                )
            elif result.title_length < 20:
                findings.append(
                    TechnicalSeoFinding(
                        name="Title length",
                        severity="WARNING",
                        message=f"Title is only {result.title_length} characters (recommended min ~20).",
                        detail=result.title,
                    )
                )
        else:
            findings.append(
                TechnicalSeoFinding(name="Title", severity="ERROR", message="Missing <title> tag.", detail="The page has no <title> element.")
            )

        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content", "").strip():
            result.meta_description = meta_desc["content"].strip()
            result.meta_description_length = len(result.meta_description)
            if result.meta_description_length > 160:
                findings.append(
                    TechnicalSeoFinding(
                        name="Meta description length",
                        severity="WARNING",
                        message=f"Meta description is {result.meta_description_length} characters (recommended max ~160).",
                    )
                )
        else:
            findings.append(
                TechnicalSeoFinding(name="Meta description", severity="WARNING", message="Missing meta description.")
            )

        canonical = soup.find("link", rel=lambda r: r and "canonical" in r.lower())
        if canonical and canonical.get("href"):
            result.canonical = canonical["href"].strip()
            if not result.canonical.startswith("https://"):
                findings.append(
                    TechnicalSeoFinding(
                        name="Canonical",
                        severity="WARNING",
                        message="Canonical URL is not HTTPS.",
                        detail=result.canonical,
                    )
                )
        else:
            findings.append(
                TechnicalSeoFinding(name="Canonical", severity="WARNING", message="No canonical URL declared.")
            )

        robots = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
        if robots and robots.get("content"):
            result.robots_meta = robots["content"].strip()
            result.robots_directives = [d.lower() for d in ROBOT_DIRECTIVE_RE.findall(result.robots_meta)]
            if "noindex" in result.robots_directives:
                findings.append(
                    TechnicalSeoFinding(
                        name="Robots",
                        severity="WARNING",
                        message="Page is marked noindex (will not appear in search results).",
                        detail=result.robots_meta,
                    )
                )
        else:
            result.robots_directives = ["index", "follow"]
            findings.append(
                TechnicalSeoFinding(
                    name="Robots",
                    severity="INFO",
                    message="No robots meta tag found; default index,follow assumed.",
                )
            )

        viewport = soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)})
        if viewport and viewport.get("content"):
            result.viewport = viewport["content"].strip()
        else:
            findings.append(
                TechnicalSeoFinding(name="Viewport", severity="WARNING", message="Missing viewport meta tag.")
            )

        # Headings
        h1s, h2s, h3s = [], [], []
        for h in soup.find_all(["h1", "h2", "h3"])[: MAX_H_COUNT * 3]:
            text = h.get_text(" ", strip=True)
            if h.name == "h1":
                h1s.append(text)
            elif h.name == "h2":
                h2s.append(text)
            else:
                h3s.append(text)
        result.h1, result.h2, result.h3 = h1s[:MAX_H_COUNT], h2s[:MAX_H_COUNT], h3s[:MAX_H_COUNT]
        if not h1s:
            findings.append(TechnicalSeoFinding(name="H1", severity="WARNING", message="No <h1> heading found."))
        elif len(h1s) > 1:
            findings.append(
                TechnicalSeoFinding(
                    name="H1",
                    severity="WARNING",
                    message=f"Multiple <h1> headings found ({len(h1s)}).",
                    detail="; ".join(h1s[:5]),
                )
            )

        # Images
        images = soup.find_all("img")
        result.image_count = len(images)
        missing_alt = [img for img in images if not img.get("alt")]
        result.images_missing_alt = len(missing_alt)
        if missing_alt:
            findings.append(
                TechnicalSeoFinding(
                    name="Images",
                    severity="WARNING",
                    message=f"{len(missing_alt)} of {len(images)} images are missing alt text.",
                )
            )
        elif images:
            findings.append(
                TechnicalSeoFinding(name="Images", severity="INFO", message=f"All {len(images)} images have alt text.")
            )

        # Links
        links = soup.find_all("a", href=True)
        result.link_count = len(links)
        internal, external = 0, 0
        broken_anchors = 0
        parsed_final = urlparse(final_url or url)
        base_domain = parsed_final.netloc.lower()
        for a in links:
            href = a["href"].strip()
            if href.startswith("#"):
                broken_anchors += 1
                continue
            full = _normalize_url(final_url or url, href)
            if not full:
                continue
            if href.startswith(("http://", "https://")):
                if urlparse(href).netloc.lower() == base_domain:
                    internal += 1
                else:
                    external += 1
            else:
                internal += 1
        result.internal_links, result.external_links = internal, external
        result.broken_anchors = broken_anchors

        # Open Graph
        for meta in soup.find_all("meta", attrs={"property": True}):
            prop = meta.get("property", "").strip().lower()
            if prop.startswith("og:"):
                result.og_tags[prop] = meta.get("content", "").strip()
        # Twitter
        for meta in soup.find_all("meta", attrs={"name": True}):
            name = meta.get("name", "").strip().lower()
            if name.startswith("twitter:"):
                result.twitter_tags[name] = meta.get("content", "").strip()
        if not result.og_tags:
            findings.append(
                TechnicalSeoFinding(name="Open Graph", severity="WARNING", message="No Open Graph tags detected.")
            )
        if not result.twitter_tags:
            findings.append(
                TechnicalSeoFinding(name="Twitter Card", severity="INFO", message="No Twitter Card metadata detected.")
            )

        # hreflang
        hreflangs = soup.find_all("link", attrs={"hreflang": True})
        for h in hreflangs:
            if h.get("href"):
                result.hreflang_tags.append(f'{h.get("hreflang")}: {h["href"]}')

        # JSON-LD presence (informational, not Schema.org validation)
        ld = soup.find_all("script", attrs={"type": re.compile("application/ld\\+json", re.I)})
        result.structured_data_blocks = len(ld)
        result.has_jsonld = len(ld) > 0

        # HTTPS check
        if final_url and not final_url.startswith("https://"):
            findings.append(
                TechnicalSeoFinding(name="HTTPS", severity="ERROR", message="Page is served over HTTP, not HTTPS.", detail=final_url)
            )
            result.canonical_https = False

        result.findings = findings
        return result

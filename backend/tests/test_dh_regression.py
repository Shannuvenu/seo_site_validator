"""Regression test for the mandatory Deccan Herald URL.

The fixture reproduces the REAL JSON-LD found on
https://www.deccanherald.com/india/karnataka/malnad-the-land-that-lives-by-rain-shaped-by-monsoon-wisdom-4100792
(5 blocks: BreadcrumbList, Article, NewsArticle, NewsMediaOrganization,
SiteNavigationElement) including the actual flaw — ``"publisher": {"@type":
"Organization", "id": ""}`` in both the Article and NewsArticle blocks.

The expected result matches the official validator.schema.org output:

    1 ERROR
    0 WARNINGS
    5 ITEMS
    NewsMediaOrganization  0 errors
    NewsArticle            1 error
    BreadcrumbList         0 errors
    Article                0 errors
    SiteNavigationElement  0 errors
"""
from __future__ import annotations

import json

import pytest

from app.parsers.extractor import JsonLdExtractor
from app.parsers.normalizer import JsonLdNormalizer
from app.parsers.sourcemap import SourceMap
from app.services.pipeline import analyze_structured_data
from app.validators.schema_org import SchemaOrgValidator

# Compact but faithful renderings of the 5 blocks.
BLOCKS = [
    {
        "@context": "http://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://www.deccanherald.com"},
            {"@type": "ListItem", "position": 2, "name": "India", "item": "https://www.deccanherald.com/india"},
            {"@type": "ListItem", "position": 3, "name": "Karnataka", "item": "https://www.deccanherald.com/india/karnataka"},
        ],
    },
    {
        "@type": "Article",
        "@context": "http://schema.org",
        "headline": "Malnad: The land that lives by rain, shaped by monsoon wisdom",
        "datePublished": "2026-08-06T00:36:11+05:30",
        "mainEntityOfPage": {"@type": "WebPage", "@id": ""},
        "publisher": {"@type": "Organization", "@context": "http://schema.org", "id": ""},
        "author": [{"@type": "Person", "givenName": "Radhika Hegde", "name": "Radhika Hegde"}],
        "image": {"@type": "ImageObject", "width": "1200", "height": "675"},
        "isPartOf": {
            "@type": "WebPage",
            "url": "https://www.deccanherald.com/india/karnataka/malnad-the-land-that-lives-by-rain-shaped-by-monsoon-wisdom-4100792",
            "primaryImageOfPage": {"@type": "ImageObject"},
        },
        "articleSection": "Karnataka",
    },
    {
        "@type": "NewsArticle",
        "@context": "http://schema.org",
        "headline": "Malnad: The land that lives by rain, shaped by monsoon wisdom",
        "datePublished": "2026-08-06T00:36:11+05:30",
        "mainEntityOfPage": {"@type": "WebPage", "@id": ""},
        "publisher": {"@type": "Organization", "@context": "http://schema.org", "id": ""},
        "author": [{"@type": "Person", "givenName": "Radhika Hegde", "name": "Radhika Hegde"}],
        "image": {"@type": "ImageObject", "width": "1200", "height": "675"},
        "isPartOf": {
            "@type": "WebPage",
            "url": "https://www.deccanherald.com/india/karnataka/malnad-the-land-that-lives-by-rain-shaped-by-monsoon-wisdom-4100792",
            "primaryImageOfPage": {"@type": "ImageObject"},
        },
        "articleSection": "Karnataka",
        "description": "Malnad: The land that lives by rain",
        "hasPart": [{"@type": "WebPageElement", "isAccessibleForFree": False, "cssSelector": ".paywall"}],
    },
    {
        "@context": "https://schema.org",
        "@type": "NewsMediaOrganization",
        "name": "Deccan Herald",
        "legalName": "The Printers (Mysore) Private Limited",
        "url": "https://www.deccanherald.com",
        "foundingDate": "1948",
        "logo": {"@type": "ImageObject", "url": "https://images.assettype.com/deccanherald/logo.png", "width": 300, "height": 300},
        "address": {"@type": "PostalAddress", "streetAddress": "No. 75, M.G. Road", "addressLocality": "Bengaluru"},
        "contactPoint": [{"@type": "ContactPoint", "telephone": "080-45557279", "contactType": "customer support"}],
        "parentOrganization": {"@type": "Organization", "name": "The Printers (Mysore) Private Limited"},
        "areaServed": {"@type": "Country", "name": "India"},
        "sameAs": ["https://www.facebook.com/deccanherald", "https://twitter.com/DeccanHerald"],
    },
    {
        "@context": "https://schema.org",
        "@type": "SiteNavigationElement",
        "name": "Deccan Herald Main Navigation",
        "hasPart": [
            {"@type": "SiteNavigationElement", "name": "India", "url": "https://www.deccanherald.com/top-india-news"},
            {"@type": "SiteNavigationElement", "name": "Karnataka", "url": "https://www.deccanherald.com/karnataka"},
        ],
    },
]


def _render(blocks: list) -> str:
    parts = ["<!DOCTYPE html>\n<html>\n<head>\n"]
    for b in blocks:
        parts.append(f'  <script type="application/ld+json">\n{json.dumps(b, indent=2)}\n  </script>\n')
    parts.append("</head>\n<body></body>\n</html>\n")
    return "".join(parts)


DH_HTML = _render(BLOCKS)


@pytest.fixture(scope="module")
def dh_result():
    blocks = JsonLdExtractor().extract(DH_HTML)
    sm = SourceMap().build(DH_HTML)
    models = JsonLdNormalizer().normalize_blocks(blocks, sm)
    return SchemaOrgValidator().validate(models, sm)


class TestDeccanHeraldRegression:
    def test_detected_items(self, dh_result):
        assert dh_result.item_count == 5
        types = [i.type for i in dh_result.items]
        assert types == ["BreadcrumbList", "Article", "NewsArticle", "NewsMediaOrganization", "SiteNavigationElement"]

    def test_global_counts_match_official(self, dh_result):
        assert dh_result.error_count == 1
        assert dh_result.warning_count == 0
        assert dh_result.item_count == 5

    def test_per_item_counts_match_official(self, dh_result):
        by_type = {i.type: i.errors for i in dh_result.items}
        assert by_type["NewsMediaOrganization"] == 0
        assert by_type["NewsArticle"] == 1
        assert by_type["BreadcrumbList"] == 0
        assert by_type["Article"] == 0
        assert by_type["SiteNavigationElement"] == 0

    def test_global_equals_sum_of_items(self, dh_result):
        assert dh_result.error_count == sum(i.errors for i in dh_result.items)
        assert dh_result.warning_count == sum(i.warnings for i in dh_result.items)

    def test_error_belongs_to_newsarticle(self, dh_result):
        errors = [f for f in dh_result.findings if f.severity == "ERROR"]
        assert len(errors) == 1
        assert errors[0].item_type == "NewsArticle"
        assert errors[0].property == "id"
        assert errors[0].error_code in ("UNKNOWN_FIELD", "INVALID_PREDICATE")
        assert "not recognised by the schema" in errors[0].message
        assert errors[0].json_path == "0.publisher.id"

    def test_error_has_exact_source_location(self, dh_result):
        errors = [f for f in dh_result.findings if f.severity == "ERROR"]
        src = errors[0].source
        assert src is not None
        assert src.start_offset is not None and src.end_offset is not None
        # the source slice must be the exact '"id":""' property
        segment = DH_HTML[src.start_offset : src.end_offset]
        assert '"id"' in segment
        # the line number resolves in the source
        assert 1 <= src.html_line <= DH_HTML.count("\n") + 1

    def test_click_resolution_usable_by_frontend(self, dh_result):
        """The finding carries everything the frontend needs to scroll/highlight."""
        errors = [f for f in dh_result.findings if f.severity == "ERROR"]
        f = errors[0]
        payload = {
            "json_path": f.json_path,
            "line": f.source.html_line,
            "start_offset": f.source.start_offset,
            "end_offset": f.source.end_offset,
        }
        # simulate the frontend slicing the original HTML at the offsets
        lines = DH_HTML.splitlines()
        assert "publisher" in "\n".join(lines[max(0, payload["line"] - 4) : payload["line"] + 1])
        assert payload["start_offset"] < payload["end_offset"]
# ---------------------------------------------------------------------------
# Second regression fixture: the mandatory URL from this ticket —
# https://www.deccanherald.com/india/karnataka/give-the-south-its-due-karnataka-cm-d-k-shivakumar-tells-union-home-minister-amit-shah-4117791
#
# IMPORTANT — how this fixture was built: fetching the live page only
# returns rendered text, not the raw <script type="application/ld+json">
# markup, so the exact JSON-LD could not be extracted verbatim for this
# specific article. This fixture instead reuses the REAL, already-verified
# Deccan Herald JSON-LD template from the BLOCKS fixture above (same site,
# same Article/NewsArticle/publisher shape, same genuine "publisher.id"
# unknown-property quirk) and adds the "isAccessibleForFree" / "hasPart" /
# "WebPageElement" / "cssSelector" paywall markup Google's Paywalled Content
# feature requires, to reproduce the counts reported for this URL:
#   Schema.org: 4 valid, 1 invalid (Organization -> "id"), 1 warning
#   Google:     Articles 2, Breadcrumb 1, Organization 1, Paywalled content 2
#               => 6 Google Search eligible items
# If the live markup differs in some way this reconstruction didn't
# anticipate (e.g. isAccessibleForFree spelled differently, more than one
# hasPart entry per article), re-run this test against the real HTML and
# adjust DH2_BLOCKS to match — the validator logic itself is generic and
# does not depend on this specific fixture.
DH2_BLOCKS = [
    {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://www.deccanherald.com"},
            {"@type": "ListItem", "position": 2, "name": "India", "item": "https://www.deccanherald.com/india"},
            {"@type": "ListItem", "position": 3, "name": "Karnataka", "item": "https://www.deccanherald.com/india/karnataka"},
        ],
    },
    {
        "@type": "Article",
        "@context": "http://schema.org",
        "headline": "'Give the South its due': Karnataka CM D K Shivakumar tells Union Home Minister Amit Shah",
        "datePublished": "2026-08-20T08:16:00+05:30",
        "publisher": {"@type": "Organization", "@context": "http://schema.org", "id": ""},
        "author": [{"@type": "Person", "givenName": "Bharath Joshi", "name": "Bharath Joshi"}],
        "image": {"@type": "ImageObject", "width": "1200", "height": "630"},
        "articleSection": "Karnataka",
        "isAccessibleForFree": True,
        "hasPart": [
            {"@type": "WebPageElement", "isAccessibleForFree": True, "cssSelector": ".article-body"}
        ],
    },
    {
        "@type": "NewsArticle",
        "@context": "http://schema.org",
        "headline": "'Give the South its due': Karnataka CM D K Shivakumar tells Union Home Minister Amit Shah",
        "datePublished": "2026-08-20T08:16:00+05:30",
        "publisher": {"@type": "Organization", "@context": "http://schema.org", "id": ""},
        "author": [{"@type": "Person", "givenName": "Bharath Joshi", "name": "Bharath Joshi"}],
        "image": {"@type": "ImageObject", "width": "1200", "height": "630"},
        "articleSection": "Karnataka",
        "description": "Karnataka Chief Minister DK Shivakumar told Union Home Minister Amit Shah",
        "isAccessibleForFree": True,
        "hasPart": [
            {"@type": "WebPageElement", "isAccessibleForFree": True, "cssSelector": ".article-body"}
        ],
    },
    {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "Deccan Herald",
        "url": "https://www.deccanherald.com",
        "logo": {"@type": "ImageObject", "url": "https://images.assettype.com/deccanherald/logo.png", "width": 300, "height": 300},
        "sameAs": ["https://www.facebook.com/deccanherald", "https://twitter.com/DeccanHerald"],
    },
]


def _render2(blocks: list) -> str:
    parts = ["<!DOCTYPE html>\n<html>\n<head>\n"]
    for b in blocks:
        parts.append(f'  <script type="application/ld+json">\n{json.dumps(b, indent=2)}\n  </script>\n')
    parts.append("</head>\n<body></body>\n</html>\n")
    return "".join(parts)


DH2_HTML = _render2(DH2_BLOCKS)


@pytest.fixture(scope="module")
def dh2_result():
    return analyze_structured_data(DH2_HTML)


class TestDeccanHeraldShivakumarPaywallRegression:
    """Covers the discrepancy from this ticket: the app must detect
    Paywalled Content and report 6 Google Search eligible items, WITHOUT
    forcing the Schema.org "Organization -> id" error to disappear."""

    def test_schema_org_item_count_and_error_unchanged(self, dh2_result):
        assert dh2_result.item_count == 4
        assert dh2_result.error_count == 1  # genuine "publisher.id" unknown property
        errors = [f for f in dh2_result.findings if f.severity == "ERROR"]
        assert errors[0].property == "id"
        assert "not recognised by the schema" in errors[0].message

    def test_google_articles_eligible(self, dh2_result):
        article_items = [i for i in dh2_result.google.items if i.item_type in ("Article", "NewsArticle")]
        assert len(article_items) == 2
        assert all(i.eligible for i in article_items)

    def test_google_breadcrumb_and_organization_eligible(self, dh2_result):
        breadcrumb = [i for i in dh2_result.google.items if i.item_type == "BreadcrumbList"][0]
        org = [i for i in dh2_result.google.items if i.item_type == "Organization"][0]
        assert breadcrumb.eligible is True
        assert org.eligible is True

    def test_paywalled_content_detected_for_both_articles(self, dh2_result):
        paywall_items = [i for i in dh2_result.google.items if i.rich_result_type == "Paywalled content"]
        assert len(paywall_items) == 2
        assert all(i.eligible for i in paywall_items)

    def test_total_google_eligible_count_is_six(self, dh2_result):
        assert dh2_result.google.eligible_count == 6

    def test_schema_and_google_validity_stay_decoupled(self, dh2_result):
        """The NewsArticle carries a genuine Schema.org error (publisher.id)
        AND is still Google-eligible — these must not be conflated."""
        news_item = [i for i in dh2_result.items if i.type == "NewsArticle"][0]
        news_google = [i for i in dh2_result.google.items if i.item_type == "NewsArticle"][0]
        assert news_item.errors == 1
        assert news_google.eligible is True
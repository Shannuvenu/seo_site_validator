"""Tests for Technical SEO and Site Structure services."""
from __future__ import annotations

from app.services.technical_seo import TechnicalSeoAnalyzer
from app.services.site_structure import SiteStructureService, normalize_site_name

SAMPLE_PAGE = """<!DOCTYPE html>
<html>
<head>
  <title>Deccan Herald | Test Article</title>
  <meta name="description" content="A test article description that is reasonably long for testing purposes.">
  <link rel="canonical" href="https://www.deccanherald.com/test-article">
  <meta name="robots" content="index, follow">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta property="og:title" content="Test Article">
  <meta property="og:type" content="article">
  <meta name="twitter:card" content="summary_large_image">
</head>
<body>
  <h1>Main Headline</h1>
  <h2>Section A</h2>
  <h2>Section B</h2>
  <img src="/a.jpg" alt="Picture A">
  <img src="/b.jpg">
  <a href="/internal">Internal</a>
  <a href="https://external.example.com/x">External</a>
  <a href="#section">Anchor</a>
</body>
</html>
"""


class TestTechnicalSeo:
    def test_full_analysis(self):
        result = TechnicalSeoAnalyzer().analyze(
            html=SAMPLE_PAGE,
            url="https://www.deccanherald.com/test-article",
            final_url="https://www.deccanherald.com/test-article",
            status_code=200,
            content_type="text/html",
            fetch_duration_ms=123.0,
        )
        assert result.title == "Deccan Herald | Test Article"
        assert result.title_length == len(result.title)
        assert result.canonical == "https://www.deccanherald.com/test-article"
        assert result.robots_directives == ["index", "follow"]
        assert result.h1 == ["Main Headline"]
        assert result.h2 == ["Section A", "Section B"]
        assert result.image_count == 2
        assert result.images_missing_alt == 1
        assert result.link_count == 3
        assert result.internal_links == 1
        assert result.external_links == 1
        assert result.broken_anchors == 1
        assert result.og_tags["og:title"] == "Test Article"
        assert result.twitter_tags["twitter:card"] == "summary_large_image"
        assert result.status_code == 200

    def test_no_schema_findings_in_technical_seo(self):
        """Technical SEO must never contain Schema.org findings."""
        result = TechnicalSeoAnalyzer().analyze(
            html=SAMPLE_PAGE,
            url="https://www.deccanherald.com/",
            final_url="https://www.deccanherald.com/",
            status_code=200,
            content_type="text/html",
            fetch_duration_ms=1.0,
        )
        for f in result.findings:
            assert f.category == "general"

    def test_missing_title_is_error(self):
        result = TechnicalSeoAnalyzer().analyze(
            html="<html><body>No head here</body></html>",
            url="https://example.com/",
            final_url="https://example.com/",
            status_code=200,
            content_type="text/html",
            fetch_duration_ms=1.0,
        )
        assert any(f.name == "Title" and f.severity == "ERROR" for f in result.findings)


class TestSiteStructure:
    def test_normalize_site_names(self):
        assert normalize_site_name("Deccan Herald") == "deccanherald"
        assert normalize_site_name("www.deccanherald.com") == "deccanherald"
        assert normalize_site_name("prajavani") == "prajavani"
        assert normalize_site_name("Prajavani.net") == "prajavani"

    def test_build_tree_from_config_payload(self):
        svc = SiteStructureService()
        data = {
            "sections": [
                {
                    "_id": "sec_news",
                    "name": "News",
                    "slug": "news",
                    "children": [
                        {"_id": "sec_india", "name": "India", "slug": "india"},
                        {"_id": "sec_karnataka", "name": "Karnataka", "slug": "karnataka"},
                    ],
                },
                {"_id": "sec_opinion", "name": "Opinion", "slug": "opinion"},
            ]
        }
        result = svc._build_tree("deccanherald", "https://www.deccanherald.com/api/v1/config", data)
        assert result.node_count == 4
        assert result.root is not None
        # News should have two children
        news = next(n for n in result.nodes if n.section_id == "sec_news")
        assert news.name == "News"
        india = next(n for n in result.nodes if n.section_id == "sec_india")
        assert india.parent_id == "sec_news"

    def test_fetch_config_real(self):
        """Hit the real Quintype endpoint (network) to confirm integration."""
        import asyncio

        result = asyncio.run(SiteStructureService().fetch_config("deccanherald"))
        assert result.node_count > 0
        assert result.root is not None
        assert result.error is None

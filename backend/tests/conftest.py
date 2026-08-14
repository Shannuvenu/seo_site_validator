"""Shared test fixtures: a real NewsArticle JSON-LD sample with source offsets."""
from __future__ import annotations

import pytest


SAMPLE_NEWS_JSONLD = {
    "@context": "https://schema.org",
    "@type": "NewsArticle",
    "headline": "Malnad: the land that lives by rain, shaped by monsoon wisdom",
    "datePublished": "2025-08-10T09:30:00+05:30",
    "author": {
        "@type": "Person",
        "name": "A Staff Reporter",
    },
    "publisher": {
        "@type": "NewsMediaOrganization",
        "name": "Deccan Herald",
        "logo": {
            "@type": "ImageObject",
            "url": "https://www.deccanherald.com/logo.png",
        },
    },
}


def render_block(node, indent=2):
    """Render a JSON node as the body of a JSON-LD script."""
    import json

    return json.dumps(node, ensure_ascii=False, indent=indent)


@pytest.fixture
def sample_html():
    """A minimal news page with one JSON-LD block."""
    body = render_block(SAMPLE_NEWS_JSONLD)
    return (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head>\n"
        "  <title>Test</title>\n"
        f'  <script type="application/ld+json">\n{body}\n  </script>\n'
        "</head>\n"
        "<body></body>\n"
        "</html>\n"
    )


@pytest.fixture
def sample_multi_block_html():
    """A page with three JSON-LD blocks (NewsArticle + BreadcrumbList + WebSite)."""
    import json

    blocks = [
        {
            "@context": "https://schema.org",
            "@type": "NewsArticle",
            "headline": "Hello",
            "author": {"@type": "Person", "name": "Reporter"},
        },
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://www.deccanherald.com/"},
                {"@type": "ListItem", "position": 2, "name": "India", "item": "https://www.deccanherald.com/india"},
            ],
        },
        {
            "@context": "https://schema.org",
            "@graph": [
                {"@type": "WebSite", "name": "Deccan Herald", "url": "https://www.deccanherald.com/"},
                {"@type": "Organization", "name": "Deccan Herald", "url": "https://www.deccanherald.com/"},
            ],
        },
    ]
    parts = [
        "<!DOCTYPE html>\n<html>\n<head>\n",
        "<title>Multi</title>\n",
    ]
    for b in blocks:
        parts.append(f'  <script type="application/ld+json">\n{render_block(b)}\n  </script>\n')
    parts.append("</head>\n<body></body>\n</html>\n")
    return "".join(parts)

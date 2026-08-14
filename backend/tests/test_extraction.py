"""Tests for source-aware JSON-LD extraction and source mapping."""
from __future__ import annotations

import json

from app.parsers.extractor import JsonLdExtractor
from app.parsers.sourceloc import find_jsonld_blocks, JsonLineScanner
from app.parsers.sourcemap import SourceMap


class TestJsonLdExtraction:
    def test_extracts_one_block(self, sample_html):
        blocks = JsonLdExtractor().extract(sample_html)
        assert len(blocks) == 1
        assert blocks[0].parsed is True
        assert blocks[0].malformed is False
        assert blocks[0].raw["@type"] == "NewsArticle"

    def test_multiple_blocks(self, sample_multi_block_html):
        blocks = JsonLdExtractor().extract(sample_multi_block_html)
        assert len(blocks) == 3
        assert all(b.parsed for b in blocks)
        assert blocks[0].raw["@type"] == "NewsArticle"
        assert blocks[1].raw["@type"] == "BreadcrumbList"
        assert "@graph" in blocks[2].raw

    def test_malformed_block_does_not_kill_others(self, sample_multi_block_html):
        bad = (
            "<html><head>"
            '<script type="application/ld+json">{"@type": "NewsArticle", </script>'
            '<script type="application/ld+json">{"@type": "WebPage"}</script>'
            "</head></html>"
        )
        blocks = JsonLdExtractor().extract(bad)
        assert len(blocks) == 2
        assert blocks[0].malformed is True
        assert blocks[0].parsed is False
        assert blocks[0].json_error_line is not None
        assert blocks[1].parsed is True
        assert blocks[1].raw["@type"] == "WebPage"

    def test_html_entities_decoded(self):
        html = (
            '<script type="application/ld+json">'
            '{"@type":"Article","headline":"A &amp; B &lt;3"}'
            "</script>"
        )
        blocks = JsonLdExtractor().extract(html)
        assert blocks[0].raw["headline"] == "A & B <3"


class TestBlockLocator:
    def test_line_numbers(self, sample_html):
        locs = find_jsonld_blocks(sample_html)
        assert len(locs) == 1
        # The block starts on the line of the <script> tag.
        assert locs[0].start_line == 5
        assert locs[0].text_start_line == 6
        assert locs[0].end_line > 6

    def test_offsets_correct(self, sample_html):
        locs = find_jsonld_blocks(sample_html)
        assert sample_html[locs[0].start_offset : locs[0].end_offset].startswith("<script")
        assert sample_html[locs[0].start_offset : locs[0].end_offset].endswith("</script>")


class TestJsonLineScanner:
    def test_scans_nested_paths(self):
        text = json.dumps(
            {
                "@context": "https://schema.org",
                "@type": "NewsArticle",
                "author": {"@type": "Person", "name": "R"},
                "keywords": ["a", "b"],
                "mentions": [{"@type": "Thing", "name": "T1"}, {"@type": "Thing", "name": "T2"}],
            },
            indent=2,
        )
        scan = JsonLineScanner(text).scan()
        paths = scan["paths"]
        assert "author" in paths
        assert "author.name" in paths
        # scalar array elements produce no paths; object array elements do
        assert "keywords" in paths
        assert "mentions[0].name" in paths
        assert "mentions[1].name" in paths
        # verify positions are monotonic in document order
        assert paths["author"][0] < paths["author.name"][0]
        # mentions[0] and mentions[1] can share a line; the keys must be distinct
        assert paths["mentions[0].name"] != paths["mentions[1].name"]

    def test_invalid_json_returns_empty(self):
        scan = JsonLineScanner('{"a": ').scan()
        assert scan["paths"] == {}
        assert scan["raw"] is None


class TestSourceMap:
    def test_maps_json_paths_to_html_lines(self, sample_html):
        sm = SourceMap().build(sample_html)
        assert 0 in sm.block_props
        props = sm.block_props[0]
        assert "@context" in props
        assert "headline" in props
        assert "author" in props
        assert "author.name" in props
        # author.name should be on a later line than headline
        assert props["headline"].html_line < props["author.name"].html_line
        # every property has offsets inside the HTML
        for pr in props.values():
            assert pr.start_offset > 0
            assert pr.end_offset > pr.start_offset

    def test_locate_exact(self, sample_html):
        sm = SourceMap().build(sample_html)
        pr = sm.locate(0, "headline")
        assert pr is not None
        assert pr.json_path == "headline"
        # the html line should point at the line containing "headline"
        line_text = sample_html.splitlines()[pr.html_line - 1]
        assert "headline" in line_text

    def test_multi_block_paths_distinct(self, sample_multi_block_html):
        sm = SourceMap().build(sample_multi_block_html)
        assert len(sm.block_props) == 3
        # BreadcrumbList block has itemListElement[0].name etc.
        props = sm.block_props[1]
        assert "itemListElement[0].name" in props
        assert "itemListElement[1].item" in props

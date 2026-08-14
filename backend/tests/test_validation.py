"""Tests for Schema.org validation semantics and error grouping.

The reference behavior is validator.schema.org: findings are attributed to the
TOP-LEVEL detected item that contains them, identical errors dedupe across
blocks, and per-item counts equal the global count (single source of truth).
"""
from __future__ import annotations

from app.parsers.extractor import JsonLdExtractor
from app.parsers.normalizer import JsonLdNormalizer
from app.parsers.sourcemap import SourceMap
from app.validators.schema_org import SchemaOrgValidator


def run_validation(html: str):
    """Extract -> normalize -> validate, returning the result."""
    blocks = JsonLdExtractor().extract(html)
    sm = SourceMap().build(html)
    block_models = JsonLdNormalizer().normalize_blocks(blocks, sm)
    result = SchemaOrgValidator().validate(block_models, sm)
    return result


class TestValidationSemantics:
    def test_valid_news_article_no_errors(self, sample_html):
        result = run_validation(sample_html)
        assert result.error_count == 0
        assert result.item_count == 1
        item = result.items[0]
        assert item.type == "NewsArticle"
        assert item.status == "PASS"

    def test_valid_article(self):
        html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"Article","headline":"X",'
            '"author":{"@type":"Person","name":"R"}}'
            "</script>"
        )
        result = run_validation(html)
        assert result.error_count == 0
        assert result.item_count == 1
        assert result.items[0].type == "Article"

    def test_valid_news_article_full(self):
        html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"NewsArticle","headline":"X",'
            '"datePublished":"2025-01-01T00:00:00+05:30",'
            '"publisher":{"@type":"Organization","name":"DH"},'
            '"author":{"@type":"Person","name":"R"}}'
            "</script>"
        )
        result = run_validation(html)
        assert result.error_count == 0
        assert result.warning_count == 0
        assert result.item_count == 1

    def test_unknown_property_is_error(self):
        html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"NewsArticle","headline":"X","notARealProperty":"y"}'
            "</script>"
        )
        result = run_validation(html)
        errors = [f for f in result.findings if f.severity == "ERROR"]
        assert len(errors) == 1
        assert errors[0].property == "notARealProperty"
        assert errors[0].item_type == "NewsArticle"
        assert errors[0].json_path == "0.notARealProperty"
        assert errors[0].error_code in ("UNKNOWN_FIELD", "INVALID_PREDICATE")

    def test_keyword_not_treated_as_property(self):
        html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"NewsArticle","@id":"https://example.com/a","headline":"X"}'
            "</script>"
        )
        result = run_validation(html)
        assert result.error_count == 0
        assert result.item_count == 1

    def test_id_versus_atid_preserved(self):
        """'id' is NOT '@id'. 'id' on Organization is a real error."""
        html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"NewsArticle","headline":"X",'
            '"publisher":{"@type":"Organization","@id":"https://x.com/org","id":""}}'
            "</script>"
        )
        result = run_validation(html)
        errors = [f for f in result.findings if f.severity == "ERROR"]
        assert len(errors) == 1
        assert errors[0].property == "id"  # 'id' flagged, '@id' not
        assert errors[0].item_type == "NewsArticle"

    def test_unknown_type_reported_honestly(self):
        html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"TotallyMadeUpType","headline":"X"}'
            "</script>"
        )
        result = run_validation(html)
        errors = [f for f in result.findings if f.severity == "ERROR"]
        assert any(f.property == "@type" for f in errors)
        assert any(f.error_code == "INVALID_ITEMTYPE" for f in errors)

    def test_inherited_property_not_flagged(self):
        # publisher is defined on Organization -> CreativeWork; author on Article.
        html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"NewsArticle","headline":"X",'
            '"author":{"@type":"Person","name":"R"},"publisher":{"@type":"Organization","name":"DH"}}'
            "</script>"
        )
        result = run_validation(html)
        assert result.error_count == 0
        assert result.item_count == 1

    def test_error_grouping_by_item(self):
        html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"NewsArticle","headline":"X","badProp":1}'
            "</script>"
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"BreadcrumbList",'
            '"itemListElement":[{"@type":"ListItem","position":1,"name":"H","bad2":2}]}'
            "</script>"
        )
        result = run_validation(html)
        assert result.error_count == 2
        news_errors = [f for f in result.findings if f.item_type == "NewsArticle" and f.severity == "ERROR"]
        bread_errors = [f for f in result.findings if f.item_type == "BreadcrumbList" and f.severity == "ERROR"]
        assert len(news_errors) == 1
        assert len(bread_errors) == 1
        assert news_errors[0].property == "badProp"
        # nested ListItem error belongs to the top-level BreadcrumbList item
        assert bread_errors[0].property == "bad2"
        assert bread_errors[0].json_path == "0.itemListElement[0].bad2"
        # invariant: global == sum of per-item errors
        assert result.error_count == sum(i.errors for i in result.items)

    def test_missing_property_not_an_error(self):
        html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"NewsArticle"}'
            "</script>"
        )
        result = run_validation(html)
        assert result.error_count == 0

    def test_multiple_errors_one_item(self):
        html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"NewsArticle","headline":"X",'
            '"badProp1":1,"badProp2":2}'
            "</script>"
        )
        result = run_validation(html)
        assert result.error_count == 2
        item = result.items[0]
        assert item.errors == 2
        assert result.error_count == sum(i.errors for i in result.items)


class TestSourceMappingOnFindings:
    def test_finding_has_exact_source_location(self):
        html = (
            "<html><head>\n"
            '<script type="application/ld+json">\n'
            '{\n  "@context": "https://schema.org",\n  "@type": "NewsArticle",\n'
            '  "headline": "X",\n  "badProperty": "oops"\n}\n'
            "</script>\n</head></html>"
        )
        result = run_validation(html)
        errors = [f for f in result.findings if f.severity == "ERROR"]
        assert len(errors) == 1
        src = errors[0].source
        assert src is not None
        # the error should point at the line with "badProperty"
        lines = html.splitlines()
        assert "badProperty" in lines[src.html_line - 1]
        assert errors[0].json_path == "0.badProperty"
        assert src.start_offset is not None
        assert src.end_offset > src.start_offset
        # the source range must cover the property name
        segment = html[src.start_offset : src.end_offset]
        assert "badProperty" in segment

    def test_nested_finding_source(self):
        html = (
            '<script type="application/ld+json">\n'
            '{\n "@context": "https://schema.org",\n "@type": "NewsArticle",\n'
            ' "author": {\n  "@type": "Person",\n  "name": "R",\n  "bogus": true\n }\n}\n'
            "</script>"
        )
        result = run_validation(html)
        errors = [f for f in result.findings if f.severity == "ERROR"]
        assert len(errors) == 1
        assert errors[0].property == "bogus"
        assert errors[0].json_path == "0.author.bogus"
        src = errors[0].source
        assert src is not None
        lines = html.splitlines()
        assert "bogus" in lines[src.html_line - 1]

    def test_same_value_appearing_multiple_times_maps_correctly(self):
        """'name: Deccan Herald' appears in multiple places; the finding must
        point at the EXACT occurrence that produced it."""
        html = (
            '<script type="application/ld+json">\n'
            '{\n "@context": "https://schema.org",\n "@type": "NewsArticle",\n'
            ' "publisher": {\n  "@type": "Organization",\n  "name": "Deccan Herald",\n'
            '  "badProp": 1\n },\n "author": {\n  "@type": "Person",\n  "name": "Deccan Herald"\n }\n}\n'
            "</script>"
        )
        result = run_validation(html)
        errors = [f for f in result.findings if f.severity == "ERROR"]
        assert len(errors) == 1
        assert errors[0].property == "badProp"
        assert errors[0].json_path == "0.publisher.badProp"
        src = errors[0].source
        assert src is not None
        lines = html.splitlines()
        assert "badProp" in lines[src.html_line - 1]
        # the error must point at the publisher's badProp, not the author's name
        # — the slice of the source at the finding's offsets is the property key
        segment = html[src.start_offset : src.end_offset]
        assert '"badProp"' in segment


class TestGraphAndNested:
    def test_graph_splits_into_items(self):
        html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@graph":['
            '{"@type":"WebSite","name":"DH","url":"https://www.deccanherald.com/"},'
            '{"@type":"Organization","name":"DH","url":"https://www.deccanherald.com/"}]}'
            "</script>"
        )
        result = run_validation(html)
        assert result.item_count == 2
        assert {i.type for i in result.items} == {"WebSite", "Organization"}
        assert result.error_count == 0

    def test_nested_graph_nodes_are_not_top_level_items(self):
        """@graph nodes nested inside a property must NOT inflate the item count."""
        html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"NewsArticle","headline":"X",'
            '"author":{"@graph":[{"@type":"Person","name":"A"},{"@type":"Person","name":"B"}]}}'
            "</script>"
        )
        result = run_validation(html)
        assert result.item_count == 1
        assert result.error_count == 0

    def test_array_of_entities(self):
        html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"BreadcrumbList",'
            '"itemListElement":[{"@type":"ListItem","position":1,"name":"Home"},'
            '{"@type":"ListItem","position":2,"name":"India","badProp":1}]}'
            "</script>"
        )
        result = run_validation(html)
        errors = [f for f in result.findings if f.severity == "ERROR"]
        assert len(errors) == 1
        assert errors[0].property == "badProp"
        assert errors[0].item_type == "BreadcrumbList"  # attributed to top-level
        assert errors[0].json_path == "0.itemListElement[1].badProp"

    def test_live_blog_nested_updates(self):
        html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"LiveBlogPosting","headline":"Live",'
            '"liveBlogUpdate":[{"@type":"BlogPosting","headline":"Update 1"},'
            '{"@type":"BlogPosting","headline":"Update 2"}]}'
            "</script>"
        )
        result = run_validation(html)
        assert result.error_count == 0
        assert result.item_count == 1

    def test_id_reference_node(self):
        """A node referenced by @id should not be double-counted as its own item."""
        html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"NewsArticle","headline":"X",'
            '"author":{"@id":"https://x.com/author/1"}}'
            "</script>"
        )
        result = run_validation(html)
        assert result.item_count == 1
        assert result.error_count == 0

    def test_wrong_expected_property_type_warns_not_errors(self):
        """A value whose type doesn't match the declared range is a WARNING,
        not an error, matching the official validator's looseness."""
        html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"NewsArticle","headline":"X",'
            '"datePublished": 12345}'
            "</script>"
        )
        result = run_validation(html)
        assert result.error_count == 0
        # a number for a Date field may warn
        assert result.warning_count <= 1


class TestCrossItemDedup:
    def test_identical_error_in_generic_and_specific_type_collapses(self):
        """The same publisher.id flaw in Article AND NewsArticle blocks reports
        once, on the most specific type (NewsArticle) — matching the official
        validator's 1-error result for the Deccan Herald page."""
        html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"Article","headline":"X",'
            '"publisher":{"@type":"Organization","id":""}}'
            "</script>"
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"NewsArticle","headline":"X",'
            '"publisher":{"@type":"Organization","id":""}}'
            "</script>"
        )
        result = run_validation(html)
        assert result.item_count == 2
        assert result.error_count == 1
        assert sum(i.errors for i in result.items) == result.error_count
        by_type = {i.type: i.errors for i in result.items}
        assert by_type["Article"] == 0
        assert by_type["NewsArticle"] == 1

    def test_distinct_errors_are_not_deduped(self):
        html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"NewsArticle","headline":"X","badA":1}'
            "</script>"
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":['
            '{"@type":"ListItem","position":1,"name":"H","badB":1}]}'
            "</script>"
        )
        result = run_validation(html)
        assert result.error_count == 2
        assert sum(i.errors for i in result.items) == result.error_count


class TestMalformedJsonLd:
    def test_malformed_json_is_parse_error_not_schema_error(self):
        html = (
            '<script type="application/ld+json">{"@type": "NewsArticle", </script>'
            '<script type="application/ld+json">{"@context":"https://schema.org","@type":"WebPage"}</script>'
        )
        result = run_validation(html)
        # The malformed block is reported on the block, not as a schema finding.
        malformed_blocks = [b for b in result.blocks if b.malformed]
        assert len(malformed_blocks) == 1
        # the valid block still validates with 0 schema errors
        assert result.item_count == 1
        assert result.items[0].type == "WebPage"

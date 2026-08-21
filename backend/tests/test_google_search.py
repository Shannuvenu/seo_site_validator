"""Tests for the Google Search structured-data eligibility layer.

This layer is deliberately separate from Schema.org validation
(``test_validation.py`` / ``test_dh_regression.py``): a Schema.org-valid item
is not automatically Google Search eligible, and vice versa.
"""
from __future__ import annotations

from app.parsers.extractor import JsonLdExtractor
from app.parsers.normalizer import JsonLdNormalizer
from app.parsers.sourcemap import SourceMap
from app.services.pipeline import analyze_structured_data
from app.validators.schema_org import SchemaOrgValidator


def run(html: str):
    """Extract -> normalize -> Schema.org validate -> Google validate."""
    return analyze_structured_data(html)


def block_html(node_json: str) -> str:
    return (
        "<html><head>"
        f'<script type="application/ld+json">{node_json}</script>'
        "</head><body></body></html>"
    )


class TestGoogleProductEligibility:
    def test_product_with_offers_is_eligible(self):
        html = block_html(
            '{"@context":"https://schema.org","@type":"Product","name":"Widget",'
            '"image":"https://example.com/w.jpg","offers":{"@type":"Offer",'
            '"price":"9.99","priceCurrency":"USD","availability":"https://schema.org/InStock"}}'
        )
        result = run(html)
        assert result.error_count == 0  # Schema.org valid
        gitem = result.google.items[0]
        assert gitem.support_status == "SUPPORTED"
        assert gitem.rich_result_type
        assert gitem.eligible is True
        assert gitem.errors == 0

    def test_product_missing_name_is_google_error(self):
        html = block_html(
            '{"@context":"https://schema.org","@type":"Product",'
            '"offers":{"@type":"Offer","price":"9.99","priceCurrency":"USD"}}'
        )
        result = run(html)
        gitem = result.google.items[0]
        assert gitem.eligible is False
        codes = {f.code for f in result.google.findings if f.item_index == 0}
        assert "GOOGLE_MISSING_REQUIRED" in codes

    def test_product_missing_offers_review_and_rating_one_of(self):
        """ONE_OF rule: Product needs at least one of offers/review/aggregateRating."""
        html = block_html('{"@context":"https://schema.org","@type":"Product","name":"Widget"}')
        result = run(html)
        gitem = result.google.items[0]
        assert gitem.eligible is False
        one_of = [f for f in result.google.findings if f.code == "GOOGLE_ONE_OF_MISSING"]
        assert len(one_of) == 1
        assert "offers" in one_of[0].message

    def test_product_one_of_satisfied_by_review_only(self):
        """Do NOT report an error when only one valid alternative is supplied."""
        html = block_html(
            '{"@context":"https://schema.org","@type":"Product","name":"Widget",'
            '"review":{"@type":"Review","author":{"@type":"Person","name":"A"},'
            '"reviewRating":{"@type":"Rating","ratingValue":"4"}}}'
        )
        result = run(html)
        one_of = [f for f in result.google.findings if f.code == "GOOGLE_ONE_OF_MISSING"]
        assert len(one_of) == 0

    def test_product_missing_recommended_is_warning_not_error(self):
        html = block_html(
            '{"@context":"https://schema.org","@type":"Product","name":"Widget",'
            '"offers":{"@type":"Offer","price":"9.99","priceCurrency":"USD"}}'
        )
        result = run(html)
        gitem = result.google.items[0]
        # missing image/description/brand/sku/gtin/mpn -> warnings, still eligible
        assert gitem.warnings > 0
        assert gitem.eligible is True
        assert gitem.errors == 0


class TestGoogleRecipeEligibility:
    def test_recipe_all_of_required_fields_present(self):
        html = block_html(
            '{"@context":"https://schema.org","@type":"Recipe","name":"Banana Bread",'
            '"image":"https://example.com/b.jpg",'
            '"recipeIngredient":["banana","flour"],'
            '"recipeInstructions":"Mix and bake."}'
        )
        result = run(html)
        gitem = result.google.items[0]
        assert gitem.eligible is True

    def test_recipe_missing_ingredients_is_error(self):
        html = block_html(
            '{"@context":"https://schema.org","@type":"Recipe","name":"Banana Bread",'
            '"image":"https://example.com/b.jpg","recipeInstructions":"Mix and bake."}'
        )
        result = run(html)
        gitem = result.google.items[0]
        assert gitem.eligible is False
        missing_props = {
            f.property for f in result.google.findings if f.code == "GOOGLE_MISSING_REQUIRED"
        }
        assert "recipeIngredient" in missing_props


class TestGoogleArticleNoHardRequirements:
    def test_article_with_no_fields_is_still_eligible_but_warned(self):
        """Google's Article guidance has no hard requirements — only recommended
        fields — so a bare Article must not be reported as INELIGIBLE."""
        html = block_html('{"@context":"https://schema.org","@type":"Article","headline":"X"}')
        result = run(html)
        gitem = result.google.items[0]
        assert gitem.support_status == "SUPPORTED"
        assert gitem.eligible is True  # no required fields => never FAIL
        assert gitem.warnings > 0  # missing recommended fields (image, dates, etc.)


class TestGoogleDeprecatedTypes:
    def test_faqpage_is_reported_as_deprecated_not_a_false_success(self):
        html = block_html(
            '{"@context":"https://schema.org","@type":"FAQPage","mainEntity":['
            '{"@type":"Question","name":"Q1","acceptedAnswer":{"@type":"Answer","text":"A1"}}]}'
        )
        result = run(html)
        gitem = result.google.items[0]
        assert gitem.support_status == "DEPRECATED"
        assert gitem.eligible is False
        assert gitem.deprecated_message
        assert "2026-05-07" in gitem.deprecated_message
        # A deprecated type must never contribute ERROR/WARNING noise.
        assert result.google.error_count == 0
        assert result.google.warning_count == 0

    def test_howto_is_reported_as_deprecated(self):
        html = block_html(
            '{"@context":"https://schema.org","@type":"HowTo","name":"Make tea",'
            '"step":[{"@type":"HowToStep","text":"Boil water"}]}'
        )
        result = run(html)
        gitem = result.google.items[0]
        assert gitem.support_status == "DEPRECATED"
        assert gitem.eligible is False


class TestGoogleUnsupportedAndUnknownTypes:
    def test_valid_schema_type_not_a_google_feature_is_not_supported(self):
        """CreativeWorkSeries (or similar) is valid Schema.org but has no
        Google Search rich-result feature registered for it."""
        html = block_html(
            '{"@context":"https://schema.org","@type":"CreativeWorkSeries","name":"Series A"}'
        )
        result = run(html)
        assert result.error_count == 0  # Schema.org valid
        gitem = result.google.items[0]
        assert gitem.support_status == "NOT_SUPPORTED"
        assert gitem.eligible is False
        assert "not a Google Search supported rich-result feature" in (gitem.note or "")

    def test_schema_org_invalid_type_is_google_unknown(self):
        html = block_html('{"@context":"https://schema.org","@type":"TotallyMadeUpType","x":"y"}')
        result = run(html)
        assert result.error_count >= 1  # Schema.org INVALID_ITEMTYPE
        gitem = result.google.items[0]
        assert gitem.support_status == "UNKNOWN"
        assert gitem.eligible is False


class TestGoogleSchemaSeparation:
    def test_schema_valid_does_not_imply_google_eligible(self):
        """A Schema.org-valid Product missing offers/review/aggregateRating is
        still Schema.org VALID but Google-INELIGIBLE — these must not be
        conflated into one status."""
        html = block_html('{"@context":"https://schema.org","@type":"Product","name":"Widget"}')
        result = run(html)
        assert result.error_count == 0  # Schema.org: valid
        assert result.google.items[0].eligible is False  # Google: not eligible

    def test_findings_are_categorised_separately(self):
        html = block_html(
            '{"@context":"https://schema.org","@type":"Product","badProp":1}'
        )
        result = run(html)
        schema_codes = {f.error_code for f in result.findings}
        google_categories = {f.category for f in result.google.findings}
        assert "UNKNOWN_FIELD" in schema_codes
        assert google_categories <= {"GOOGLE_SEARCH_ERROR", "GOOGLE_SEARCH_WARNING"}


class TestGoogleMultipleErrorsAndWarnings:
    def test_item_can_carry_both_error_and_warning(self):
        html = block_html(
            '{"@context":"https://schema.org","@type":"Recipe","image":"https://example.com/x.jpg",'
            '"recipeIngredient":["x"],"recipeInstructions":"do it"}'
        )
        result = run(html)  # missing "name" (required) but has ingredients/instructions
        gitem = result.google.items[0]
        assert gitem.errors >= 1
        assert gitem.warnings >= 1  # missing several recommended fields too


class TestGoogleSourceLocation:
    def test_google_finding_has_source_location_when_available(self):
        html = block_html('{"@context":"https://schema.org","@type":"Product","name":"Widget"}')
        result = run(html)
        one_of = [f for f in result.google.findings if f.code == "GOOGLE_ONE_OF_MISSING"]
        assert len(one_of) == 1
        # one-of findings reference the item path even without a single prop match
        assert one_of[0].block_index == 0
        assert one_of[0].item_type == "Product"


class TestGoogleOverviewCounts:
    def test_result_level_counts_are_consistent(self):
        html = (
            "<html><head>"
            '<script type="application/ld+json">{"@context":"https://schema.org",'
            '"@type":"Product","name":"Widget","offers":{"@type":"Offer","price":"1","priceCurrency":"USD"}}</script>'
            '<script type="application/ld+json">{"@context":"https://schema.org",'
            '"@type":"FAQPage","mainEntity":[]}</script>'
            '<script type="application/ld+json">{"@context":"https://schema.org",'
            '"@type":"CreativeWorkSeries","name":"S"}</script>'
            "</head><body></body></html>"
        )
        result = run(html)
        g = result.google
        assert g.supported_count == 1
        assert g.deprecated_count == 1
        assert g.not_supported_count == 1
        assert g.supported_count + g.deprecated_count + g.not_supported_count + g.unknown_count == len(g.items)
        
class TestGooglePaywalledContent:
    """Google's "Paywalled content" feature: isAccessibleForFree + hasPart /
    WebPageElement / cssSelector nested inside a CreativeWork-family node.

    Deliberately separate from the type-rule tests above: this feature is
    NOT a Schema.org @type, so it never appears in GOOGLE_TYPE_RULES / via
    get_rule() — it is detected directly on the raw node.
    """

    def test_valid_paywall_markup_is_eligible(self):
        html = block_html(
            '{"@context":"https://schema.org","@type":"NewsArticle","headline":"X",'
            '"isAccessibleForFree":false,'
            '"hasPart":[{"@type":"WebPageElement","isAccessibleForFree":false,'
            '"cssSelector":".paywall"}]}'
        )
        result = run(html)
        paywall_items = [i for i in result.google.items if i.rich_result_type == "Paywalled content"]
        assert len(paywall_items) == 1
        assert paywall_items[0].eligible is True
        assert paywall_items[0].item_type == "WebPageElement"
        # The Article's own eligibility is untouched by the paywall check.
        article_item = [i for i in result.google.items if i.item_type == "NewsArticle"][0]
        assert article_item.support_status == "SUPPORTED"

    def test_missing_top_level_isAccessibleForFree_is_error(self):
        html = block_html(
            '{"@context":"https://schema.org","@type":"NewsArticle","headline":"X",'
            '"hasPart":[{"@type":"WebPageElement","isAccessibleForFree":false,'
            '"cssSelector":".paywall"}]}'
        )
        result = run(html)
        paywall = [i for i in result.google.items if i.rich_result_type == "Paywalled content"][0]
        assert paywall.eligible is False
        props = {f.property for f in result.google.findings if f.rich_result_type == "Paywalled content"}
        assert "isAccessibleForFree" in props

    def test_missing_cssSelector_is_error(self):
        html = block_html(
            '{"@context":"https://schema.org","@type":"NewsArticle","headline":"X",'
            '"isAccessibleForFree":false,'
            '"hasPart":[{"@type":"WebPageElement","isAccessibleForFree":false}]}'
        )
        result = run(html)
        paywall = [i for i in result.google.items if i.rich_result_type == "Paywalled content"][0]
        assert paywall.eligible is False
        props = {f.property for f in result.google.findings if f.rich_result_type == "Paywalled content"}
        assert "hasPart[0].cssSelector" in props

    def test_multiple_paywalled_sections_on_one_article(self):
        """Multiple hasPart/WebPageElement entries on the same node."""
        html = block_html(
            '{"@context":"https://schema.org","@type":"NewsArticle","headline":"X",'
            '"isAccessibleForFree":false,'
            '"hasPart":['
            '{"@type":"WebPageElement","isAccessibleForFree":true,"cssSelector":".intro"},'
            '{"@type":"WebPageElement","isAccessibleForFree":false,"cssSelector":".paywall"}'
            ']}'
        )
        result = run(html)
        paywall_items = [i for i in result.google.items if i.rich_result_type == "Paywalled content"]
        # One aggregated Google result for the node, not one per hasPart entry.
        assert len(paywall_items) == 1
        assert paywall_items[0].eligible is True

    def test_hasPart_without_webpage_element_is_not_the_paywall_feature(self):
        """hasPart used for something else (e.g. site navigation) must not be
        misdetected as the paywalled-content feature."""
        html = block_html(
            '{"@context":"https://schema.org","@type":"SiteNavigationElement","name":"Nav",'
            '"hasPart":[{"@type":"SiteNavigationElement","name":"India"}]}'
        )
        result = run(html)
        assert not any(i.rich_result_type == "Paywalled content" for i in result.google.items)

    def test_non_creativework_type_with_hasPart_is_ignored(self):
        """A Product using hasPart for unrelated parts must never trigger the
        paywall feature — it only applies to the CreativeWork family."""
        html = block_html(
            '{"@context":"https://schema.org","@type":"Product","name":"Widget",'
            '"offers":{"@type":"Offer","price":"9.99","priceCurrency":"USD"},'
            '"hasPart":[{"@type":"WebPageElement","isAccessibleForFree":false,'
            '"cssSelector":".x"}]}'
        )
        result = run(html)
        # A Product with a WebPageElement hasPart entry is unrealistic, but if
        # it occurs we still only apply the feature to CreativeWork nodes.
        assert not any(i.rich_result_type == "Paywalled content" for i in result.google.items)

    def test_no_hasPart_no_paywall_item_emitted(self):
        """An ordinary article with no paywall markup gets no Paywalled
        content entry at all — never a manufactured claim."""
        html = block_html('{"@context":"https://schema.org","@type":"NewsArticle","headline":"X"}')
        result = run(html)
        assert not any(i.rich_result_type == "Paywalled content" for i in result.google.items)

    def test_source_mapping_points_at_cssSelector(self):
        html = block_html(
            '{"@context":"https://schema.org","@type":"NewsArticle","headline":"X",'
            '"isAccessibleForFree":false,'
            '"hasPart":[{"@type":"WebPageElement","isAccessibleForFree":false,'
            '"cssSelector":""}]}'
        )
        result = run(html)
        f = [f for f in result.google.findings if f.property == "hasPart[0].cssSelector"][0]
        assert f.source is not None
        assert f.source.start_offset is not None and f.source.end_offset is not None        

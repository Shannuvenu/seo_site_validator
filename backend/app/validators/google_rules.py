"""Google Search structured-data eligibility rule registry.

This module is the SINGLE SOURCE OF TRUTH for what this application claims
about Google Search structured-data eligibility. It is deliberately kept
separate from ``schema_org.py`` (Schema.org vocabulary validity) — see
``google_search.py`` for the validator that applies these rules.

IMPORTANT — accuracy discipline (requirement #16, "no fake Google claims"):

- Every rule here is meant to reflect Google's PUBLICLY DOCUMENTED structured
  data guidelines (https://developers.google.com/search/docs/appearance/structured-data).
  This is NOT a reproduction of Google's proprietary ranking/eligibility
  algorithm — it is a best-effort, maintainable approximation of the
  published required/recommended property lists for the most common rich
  result types.
- Fields marked ``heuristic=True`` on an emitted finding indicate a
  project-level interpretation (e.g. "a URL-shaped string probably satisfies
  a Thing-typed range") rather than a rule lifted verbatim from Google's
  docs.
- Types Google has PUBLICLY DEPRECATED are marked ``support="DEPRECATED"``
  with a dated explanation, instead of silently validating them as if they
  still produce a rich result. As of this registry's last review:
    * FAQPage rich results stopped appearing in Google Search for ALL sites
      as of 2026-05-07 (they were already restricted to authoritative
      government/health sites since 2023-08). FAQPage remains a valid
      Schema.org type; it is simply no longer a Google Search feature.
    * HowTo rich results were deprecated on desktop in 2023-09 (having
      already been restricted on mobile earlier the same year).
    * ClaimReview and SpecialAnnouncement were retired as Search features in
      2025-06 along with five other minor features.

To add a new Google-supported type: add a ``GoogleTypeRule`` entry to
``GOOGLE_TYPE_RULES`` below. Nothing else in the pipeline needs to change —
this is the extension point requirement #2 asks for.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Rule primitives
# ---------------------------------------------------------------------------

# Value/format kinds understood by the format validator in google_search.py.
ValueKind = str  # "text" | "url" | "date" | "datetime" | "number" | "price" | "enum" | "image" | "object"


@dataclass(frozen=True)
class PropertyFormat:
    """Optional format constraint for a required/recommended property."""

    prop: str
    kind: ValueKind = "text"
    enum_values: Optional[Tuple[str, ...]] = None


@dataclass(frozen=True)
class GoogleTypeRule:
    """Google Search eligibility rule set for one Schema.org type.

    - ``required``: simple top-level (or dotted-path) properties that MUST be
      present for the item to be eligible. Missing => ERROR.
    - ``required_one_of``: groups where at least ONE property in each group
      must be present (Google's "include at least one of" pattern). Missing
      the whole group => ERROR.
    - ``recommended``: properties whose absence is a WARNING, never an error.
    - ``formats``: optional format/type constraints checked when the
      property IS present.
    """

    schema_type: str
    rich_result_name: str
    support: str  # "SUPPORTED" | "DEPRECATED"
    required: Tuple[str, ...] = ()
    required_one_of: Tuple[Tuple[str, ...], ...] = ()
    recommended: Tuple[str, ...] = ()
    formats: Tuple[PropertyFormat, ...] = ()
    notes: str = ""
    deprecated_message: Optional[str] = None
    doc_url: str = ""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

GOOGLE_TYPE_RULES: dict[str, GoogleTypeRule] = {}


def _register(rule: GoogleTypeRule) -> None:
    GOOGLE_TYPE_RULES[rule.schema_type] = rule


# ---- Article family --------------------------------------------------------
# Google's Article documentation (last public update reviewed: 2025-12) does
# not list any strictly required properties; markup without headline/image is
# still parsed, just lower quality. We therefore treat these as recommended
# only, to avoid manufacturing an error Google itself does not raise.
_ARTICLE_RULE = GoogleTypeRule(
    schema_type="Article",
    rich_result_name="Article (Top stories / AMP carousel context)",
    support="SUPPORTED",
    required=(),
    recommended=("headline", "image", "datePublished", "dateModified", "author", "publisher"),
    formats=(
        PropertyFormat("image", "image"),
        PropertyFormat("datePublished", "datetime"),
        PropertyFormat("dateModified", "datetime"),
    ),
    notes="Google's Article guidance lists no required properties; the fields "
    "below are RECOMMENDED for eligibility for Top Stories / richer display.",
    doc_url="https://developers.google.com/search/docs/appearance/structured-data/article",
)
for _t in ("Article", "NewsArticle", "BlogPosting", "SocialMediaPosting"):
    _register(GoogleTypeRule(**{**_ARTICLE_RULE.__dict__, "schema_type": _t}))

# ---- Product ----------------------------------------------------------------
_register(
    GoogleTypeRule(
        schema_type="Product",
        rich_result_name="Product snippet / Merchant listing",
        support="SUPPORTED",
        required=("name",),
        required_one_of=(("offers", "review", "aggregateRating"),),
        recommended=("image", "description", "sku", "brand", "gtin", "mpn"),
        formats=(
            PropertyFormat("image", "image"),
            PropertyFormat("offers.price", "price"),
            PropertyFormat("offers.priceCurrency", "text"),
            PropertyFormat("offers.availability", "url"),
            PropertyFormat("aggregateRating.ratingValue", "number"),
            PropertyFormat("aggregateRating.reviewCount", "number"),
        ),
        notes="Google requires Product markup to include at least one of "
        "offers, review, or aggregateRating to be eligible for a rich result.",
        doc_url="https://developers.google.com/search/docs/appearance/structured-data/product",
    )
)

# ---- Recipe -------------------------------------------------------------
_register(
    GoogleTypeRule(
        schema_type="Recipe",
        rich_result_name="Recipe",
        support="SUPPORTED",
        required=("name", "image", "recipeIngredient", "recipeInstructions"),
        recommended=(
            "author",
            "datePublished",
            "description",
            "prepTime",
            "cookTime",
            "totalTime",
            "keywords",
            "recipeYield",
            "recipeCategory",
            "recipeCuisine",
            "nutrition",
            "video",
            "aggregateRating",
            "review",
        ),
        formats=(
            PropertyFormat("image", "image"),
            PropertyFormat("datePublished", "datetime"),
            PropertyFormat("prepTime", "text"),
            PropertyFormat("cookTime", "text"),
            PropertyFormat("totalTime", "text"),
            PropertyFormat("aggregateRating.ratingValue", "number"),
        ),
        doc_url="https://developers.google.com/search/docs/appearance/structured-data/recipe",
    )
)

# ---- BreadcrumbList -------------------------------------------------------
_register(
    GoogleTypeRule(
        schema_type="BreadcrumbList",
        rich_result_name="Breadcrumb",
        support="SUPPORTED",
        required=("itemListElement",),
        notes="Each itemListElement must be a ListItem with a position and "
        "either an item (URL) or a name.",
        doc_url="https://developers.google.com/search/docs/appearance/structured-data/breadcrumb",
    )
)

# ---- FAQPage (DEPRECATED as of 2026-05-07) --------------------------------
_register(
    GoogleTypeRule(
        schema_type="FAQPage",
        rich_result_name="FAQ",
        support="DEPRECATED",
        required=("mainEntity",),
        deprecated_message=(
            "As of 2026-05-07, FAQ rich results no longer appear in Google "
            "Search for any site (this feature was already restricted to "
            "authoritative government/health sites since 2023-08). "
            "FAQPage remains a valid Schema.org type, but it no longer "
            "produces a Google Search rich result."
        ),
        doc_url="https://developers.google.com/search/docs/appearance/structured-data/faqpage",
    )
)

# ---- HowTo (DEPRECATED since 2023-09) -------------------------------------
_register(
    GoogleTypeRule(
        schema_type="HowTo",
        rich_result_name="HowTo",
        support="DEPRECATED",
        required=("name", "step"),
        deprecated_message=(
            "HowTo rich results were deprecated by Google in 2023-09 and no "
            "longer appear in Google Search. HowTo remains a valid "
            "Schema.org type, but it no longer produces a Google Search "
            "rich result."
        ),
        doc_url="https://developers.google.com/search/docs/appearance/structured-data/how-to",
    )
)

# ---- ClaimReview (retired 2025-06) ----------------------------------------
_register(
    GoogleTypeRule(
        schema_type="ClaimReview",
        rich_result_name="Fact Check",
        support="DEPRECATED",
        required=("claimReviewed", "reviewRating"),
        deprecated_message=(
            "Google retired the Fact Check (ClaimReview) rich result "
            "feature in 2025-06."
        ),
        doc_url="https://developers.google.com/search/docs/appearance/structured-data/factcheck",
    )
)

# ---- SpecialAnnouncement (retired 2025-06) --------------------------------
_register(
    GoogleTypeRule(
        schema_type="SpecialAnnouncement",
        rich_result_name="Special Announcement",
        support="DEPRECATED",
        required=("name", "datePosted"),
        deprecated_message=(
            "Google retired the Special Announcement rich result feature in "
            "2025-06."
        ),
        doc_url="https://developers.google.com/search/docs/appearance/structured-data/special-announcement",
    )
)

# ---- JobPosting -------------------------------------------------------------
_register(
    GoogleTypeRule(
        schema_type="JobPosting",
        rich_result_name="Job posting",
        support="SUPPORTED",
        required=("title", "description", "datePosted", "hiringOrganization", "jobLocation"),
        recommended=("validThrough", "employmentType", "baseSalary"),
        formats=(
            PropertyFormat("datePosted", "date"),
            PropertyFormat("validThrough", "datetime"),
        ),
        doc_url="https://developers.google.com/search/docs/appearance/structured-data/job-posting",
    )
)

# ---- Event ------------------------------------------------------------------
_register(
    GoogleTypeRule(
        schema_type="Event",
        rich_result_name="Event",
        support="SUPPORTED",
        required=("name", "startDate", "location"),
        recommended=("endDate", "image", "description", "offers", "performer", "eventAttendanceMode", "eventStatus"),
        formats=(
            PropertyFormat("startDate", "datetime"),
            PropertyFormat("endDate", "datetime"),
            PropertyFormat("image", "image"),
        ),
        doc_url="https://developers.google.com/search/docs/appearance/structured-data/event",
    )
)

# ---- VideoObject --------------------------------------------------------
_register(
    GoogleTypeRule(
        schema_type="VideoObject",
        rich_result_name="Video",
        support="SUPPORTED",
        required=("name", "description", "thumbnailUrl", "uploadDate"),
        recommended=("duration", "contentUrl", "embedUrl", "interactionStatistic"),
        formats=(
            PropertyFormat("thumbnailUrl", "image"),
            PropertyFormat("uploadDate", "datetime"),
            PropertyFormat("contentUrl", "url"),
            PropertyFormat("embedUrl", "url"),
        ),
        doc_url="https://developers.google.com/search/docs/appearance/structured-data/video",
    )
)

# ---- LocalBusiness (and its many subtypes share the same rule) -----------
_LOCAL_BUSINESS_RULE = GoogleTypeRule(
    schema_type="LocalBusiness",
    rich_result_name="Local business",
    support="SUPPORTED",
    required=("name", "address"),
    recommended=("telephone", "openingHoursSpecification", "priceRange", "image"),
    formats=(PropertyFormat("image", "image"),),
    doc_url="https://developers.google.com/search/docs/appearance/structured-data/local-business",
)
_register(_LOCAL_BUSINESS_RULE)

# ---- Organization (logo / knowledge panel) --------------------------------
_register(
    GoogleTypeRule(
        schema_type="Organization",
        rich_result_name="Logo",
        support="SUPPORTED",
        required=("logo", "url"),
        recommended=("sameAs", "name"),
        formats=(PropertyFormat("logo", "image"), PropertyFormat("url", "url")),
        doc_url="https://developers.google.com/search/docs/appearance/structured-data/organization",
    )
)

# ---- SoftwareApplication ---------------------------------------------------
_register(
    GoogleTypeRule(
        schema_type="SoftwareApplication",
        rich_result_name="Software app",
        support="SUPPORTED",
        required=("name", "operatingSystem", "applicationCategory"),
        required_one_of=(("offers", "aggregateRating", "review"),),
        recommended=("offers",),
        formats=(PropertyFormat("aggregateRating.ratingValue", "number"),),
        doc_url="https://developers.google.com/search/docs/appearance/structured-data/software-app",
    )
)

# ---- Review (standalone review snippet) -----------------------------------
_register(
    GoogleTypeRule(
        schema_type="Review",
        rich_result_name="Review snippet",
        support="SUPPORTED",
        required=("itemReviewed", "reviewRating", "author"),
        recommended=("datePublished",),
        formats=(PropertyFormat("reviewRating.ratingValue", "number"),),
        doc_url="https://developers.google.com/search/docs/appearance/structured-data/review-snippet",
    )
)

# ---- WebSite (sitelinks search box) ---------------------------------------
_register(
    GoogleTypeRule(
        schema_type="WebSite",
        rich_result_name="Sitelinks search box",
        support="SUPPORTED",
        required=("url",),
        recommended=("potentialAction",),
        doc_url="https://developers.google.com/search/docs/appearance/sitelinks-searchbox",
    )
)


# ---------------------------------------------------------------------------
# Paywalled content (https://developers.google.com/search/docs/appearance/structured-data/paywalled-content)
# ---------------------------------------------------------------------------
#
# Unlike every rule above, "Paywalled content" is NOT itself a Schema.org
# @type — Google does not define a "PaywalledContent" type in its vocabulary.
# Instead, the feature is expressed as extra properties nested inside a
# CreativeWork-family node (Article, NewsArticle, Report, ...):
#
#   {
#     "@type": "NewsArticle",
#     "isAccessibleForFree": false,
#     "hasPart": [{
#       "@type": "WebPageElement",
#       "isAccessibleForFree": false,
#       "cssSelector": ".paywall"
#     }]
#   }
#
# Because it is not keyed by a top-level @type, it cannot live in
# GOOGLE_TYPE_RULES / be looked up via get_rule(). It is applied directly by
# GoogleSearchValidator (see google_search.py:_check_paywalled_content),
# which reads this rule as its single source of truth for the required
# properties, exactly like GOOGLE_TYPE_RULES is for ordinary types.
@dataclass(frozen=True)
class PaywalledContentRule:
    rich_result_name: str = "Paywalled content"
    # The feature applies to any CreativeWork-family node (Google's docs say
    # "any page marked up as a type of CreativeWork"), resolved via the
    # Schema.org ancestor chain rather than a hardcoded type list so new
    # host types (and other sites) are picked up automatically.
    host_ancestor: str = "CreativeWork"
    required_host: Tuple[str, ...] = ("isAccessibleForFree",)
    required_part_type: str = "WebPageElement"
    required_part_props: Tuple[str, ...] = ("cssSelector", "isAccessibleForFree")
    doc_url: str = "https://developers.google.com/search/docs/appearance/structured-data/paywalled-content"


PAYWALLED_CONTENT_RULE = PaywalledContentRule()

# Small offline fallback so the feature still triggers when the bundled
# Schema.org vocabulary hasn't loaded (e.g. a stripped-down test env) and
# ``Vocabulary.ancestors()`` can't be consulted. The vocabulary-based
# ancestor check in google_search.py is the primary, non-hardcoded path;
# this set only covers the common CreativeWork subtypes news sites use.
PAYWALL_HOST_FALLBACK_TYPES = {
    "CreativeWork",
    "Article",
    "NewsArticle",
    "BlogPosting",
    "SocialMediaPosting",
    "Report",
    "ScholarlyArticle",
    "WebPage",
}


def get_rule(schema_type: str, ancestors: Optional[List[str]] = None) -> Optional[GoogleTypeRule]:
    """Look up the Google rule for a Schema.org type, falling back to the
    closest ancestor that has a rule (e.g. a custom LocalBusiness subtype
    like "Restaurant" inherits the LocalBusiness rule)."""
    if schema_type in GOOGLE_TYPE_RULES:
        return GOOGLE_TYPE_RULES[schema_type]
    for anc in ancestors or []:
        if anc in GOOGLE_TYPE_RULES:
            return GOOGLE_TYPE_RULES[anc]
    return None

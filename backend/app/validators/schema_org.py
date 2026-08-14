"""Schema.org structured-data validator.

Implements the behavior of the official validator at https://validator.schema.org/

Validation semantics (derived from the official validator's error taxonomy and
the schema.org vocabulary dump):

- @context / @type / @id / @graph / @value are JSON-LD keywords — never treated
  as schema.org properties.
- An unknown TYPE produces INVALID_ITEMTYPE:
  "The type <i>X</i> is not a type defined by the recognised schema (e.g. schema.org)."
- An unknown PROPERTY on a known type produces INVALID_PREDICATE / UNKNOWN_FIELD:
  "The property <i>X</i> is not recognised by the schema (e.g. schema.org) for an
   object of type <i>Y</i>."
- Value/type checks follow the official taxonomy (INVALID_OBJECT for a nested
  object whose @type is not a valid target, INVALID_URL for bad URLs, etc.)
- Errors on NESTED entities are attributed to the TOP-LEVEL item that contains
  them (the official validator groups errors by top-level object; a nested
  Organization's bad property is an error of the NewsArticle/Article that embeds
  it, NOT a phantom "Organization" item that never appears in the summary).
- IDENTICAL errors (same error code + property + top-level type) are deduplicated
  across blocks: when the same flawed node appears under both a generic and a
  more specific type (e.g. Article and NewsArticle), the error is reported once,
  on the most specific type. This matches the official validator's "1 error on
  NewsArticle, 0 on Article" behavior for pages that repeat the same publisher
  node in multiple blocks.

Single source of truth: per-item counts (item.errors / item.warnings) and the
global counts (result.error_count / warning_count) are computed from the SAME
findings list, so SUM(item.errors) == global error count always holds.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..models.schemas import (
    DetectedItem,
    JsonLdBlock,
    SourceLocation,
    StructuredDataResult,
    ValidationFinding,
)
from ..parsers.jsonld_parser import bare_type, is_typed_node, node_types
from ..parsers.sourcemap import SourceMap
from .vocabulary import Vocabulary, VocabularyProvider

# JSON-LD keywords: never validated as Schema.org properties.
JSONLD_KEYWORDS = {
    "@context",
    "@type",
    "@id",
    "@graph",
    "@value",
    "@language",
    "@list",
    "@set",
    "@reverse",
    "@index",
    "@none",
    "@vocab",
    "@base",
    "@version",
    "@container",
}


@dataclass
class Context:
    """Shared state for one validation run."""

    vocab: Vocabulary
    findings: List[ValidationFinding]
    source_map: Optional[SourceMap]
    block_index: int = 0
    # top-level items: (block_index, item_index) -> DetectedItem
    items: Dict[Tuple[int, int], DetectedItem] = field(default_factory=dict)

    def add(
        self,
        severity: str,
        message: str,
        item: DetectedItem,
        property: Optional[str] = None,
        json_path: Optional[str] = None,
        source: Optional[SourceLocation] = None,
        error_code: Optional[str] = None,
        detail: Optional[str] = None,
        expected: Optional[str] = None,
        actual: Optional[str] = None,
    ) -> None:
        finding = ValidationFinding(
            id=uuid.uuid4().hex[:12],
            severity=severity,
            message=message,
            error_code=error_code,
            detail=detail,
            item_type=item.type,
            item_index=item.index,
            block_index=item.block_index,
            json_path=json_path or "",
            property=property,
            expected=expected,
            actual=actual,
            source=source,
        )
        self.findings.append(finding)


def _resolve_source(
    ctx: Context,
    json_path: Optional[str],
    block_index: Optional[int],
) -> Optional[SourceLocation]:
    """Resolve a JSON path to a precise HTML source location.

    Item paths are graph-node-relative ("0.headline" or "0.author[0].name");
    source-map paths are block-relative ("headline", "author[0].name"). We try
    both forms and any block.
    """
    if not json_path:
        return None
    path = json_path.lstrip("$.")
    stripped = _strip_graph_prefix(path)
    sm = ctx.source_map
    if sm is None:
        return None
    candidates = [path, stripped]
    pr = None
    for b in ([block_index] if block_index is not None else [ctx.block_index]):
        props = sm.block_props.get(b, {})
        for cand in candidates:
            if cand in props:
                pr = props[cand]
                break
        if pr:
            break
    if pr is None:
        pr = sm.locate_any(stripped)
    if pr is None:
        return None
    return SourceLocation(
        html_line=pr.html_line,
        html_column=pr.html_col,
        start_offset=pr.start_offset,
        end_offset=pr.end_offset,
        json_path=json_path,
        json_line=pr.json_line,
        json_column=pr.json_col,
        block_index=pr.block_index,
    )


def _strip_graph_prefix(path: str) -> str:
    """'0.headline' -> 'headline'; '0.author[0].name' -> 'author[0].name'."""
    if "." in path:
        head, rest = path.split(".", 1)
        if head.isdigit():
            return rest
    return path


def _preview(value: Any, max_len: int = 90) -> str:
    if isinstance(value, str):
        return value if len(value) <= max_len else value[:max_len] + "…"
    import json as _json

    try:
        s = _json.dumps(value, ensure_ascii=False)
        return s if len(s) <= max_len else s[:max_len] + "…"
    except Exception:  # noqa: BLE001
        return str(value)[:max_len]


def _value_schema_type(value: Any) -> List[str]:
    """Best-effort Schema.org types for a Python value.

    Arrays report the union of their element types; typed nodes report @type.
    """
    if isinstance(value, bool):
        return ["Boolean"]
    if isinstance(value, (int, float)):
        return ["Number"]
    if isinstance(value, str):
        return ["Text"]
    if isinstance(value, list):
        if not value:
            return ["Array"]
        types: List[str] = []
        for item in value:
            for t in _value_schema_type(item):
                if t not in types:
                    types.append(t)
        return types or ["Array"]
    if isinstance(value, dict):
        types = node_types(value)
        if types:
            return [bare_type(t) for t in types]
        if "@id" in value:
            return ["@id-ref"]
        return ["Object"]
    return ["Unknown"]


def _type_specificity(t: str) -> int:
    """Rank how specific a type is for dedup (NewsArticle > Article > CreativeWork)."""
    return {
        "NewsArticle": 3,
        "Article": 2,
        "BlogPosting": 3,
        "WebPage": 2,
        "CreativeWork": 1,
        "Thing": 0,
    }.get(t, 2)


class SchemaOrgValidator:
    """Validates structured data items against the Schema.org vocabulary."""

    def __init__(self, vocab: Optional[Vocabulary] = None):
        self.vocab = vocab or VocabularyProvider.get()

    # ------------------------------------------------------------------
    def validate(
        self,
        blocks: List[JsonLdBlock],
        source_map: Optional[SourceMap] = None,
    ) -> StructuredDataResult:
        """Validate all extracted blocks; returns the full result model."""
        ctx = Context(vocab=self.vocab, findings=[], source_map=source_map)

        # Build the top-level item registry first.
        for block in blocks:
            if not block.parsed:
                continue
            for item in block.entities:
                ctx.items[(block.index, item.index)] = item
                # record property names for the item detail view
                node = self._find_raw_node(block, item)
                if node:
                    item.properties = [
                        k for k in node.keys() if not k.startswith("@")
                    ]

        for block in blocks:
            ctx.block_index = block.index
            if not block.parsed:
                continue
            for item in block.entities:
                try:
                    self._validate_item(ctx, item, block)
                except Exception as exc:  # noqa: BLE001 - never let one item kill the scan
                    ctx.add(
                        "ERROR",
                        "Validation could not complete for this item.",
                        item,
                        error_code="OTHER",
                        detail=f"{type(exc).__name__}: {exc}",
                    )

        # Single source of truth for counts.
        result = StructuredDataResult(
            status="PASS",
            blocks=blocks,
            items=[it for b in blocks for it in b.entities],
            findings=ctx.findings,
        )
        result.error_count = sum(1 for f in ctx.findings if f.severity == "ERROR")
        result.warning_count = sum(1 for f in ctx.findings if f.severity == "WARNING")
        result.info_count = sum(1 for f in ctx.findings if f.severity == "INFO")
        result.item_count = len(result.items)
        result.status = (
            "FAIL" if result.error_count else ("WARN" if result.warning_count else "PASS")
        )
        # Per-item counts from the SAME findings.
        for item in result.items:
            item.errors = sum(
                1
                for f in ctx.findings
                if f.item_type == item.type
                and f.item_index == item.index
                and f.severity == "ERROR"
            )
            item.warnings = sum(
                1
                for f in ctx.findings
                if f.item_type == item.type
                and f.item_index == item.index
                and f.severity == "WARNING"
            )
            item.infos = sum(
                1
                for f in ctx.findings
                if f.item_type == item.type
                and f.item_index == item.index
                and f.severity == "INFO"
            )
            item.status = "FAIL" if item.errors else ("WARN" if item.warnings else "PASS")
        return result

    # ------------------------------------------------------------------
    def _emit_error(
        self,
        ctx: Context,
        code: str,
        message: str,
        item: DetectedItem,
        property: Optional[str] = None,
        json_path: Optional[str] = None,
        expected: Optional[str] = None,
        actual: Optional[str] = None,
        detail: Optional[str] = None,
        dedup_key: Optional[str] = None,
    ) -> bool:
        """Emit an error, deduplicating identical errors across the document.

        Identical errors (same code + property) on related types collapse to
        the MOST SPECIFIC type: e.g. the same ``publisher: {id:""}`` flaw in an
        Article block and a NewsArticle block is reported once, on NewsArticle.

        Returns True if the error was actually emitted (not deduplicated away).
        """
        code_prop = dedup_key or (code, property or "")
        # Look for an existing finding with the same code+property on ANY type.
        existing: Optional[ValidationFinding] = None
        for f in ctx.findings:
            if (
                f.severity == "ERROR"
                and f.error_code == code
                and (f.property or "") == (property or "")
            ):
                existing = f
                break

        if existing is not None:
            # Same error already reported. If this item's type is MORE specific
            # than the existing one, re-attribute to this item (drop the old).
            existing_type = existing.item_type or ""
            if _type_specificity(item.type) > _type_specificity(existing_type):
                existing.item_type = item.type
                existing.item_index = item.index
                existing.block_index = item.block_index
                existing.json_path = json_path or existing.json_path
                if source := _resolve_source(ctx, json_path, item.block_index):
                    existing.source = source
            return False

        source = _resolve_source(ctx, json_path, item.block_index)
        ctx.add(
            "ERROR",
            message,
            item,
            property=property,
            json_path=json_path,
            source=source,
            error_code=code,
            expected=expected,
            actual=actual,
            detail=detail,
        )
        return True

    def _emit_warning(
        self,
        ctx: Context,
        code: str,
        message: str,
        item: DetectedItem,
        property: Optional[str] = None,
        json_path: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        source = _resolve_source(ctx, json_path, item.block_index)
        ctx.add(
            "WARNING",
            message,
            item,
            property=property,
            json_path=json_path,
            source=source,
            error_code=code,
            detail=detail,
        )

    # ------------------------------------------------------------------
    def _validate_item(self, ctx: Context, item: DetectedItem, block: JsonLdBlock) -> None:
        node = self._find_raw_node(block, item)
        if node is None:
            return
        tname = item.type
        type_known = self.vocab.type_exists(tname)
        base = item.json_path

        if not type_known:
            self._emit_error(
                ctx,
                "INVALID_ITEMTYPE",
                f"The type <i>{tname}</i> is not a type defined by the recognised schema (e.g. schema.org).",
                item,
                property="@type",
                json_path=self._path(base, "@type"),
                expected="a type defined by schema.org",
                actual=tname,
            )
            return

        # validate @type list references
        raw_type = node.get("@type")
        if isinstance(raw_type, list):
            for t in raw_type:
                if isinstance(t, str) and not self.vocab.type_exists(bare_type(t)):
                    self._emit_error(
                        ctx,
                        "INVALID_ITEMTYPE",
                        f"The type <i>{bare_type(t)}</i> is not a type defined by the recognised schema (e.g. schema.org).",
                        item,
                        property="@type",
                        json_path=self._path(base, "@type"),
                        expected="a type defined by schema.org",
                        actual=bare_type(t),
                    )

        # properties
        for key, value in node.items():
            if key.startswith("@"):
                continue
            self._validate_property(ctx, item, base, key, value)

    def _find_raw_node(self, block: JsonLdBlock, item: DetectedItem) -> Optional[Dict[str, Any]]:
        """Resolve an item's json_path back to the raw parsed node."""
        if block.raw is None:
            return None
        path = item.json_path or ""
        if path.isdigit():
            nodes = self._split_graph_of(block.raw)
            try:
                idx = int(path)
                if 0 <= idx < len(nodes):
                    return nodes[idx]
            except (ValueError, IndexError):
                return None
            return None
        node = self._walk_path(block.raw, path)
        return node if isinstance(node, dict) else None

    def _split_graph_of(self, raw: Any) -> List[Dict[str, Any]]:
        from ..parsers.jsonld_parser import JsonLdParser

        return JsonLdParser().split_graph(raw)

    def _walk_path(self, raw: Any, path: str) -> Optional[Dict[str, Any]]:
        """Walk a dotted json_path (with [idx] segments) through raw JSON."""
        segs = re.findall(r"[^.\[\]]+", path)
        if not segs:
            return None
        head = segs[0]
        if head.isdigit():
            nodes = self._split_graph_of(raw)
            try:
                idx = int(head)
                node: Any = nodes[idx] if 0 <= idx < len(nodes) else None
            except (ValueError, IndexError):
                return None
        elif isinstance(raw, dict) and head in raw:
            node = raw[head]
        else:
            return None
        if node is None:
            return None
        for seg in segs[1:]:
            if seg.isdigit():
                if isinstance(node, list) and int(seg) < len(node):
                    node = node[int(seg)]
                elif isinstance(node, dict) and seg in node:
                    node = node[seg]
                else:
                    return None
            else:
                if isinstance(node, dict) and seg in node:
                    node = node[seg]
                else:
                    return None
        return node if isinstance(node, dict) else None

    # ------------------------------------------------------------------
    def _validate_property(
        self,
        ctx: Context,
        item: DetectedItem,
        base: str,
        key: str,
        value: Any,
        type_context: Optional[str] = None,
    ) -> None:
        prop_path = self._path(base, key)
        prop_source = _resolve_source(ctx, prop_path, item.block_index)
        # Validate against the effective type (nested node's own type when
        # validating an embedded object), but attribute to ``item``.
        tname = type_context or item.type

        if not self.vocab.property_exists(key, tname):
            # INVALID_PREDICATE / UNKNOWN_FIELD — the official message.
            self._emit_error(
                ctx,
                "UNKNOWN_FIELD",
                f"The property <i>{key}</i> is not recognised by the schema (e.g. schema.org) "
                f"for an object of type <i>{tname}</i>.",
                item,
                property=key,
                json_path=prop_path,
                expected="a property of the type or one of its parent types",
                actual=key,
            )
            return

        # value type vs declared ranges (warnings only — Schema.org is loose)
        ranges = self.vocab.property_ranges(key)
        if ranges:
            value_types = _value_schema_type(value)
            ok = False
            for vt in value_types:
                for rng in ranges:
                    rng_bare = bare_type(rng)
                    if self._value_matches_range(vt, rng_bare, value):
                        ok = True
                        break
                if ok:
                    break
            if not ok:
                self._emit_warning(
                    ctx,
                    "INVALID_OBJECT",
                    f"The value provided for <i>{key}</i> does not match any expected type.",
                    item,
                    property=key,
                    json_path=prop_path,
                    detail=(
                        f"Property '{key}' on '{tname}' expects {sorted({bare_type(r) for r in ranges})}, "
                        f"got {sorted(set(value_types))}."
                    ),
                )

        # nested typed objects get validated as children of THIS item
        self._validate_nested(ctx, item, base, key, value)

    def _value_matches_range(self, vt: str, rng: str, value: Any) -> bool:
        """True if a value plausibly satisfies a declared Schema.org range.

        Deliberately permissive: Schema.org is loose about coercions, and
        validator.schema.org does not error on integer widths, ISO date
        strings, or URL strings standing in for Thing references.
        """
        if vt == rng:
            return True
        if rng in ("Text", "URL", "CssSelectorType") and vt == "Text":
            return True
        if rng == "Number" and vt in ("Integer", "Float"):
            return True
        if rng == "Integer" and vt in ("Number", "Float"):
            return True  # loose
        # numeric pixel/measurement values satisfy Distance/QuantitativeValue
        if rng in ("Distance", "QuantitativeValue") and vt in ("Number", "Integer", "Float"):
            return True
        # numeric strings satisfy Number/Distance/QuantitativeValue
        if (
            isinstance(value, str)
            and self._looks_numeric(value)
            and rng in ("Number", "Integer", "Distance", "QuantitativeValue", "Float")
        ):
            return True
        # ISO date/time strings (and bare years) satisfy Date/DateTime/Time
        if (
            rng in ("Date", "DateTime", "Time")
            and vt == "Text"
            and isinstance(value, str)
            and self._looks_like_datetime(value)
        ):
            return True
        # URL-like strings satisfy Thing/URL-typed ranges (a reference)
        if (
            vt == "Text"
            and isinstance(value, str)
            and rng in ("Thing", "URL", "CreativeWork", "Person", "Organization", "Place", "Intangible", "Event", "AdministrativeArea", "GeoShape", "Country", "Language")
            and value.strip().lower().startswith(("http://", "https://"))
        ):
            return True
        # @id references match any object range
        if vt == "@id-ref" and rng not in ("Text", "Number", "Boolean", "Date", "DateTime", "Time"):
            return True
        # type-inheritance check against range type
        if vt != "Text" and vt != "Number" and not vt.startswith("@"):
            if self.vocab.type_exists(vt) and self.vocab.type_exists(rng):
                return self.vocab.is_subtype_of(vt, rng)
        return False

    @staticmethod
    def _looks_numeric(value: str) -> bool:
        import re as _re

        return bool(_re.fullmatch(r"[-+]?\d+(\.\d+)?", value.strip()))

    @staticmethod
    def _looks_like_datetime(value: str) -> bool:
        import datetime as _dt

        v = value.strip()
        if v.isdigit() and len(v) == 4:
            # bare year (e.g. "1948")
            return 1000 <= int(v) <= 9999
        try:
            _dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
            return True
        except ValueError:
            pass
        try:
            _dt.date.fromisoformat(v[:10])
            return True
        except ValueError:
            return False

    # ------------------------------------------------------------------
    def _validate_nested(
        self,
        ctx: Context,
        parent_item: DetectedItem,
        base: str,
        key: str,
        value: Any,
    ) -> None:
        """Validate nested typed nodes, attributing errors to the parent item.

        This is the key fix: a bad property on a nested object (e.g.
        ``publisher: {"id": ""}``) is reported as an error of the TOP-LEVEL item
        that contains it (NewsArticle/Article), NOT as a phantom separate item.
        """
        if isinstance(value, dict):
            if "@value" in value or ("@id" in value and "@type" not in value):
                return
            if is_typed_node(value):
                self._validate_embedded_node(ctx, parent_item, base, key, value, None)
        elif isinstance(value, list):
            for idx, v in enumerate(value):
                if isinstance(v, dict) and is_typed_node(v):
                    self._validate_embedded_node(ctx, parent_item, base, key, v, idx)
                elif isinstance(v, dict) and "@graph" in v:
                    g = v["@graph"]
                    glist = g if isinstance(g, list) else [g]
                    for gnode in glist:
                        if isinstance(gnode, dict) and is_typed_node(gnode):
                            self._validate_embedded_node(ctx, parent_item, base, key, gnode, idx)

    def _validate_embedded_node(
        self,
        ctx: Context,
        parent: DetectedItem,
        base: str,
        key: str,
        node: Dict[str, Any],
        idx: Optional[int] = None,
    ) -> None:
        """Validate a nested typed node.

        Property validity is checked against the NESTED node's own type (e.g.
        ``position`` is valid on ListItem), while the finding is ATTRIBUTED to
        the parent top-level item (e.g. BreadcrumbList) so per-item counts and
        the global count stay consistent with the official validator.
        """
        seg = f"{key}[{idx}]" if idx is not None else key
        child_path = f"{base}.{seg}"
        types = node_types(node)
        ctype = bare_type(types[0]) if types else "Unknown"

        if not self.vocab.type_exists(ctype):
            self._emit_error(
                ctx,
                "INVALID_ITEMTYPE",
                f"The type <i>{ctype}</i> is not a type defined by the recognised schema (e.g. schema.org).",
                parent,
                property="@type",
                json_path=self._path(child_path, "@type"),
                expected="a type defined by schema.org",
                actual=ctype,
            )
            return

        # Validate the nested node's properties against ITS OWN type, but
        # attribute findings to the parent item.
        for k, v in node.items():
            if k.startswith("@"):
                continue
            self._validate_property(ctx, parent, child_path, k, v, type_context=ctype)

    def _path(self, base: str, *parts: str) -> str:
        if not base:
            return ".".join(parts)
        return f"{base}.{'.'.join(parts)}"

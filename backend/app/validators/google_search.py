"""Google Search structured-data eligibility validator.

Runs AFTER Schema.org validation, over the SAME extracted blocks/items, and
produces a completely separate ``GoogleSearchResult``. This keeps the two
concerns cleanly split (requirement #11):

- ``SchemaOrgValidator``  -> "Is this valid Schema.org markup?"
- ``GoogleSearchValidator`` -> "Is this markup eligible for a Google Search
  rich result, per Google's publicly documented requirements?"

A Schema.org-valid item is NOT automatically Google Search eligible, and this
validator never claims to reproduce Google's internal, proprietary ranking or
eligibility algorithm — only the publicly documented required / recommended
property lists (see ``google_rules.py``).
"""
from __future__ import annotations

import datetime as _dt
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from ..models.schemas import (
    DetectedItem,
    GoogleFinding,
    GoogleItemResult,
    GoogleSearchResult,
    JsonLdBlock,
    SourceLocation,
)
from ..parsers.jsonld_parser import JsonLdParser, bare_type, node_types
from ..parsers.sourcemap import SourceMap
from .google_rules import (
    PAYWALL_HOST_FALLBACK_TYPES,
    PAYWALLED_CONTENT_RULE,
    GoogleTypeRule,
    get_rule,
)
from .vocabulary import Vocabulary, VocabularyProvider

_URL_RE = re.compile(r"^https?://[^\s]+$", re.I)
_PRICE_RE = re.compile(r"^\d+(\.\d{1,4})?$")


# ---------------------------------------------------------------------------
# Raw-node lookup helpers (mirrors SchemaOrgValidator's private walkers, kept
# standalone here to avoid coupling the two validators together).
# ---------------------------------------------------------------------------
def _split_graph_of(raw: Any) -> List[Dict[str, Any]]:
    return JsonLdParser().split_graph(raw)


def _walk_path(raw: Any, path: str) -> Optional[Dict[str, Any]]:
    segs = re.findall(r"[^.\[\]]+", path)
    if not segs:
        return None
    head = segs[0]
    if head.isdigit():
        nodes = _split_graph_of(raw)
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
            else:
                return None
        elif isinstance(node, dict) and seg in node:
            node = node[seg]
        else:
            return None
    return node if isinstance(node, dict) else None


def find_raw_node(block: JsonLdBlock, item: DetectedItem) -> Optional[Dict[str, Any]]:
    if block.raw is None:
        return None
    path = item.json_path or ""
    if path.isdigit():
        nodes = _split_graph_of(block.raw)
        try:
            idx = int(path)
            return nodes[idx] if 0 <= idx < len(nodes) else None
        except (ValueError, IndexError):
            return None
    node = _walk_path(block.raw, path)
    return node if isinstance(node, dict) else None


def _get_path(node: Dict[str, Any], dotted: str) -> Any:
    """Resolve a simple dotted path ('offers.price') against a raw node.

    If an intermediate value is a list, the first element is used (Google
    docs generally describe the singular case; arrays of offers etc. are
    valid but we check the first entry as a representative sample).
    """
    cur: Any = node
    for part in dotted.split("."):
        if isinstance(cur, list):
            cur = cur[0] if cur else None
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    if isinstance(cur, list):
        return cur[0] if cur else None
    return cur


def _present(node: Dict[str, Any], dotted: str) -> bool:
    val = _get_path(node, dotted)
    if val is None:
        return False
    if isinstance(val, str) and not val.strip():
        return False
    if isinstance(val, (list, dict)) and len(val) == 0:
        return False
    return True


def _looks_like_url(value: Any) -> bool:
    return isinstance(value, str) and bool(_URL_RE.match(value.strip()))


def _looks_like_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    v = value.strip()
    try:
        _dt.date.fromisoformat(v[:10])
        return True
    except ValueError:
        return False


def _looks_like_datetime(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    v = value.strip()
    try:
        _dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
        return True
    except ValueError:
        return _looks_like_date(value)


def _looks_like_price(value: Any) -> bool:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value >= 0
    if isinstance(value, str):
        return bool(_PRICE_RE.match(value.strip()))
    return False


def _looks_like_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value.strip())
            return True
        except ValueError:
            return False
    return False


def _looks_like_boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, str):
        return value.strip().lower() in ("true", "false")
    return False


def _is_webpage_element(node: Any) -> bool:
    if not isinstance(node, dict):
        return False
    return any(bare_type(t) == "WebPageElement" for t in node_types(node))


def _check_format(kind: str, value: Any) -> bool:
    """Best-effort, deliberately non-aggressive format check (req #7)."""
    if kind == "url":
        return _looks_like_url(value)
    if kind == "date":
        return _looks_like_date(value)
    if kind == "datetime":
        return _looks_like_datetime(value)
    if kind == "price":
        return _looks_like_price(value)
    if kind == "number":
        return _looks_like_number(value)
    if kind == "image":
        if isinstance(value, str):
            return _looks_like_url(value)
        if isinstance(value, dict):
            return _looks_like_url(value.get("url")) if value.get("url") else "@id" in value
        if isinstance(value, list):
            return all(_check_format("image", v) for v in value) if value else False
        return False
    return True  # "text" / "object" / "enum" — no aggressive check


class GoogleSearchValidator:
    """Applies the Google rule registry to already-extracted structured data."""

    def __init__(self, vocab: Optional[Vocabulary] = None):
        self.vocab = vocab or VocabularyProvider.get()

    def validate(
        self,
        blocks: List[JsonLdBlock],
        items: List[DetectedItem],
        source_map: Optional[SourceMap] = None,
    ) -> GoogleSearchResult:
        result = GoogleSearchResult()
        block_by_index = {b.index: b for b in blocks}

        for item in items:
            block = block_by_index.get(item.block_index)
            if block is None or not block.parsed:
                continue
            node = find_raw_node(block, item)
            if node is None:
                continue

            ancestors = sorted(self.vocab.ancestors(item.type)) if self.vocab.loaded else []
            rule = get_rule(item.type, ancestors)

            item_result = GoogleItemResult(item_type=item.type, item_index=item.index, block_index=item.block_index)

            if rule is None:
                item_result.support_status = "UNKNOWN" if not self.vocab.loaded or not self.vocab.type_exists(item.type) else "NOT_SUPPORTED"
                item_result.status = "NOT_APPLICABLE"
                item_result.note = (
                    "Valid Schema.org structured data, but not a Google Search "
                    "supported rich-result feature."
                    if item_result.support_status == "NOT_SUPPORTED"
                    else "Schema.org type not recognised, so Google Search support "
                    "could not be determined."
                )
                result.items.append(item_result)
                continue

            item_result.rich_result_type = rule.rich_result_name

            if rule.support == "DEPRECATED":
                item_result.support_status = "DEPRECATED"
                item_result.status = "NOT_APPLICABLE"
                item_result.eligible = False
                item_result.deprecated_message = rule.deprecated_message
                result.items.append(item_result)
                continue

            item_result.support_status = "SUPPORTED"
            findings = self._validate_item(rule, item, node, source_map)
            result.findings.extend(findings)
            item_result.errors = sum(1 for f in findings if f.severity == "ERROR")
            item_result.warnings = sum(1 for f in findings if f.severity == "WARNING")
            item_result.eligible = item_result.errors == 0
            item_result.status = "FAIL" if item_result.errors else ("WARN" if item_result.warnings else "PASS")
            result.items.append(item_result)

        # Paywalled content is a separate Google Search feature (not a
        # GOOGLE_TYPE_RULES entry — see google_rules.PAYWALLED_CONTENT_RULE)
        # that can coexist with whatever rule/eligibility was computed above
        # for the SAME item, so it is applied as its own pass rather than
        # folded into the loop above. Kept decoupled per requirement #11:
        # Google eligibility for one feature must never be made dependent on
        # another feature's outcome.
        for item in items:
            block = block_by_index.get(item.block_index)
            if block is None or not block.parsed:
                continue
            node = find_raw_node(block, item)
            if node is None:
                continue
            ancestors = sorted(self.vocab.ancestors(item.type)) if self.vocab.loaded else []
            paywall = self._check_paywalled_content(item, node, ancestors, source_map)
            if paywall is not None:
                p_item, p_findings = paywall
                result.items.append(p_item)
                result.findings.extend(p_findings)

        result.supported_count = sum(1 for it in result.items if it.support_status == "SUPPORTED")
        result.not_supported_count = sum(1 for it in result.items if it.support_status == "NOT_SUPPORTED")
        result.deprecated_count = sum(1 for it in result.items if it.support_status == "DEPRECATED")
        result.unknown_count = sum(1 for it in result.items if it.support_status == "UNKNOWN")
        result.eligible_count = sum(1 for it in result.items if it.eligible)
        result.error_count = sum(1 for f in result.findings if f.severity == "ERROR")
        result.warning_count = sum(1 for f in result.findings if f.severity == "WARNING")
        return result

    # ------------------------------------------------------------------
    def _validate_item(
        self,
        rule: GoogleTypeRule,
        item: DetectedItem,
        node: Dict[str, Any],
        source_map: Optional[SourceMap],
    ) -> List[GoogleFinding]:
        findings: List[GoogleFinding] = []

        for prop in rule.required:
            if not _present(node, prop):
                findings.append(
                    self._finding(
                        "ERROR",
                        "GOOGLE_MISSING_REQUIRED",
                        f'Missing field "{prop}" required for the {rule.rich_result_name} rich result.',
                        item,
                        prop,
                        rule.rich_result_name,
                        source_map,
                    )
                )

        for group in rule.required_one_of:
            if not any(_present(node, p) for p in group):
                choices = ", ".join(f'"{p}"' for p in group[:-1]) + f' or "{group[-1]}"' if len(group) > 1 else f'"{group[0]}"'
                findings.append(
                    self._finding(
                        "ERROR",
                        "GOOGLE_ONE_OF_MISSING",
                        f"Either {choices} should be specified for the {rule.rich_result_name} rich result.",
                        item,
                        "/".join(group),
                        rule.rich_result_name,
                        source_map,
                    )
                )

        for prop in rule.recommended:
            if not _present(node, prop):
                findings.append(
                    self._finding(
                        "WARNING",
                        "GOOGLE_MISSING_RECOMMENDED",
                        f'Missing recommended field "{prop}" for the {rule.rich_result_name} rich result.',
                        item,
                        prop,
                        rule.rich_result_name,
                        source_map,
                    )
                )

        for fmt in rule.formats:
            value = _get_path(node, fmt.prop)
            if value is None:
                continue  # absence is handled by required/recommended checks above
            if not _check_format(fmt.kind, value):
                findings.append(
                    self._finding(
                        "ERROR" if fmt.prop in rule.required or _dotted_root(fmt.prop) in rule.required else "WARNING",
                        "GOOGLE_INVALID_FORMAT",
                        f'Invalid {fmt.kind} format for "{fmt.prop}" ({rule.rich_result_name}).',
                        item,
                        fmt.prop,
                        rule.rich_result_name,
                        source_map,
                        heuristic=True,
                    )
                )

        return findings

    # ------------------------------------------------------------------
    def _check_paywalled_content(
        self,
        item: DetectedItem,
        node: Dict[str, Any],
        ancestors: List[str],
        source_map: Optional[SourceMap],
    ) -> Optional[Tuple[GoogleItemResult, List[GoogleFinding]]]:
        """Google's "Paywalled content" feature.

        Not a Schema.org @type — expressed as ``isAccessibleForFree`` +
        ``hasPart``/``WebPageElement``/``cssSelector`` nested inside a
        CreativeWork-family node (google_rules.PAYWALLED_CONTENT_RULE).
        Returns None when the item isn't a CreativeWork, or doesn't use the
        feature at all (no ``hasPart`` WebPageElement entries) — we only
        ever report on markup that is actually present, never manufacture a
        claim for a node that never used the feature.
        """
        is_creative_work = (
            item.type == PAYWALLED_CONTENT_RULE.host_ancestor
            or PAYWALLED_CONTENT_RULE.host_ancestor in ancestors
            or (not ancestors and item.type in PAYWALL_HOST_FALLBACK_TYPES)
        )
        if not is_creative_work:
            return None

        raw_has_part = node.get("hasPart")
        if raw_has_part is None:
            return None
        is_list = isinstance(raw_has_part, list)
        parts = raw_has_part if is_list else [raw_has_part]
        elements = [(idx, p) for idx, p in enumerate(parts) if _is_webpage_element(p)]
        if not elements:
            return None  # hasPart is used for something else -> not this feature

        findings: List[GoogleFinding] = []
        rich_name = PAYWALLED_CONTENT_RULE.rich_result_name

        for prop in PAYWALLED_CONTENT_RULE.required_host:
            if not _present(node, prop):
                findings.append(
                    self._finding(
                        "ERROR",
                        "GOOGLE_MISSING_REQUIRED",
                        f'Missing field "{prop}" required for the {rich_name} feature.',
                        item,
                        prop,
                        rich_name,
                        source_map,
                    )
                )
            elif not _looks_like_boolean(node.get(prop)):
                findings.append(
                    self._finding(
                        "ERROR",
                        "GOOGLE_INVALID_FORMAT",
                        f'Invalid boolean value for "{prop}" ({rich_name}).',
                        item,
                        prop,
                        rich_name,
                        source_map,
                        heuristic=True,
                    )
                )

        for idx, part in elements:
            base = f"hasPart[{idx}]" if is_list else "hasPart"
            for prop in PAYWALLED_CONTENT_RULE.required_part_props:
                if not _present(part, prop):
                    findings.append(
                        self._finding(
                            "ERROR",
                            "GOOGLE_MISSING_REQUIRED",
                            f'Missing field "{prop}" required for the {rich_name} feature.',
                            item,
                            f"{base}.{prop}",
                            rich_name,
                            source_map,
                        )
                    )
                    continue
                value = part.get(prop)
                valid = (
                    _looks_like_boolean(value)
                    if prop == "isAccessibleForFree"
                    else (
                        (isinstance(value, str) and value.strip())
                        or (isinstance(value, list) and value and all(isinstance(v, str) and v.strip() for v in value))
                    )
                )
                if not valid:
                    findings.append(
                        self._finding(
                            "ERROR",
                            "GOOGLE_INVALID_FORMAT",
                            f'Invalid value for "{prop}" ({rich_name}).',
                            item,
                            f"{base}.{prop}",
                            rich_name,
                            source_map,
                            heuristic=True,
                        )
                    )

        errors = sum(1 for f in findings if f.severity == "ERROR")
        warnings = sum(1 for f in findings if f.severity == "WARNING")
        item_result = GoogleItemResult(
            item_type=PAYWALLED_CONTENT_RULE.required_part_type,
            item_index=item.index,
            block_index=item.block_index,
            support_status="SUPPORTED",
            rich_result_type=rich_name,
            errors=errors,
            warnings=warnings,
            eligible=errors == 0,
            status="FAIL" if errors else ("WARN" if warnings else "PASS"),
        )
        return item_result, findings

    def _finding(
        self,
        severity: str,
        code: str,
        message: str,
        item: DetectedItem,
        prop: str,
        rich_result_type: str,
        source_map: Optional[SourceMap],
        heuristic: bool = False,
    ) -> GoogleFinding:
        json_path = f"{item.json_path}.{prop}" if item.json_path else prop
        source = _resolve_source(source_map, json_path, item.block_index)
        return GoogleFinding(
            id=uuid.uuid4().hex[:12],
            severity=severity,
            category="GOOGLE_SEARCH_ERROR" if severity == "ERROR" else "GOOGLE_SEARCH_WARNING",
            code=code,
            message=message,
            property=prop,
            json_path=json_path,
            item_type=item.type,
            item_index=item.index,
            block_index=item.block_index,
            rich_result_type=rich_result_type,
            heuristic=heuristic,
            source=source,
        )


def _dotted_root(path: str) -> str:
    return path.split(".", 1)[0]


def _resolve_source(sm: Optional[SourceMap], json_path: str, block_index: int) -> Optional[SourceLocation]:
    if sm is None or not json_path:
        return None
    path = json_path.lstrip("$.")
    stripped = path
    if "." in path:
        head, rest = path.split(".", 1)
        if head.isdigit():
            stripped = rest
    props = sm.block_props.get(block_index, {})
    pr = props.get(path) or props.get(stripped) or sm.locate_any(stripped)
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

"""JSON-LD structural parser.

Walks the parsed JSON-LD structure and identifies typed nodes:

- top-level arrays
- @graph (top-level and nested)
- arrays of nodes anywhere in the document
- @id references (never treated as an "id" property)
- @value / @language / @list / @set / @index containers
- context detection

We walk the *typed-node* structure the way the Schema.org validator does —
unknown keywords and unknown properties are preserved, not dropped.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple, Union

JsonValue = Union[Dict[str, Any], List[Any], str, float, int, bool, None]

KEYWORDS = {
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
}

SCHEMA_CONTEXT_RE = re.compile(r"https?://schema\.org", re.I)


def is_typed_node(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if "@type" in value:
        t = value["@type"]
        return isinstance(t, (str, list)) and len(t) > 0
    return "@id" in value


def node_types(value: Dict[str, Any]) -> List[str]:
    t = value.get("@type")
    if isinstance(t, str):
        return [t]
    if isinstance(t, list):
        return [x for x in t if isinstance(x, str)]
    return []


def bare_type(t: str) -> str:
    """'schema:NewsArticle' -> 'NewsArticle'."""
    if ":" in t and not t.startswith("http"):
        return t.split(":", 1)[1]
    if "/" in t:
        return t.rsplit("/", 1)[-1]
    return t


class JsonLdParser:
    """Splits a parsed JSON-LD block into top-level typed nodes."""

    @staticmethod
    def context_of(value: Any) -> Optional[str]:
        if isinstance(value, dict):
            ctx = value.get("@context")
            if isinstance(ctx, str):
                return ctx
            if isinstance(ctx, dict):
                for v in ctx.values():
                    if isinstance(v, str) and SCHEMA_CONTEXT_RE.search(v):
                        return v
        return None

    def split_graph(self, raw: Any) -> List[Dict[str, Any]]:
        """Return a list of top-level typed nodes from any JSON-LD block."""
        if isinstance(raw, list):
            return [n for n in raw if isinstance(n, dict) and is_typed_node(n)]
        if not isinstance(raw, dict):
            return []
        if "@graph" in raw:
            g = raw["@graph"]
            if isinstance(g, list):
                return [n for n in g if isinstance(n, dict) and is_typed_node(n)]
            if isinstance(g, dict):
                return [g] if is_typed_node(g) else []
        if is_typed_node(raw):
            return [raw]
        return []

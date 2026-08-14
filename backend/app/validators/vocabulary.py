"""Schema.org vocabulary service.

Loads the OFFICIAL Schema.org vocabulary (schema.org's own
schemaorg-current-https.jsonld dump) into memory, and exposes:

- known type names + inheritance (subClassOf chains)
- known properties + domains + ranges
- property existence checks that account for inheritance
- type-knowledge queries

A local copy of the vocabulary JSON-LD is bundled under app/vocab/ so the
service never depends on a live network call at runtime (the validator works
offline once installed). If the local file is missing, we fall back to the
network copy with a short timeout, then cache it to disk.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ..config import SCHEMAORG_URL, VOCAB_CACHE_FILE, VOCAB_DIR, VOCAB_META_FILE

logger = logging.getLogger(__name__)

# Types we treat as "action" types for a few heuristic checks (never hardcoded
# into validation; used only for reporting).
_ACTION_TYPES = {"Action", "TradeAction", "SearchAction", "InteractionCounter"}


class Vocabulary:
    """In-memory Schema.org vocabulary."""

    def __init__(self) -> None:
        self._types: Dict[str, Dict[str, Any]] = {}  # name -> node
        self._properties: Dict[str, Dict[str, Any]] = {}  # name -> node
        self._type_parents: Dict[str, Set[str]] = {}
        self._type_children: Dict[str, Set[str]] = {}
        self._loaded = False
        self._load_error: Optional[str] = None

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    def load(self, force: bool = False) -> bool:
        """Load the vocabulary; returns True on success."""
        if self._loaded and not force:
            return True
        data = self._read_cache_or_network()
        if data is None:
            self._loaded = False
            return False
        self._build_index(data)
        self._loaded = True
        return True

    def _read_cache_or_network(self) -> Optional[Dict[str, Any]]:
        if VOCAB_CACHE_FILE.exists():
            try:
                return json.loads(VOCAB_CACHE_FILE.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not read vocabulary cache: %s", exc)
        try:
            import httpx

            resp = httpx.get(SCHEMAORG_URL, timeout=15.0, follow_redirects=True)
            resp.raise_for_status()
            data = resp.json()
            VOCAB_DIR.mkdir(parents=True, exist_ok=True)
            VOCAB_CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            VOCAB_META_FILE.write_text(
                json.dumps({"source": SCHEMAORG_URL, "fetched_at": time.time()}, ensure_ascii=False),
                encoding="utf-8",
            )
            return data
        except Exception as exc:  # noqa: BLE001
            self._load_error = f"Vocabulary could not be loaded: {exc}"
            logger.error(self._load_error)
            return None

    def _build_index(self, data: Dict[str, Any]) -> None:
        self._types = {}
        self._properties = {}
        self._type_parents = {}
        self._type_children = {}
        graphs = data.get("@graph", [])
        # External ontologies (gs1:, bibo:, fibo-*, cmns-*, lcc-*, unece:,
        # dcat:, dctype:, void:) define classes with the same bare names as
        # Schema.org's own. Always prefer the schema: entry so inheritance is
        # correct; only use an external entry when Schema.org lacks the name.
        def prefer(existing: Optional[Dict[str, Any]], candidate: Dict[str, Any], nid: str) -> Dict[str, Any]:
            if existing is None:
                return candidate
            if nid.startswith("schema:"):
                return candidate
            if existing.get("@id", "").startswith("schema:"):
                return existing
            return candidate

        for node in graphs:
            if not isinstance(node, dict):
                continue
            ntype = node.get("@type")
            nid = node.get("@id", "")
            if ntype == "rdfs:Class":
                bare = self._bare(nid)
                self._types[bare] = prefer(self._types.get(bare), node, nid)
            elif ntype == "rdf:Property":
                bare = self._bare(nid)
                self._properties[bare] = prefer(self._properties.get(bare), node, nid)
        # Build inheritance edges.
        for name, node in self._types.items():
            parents: Set[str] = set()
            sub = node.get("rdfs:subClassOf")
            for entry in sub if isinstance(sub, list) else [sub]:
                if isinstance(entry, dict):
                    ref = entry.get("@id")
                    if ref:
                        parents.add(self._bare(ref))
            self._type_parents[name] = parents
            for p in parents:
                self._type_children.setdefault(p, set()).add(name)

    @staticmethod
    def _bare(name: str) -> str:
        """'schema:NewsArticle' -> 'NewsArticle'; full URIs keep their tail."""
        if ":" in name and not name.startswith("http"):
            return name.split(":", 1)[1]
        if "/" in name:
            return name.rsplit("/", 1)[-1]
        return name

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def type_exists(self, name: str) -> bool:
        return name in self._types

    def is_action_type(self, name: str) -> bool:
        return name in _ACTION_TYPES or any(
            a in _ACTION_TYPES for a in self.ancestors(name)
        )

    def ancestors(self, name: str) -> Set[str]:
        seen: Set[str] = set()
        stack = list(self._type_parents.get(name, set()))
        while stack:
            p = stack.pop()
            if p in seen:
                continue
            seen.add(p)
            stack.extend(self._type_parents.get(p, set()))
        return seen

    def descendants(self, name: str) -> Set[str]:
        seen: Set[str] = set()
        stack = list(self._type_children.get(name, set()))
        while stack:
            c = stack.pop()
            if c in seen:
                continue
            seen.add(c)
            stack.extend(self._type_children.get(c, set()))
        return seen

    def is_subtype_of(self, child: str, parent: str) -> bool:
        if child == parent:
            return True
        return parent in self.ancestors(child)

    def type_info(self, name: str) -> Optional[Dict[str, Any]]:
        return self._types.get(name)

    def property_exists(self, name: str, on_type: Optional[str] = None) -> bool:
        """True if the property is defined by Schema.org, optionally scoped to
        a type (or any of its ancestors)."""
        if name not in self._properties:
            return False
        if on_type is None:
            return True
        doms = self.property_domains(name)
        if not doms:
            # Property with no declared domain applies anywhere.
            return True
        for dom in doms:
            if self.is_subtype_of(on_type, dom):
                return True
        return False

    def property_domains(self, name: str) -> Set[str]:
        node = self._properties.get(name)
        if not node:
            return set()
        doms: Set[str] = set()
        raw = node.get("schema:domainIncludes")
        for entry in raw if isinstance(raw, list) else [raw]:
            if isinstance(entry, dict) and entry.get("@id"):
                doms.add(self._bare(entry["@id"]))
        return doms

    def property_ranges(self, name: str) -> Set[str]:
        node = self._properties.get(name)
        if not node:
            return set()
        ranges: Set[str] = set()
        raw = node.get("schema:rangeIncludes")
        for entry in raw if isinstance(raw, list) else [raw]:
            if isinstance(entry, dict) and entry.get("@id"):
                ranges.add(self._bare(entry["@id"]))
        return ranges

    def all_types(self) -> List[str]:
        return sorted(self._types.keys())

    def all_properties(self) -> List[str]:
        return sorted(self._properties.keys())

    def type_comment(self, name: str) -> Optional[str]:
        node = self._types.get(name)
        if node:
            return node.get("rdfs:comment")
        return None

    def property_comment(self, name: str) -> Optional[str]:
        node = self._properties.get(name)
        if node:
            return node.get("rdfs:comment")
        return None


class VocabularyProvider:
    """Cached access to a shared Vocabulary instance."""

    _instance: Optional[Vocabulary] = None

    @classmethod
    def get(cls) -> Vocabulary:
        if cls._instance is None:
            cls._instance = Vocabulary()
            cls._instance.load()
        return cls._instance

"""JSON-LD → entity tree normalizer.

Walks parsed JSON-LD blocks and produces a flat list of detected items plus a
tree of nested entities, preserving:

- block index
- JSON path (e.g. "$.newsArticle.author[0]")
- @id (never renamed to "id")
- nested entities
- arrays of nodes
- LiveBlogPosting/liveBlogUpdate detection

Unknown types and unknown properties are preserved so the validator can report
them honestly (an unknown type is reported as such, not dropped).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..models.schemas import DetectedItem, JsonLdBlock
from .jsonld_parser import JsonLdParser, bare_type, is_typed_node, node_types

LIVE_BLOG_UPDATE_TYPES = {"liveBlogUpdate", "LiveBlogUpdate", "BlogPosting", "SocialMediaPosting"}
LIVE_BLOG_TYPES = {"LiveBlogPosting", "liveBlogPosting"}


@dataclass
class EntityTree:
    """A detected entity with its nested children."""

    type: str
    id: Optional[str]
    index: int
    block_index: int
    json_path: str
    node: Dict[str, Any]
    nested: List["EntityTree"] = field(default_factory=list)


@dataclass
class SimpleRange:
    """Minimal source range used when no property-level range exists."""

    html_line: int
    start_offset: int
    end_offset: int


class JsonLdNormalizer:
    """Turns extracted blocks into DetectedItem lists."""

    def __init__(self, parser: Optional[JsonLdParser] = None):
        self.parser = parser or JsonLdParser()

    def normalize_blocks(self, blocks: List[Any], source_map: Any = None) -> List[JsonLdBlock]:
        """Return JsonLdBlock models with entities filled in."""
        result: List[JsonLdBlock] = []
        for block in blocks:
            model = JsonLdBlock(
                index=block.index,
                parsed=block.parsed,
                malformed=block.malformed,
                error=block.error,
                error_detail=block.error_detail,
                json_error_line=block.json_error_line,
                json_error_column=block.json_error_column,
                html_start_line=block.script.start_line,
                html_end_line=block.script.end_line,
                text_start_line=block.script.text_start_line,
                raw=block.raw,
            )
            if block.parsed and block.raw is not None:
                trees = self._split_entities(block)
                for tree in trees:
                    model.entities.append(self._to_detected(tree, source_map))
            result.append(model)
        return result

    def _split_entities(self, block: Any) -> List[EntityTree]:
        nodes = self.parser.split_graph(block.raw)
        trees: List[EntityTree] = []
        for i, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            if not is_typed_node(node):
                continue
            trees.append(self._build_tree(node, i, block.index, str(i)))
        return trees

    def _build_tree(self, node: Dict[str, Any], index: int, block_index: int, json_path: str) -> EntityTree:
        types = node_types(node)
        primary = bare_type(types[0]) if types else "Unknown"
        eid = node.get("@id")
        if eid is not None and not isinstance(eid, str):
            eid = str(eid)
        tree = EntityTree(
            type=primary,
            id=eid,
            index=index,
            block_index=block_index,
            json_path=json_path,
            node=node,
            nested=[],
        )
        for key, value in node.items():
            if key.startswith("@"):
                continue
            self._collect_nested(tree, key, value)
        return tree

    def _collect_nested(self, parent: EntityTree, key: str, value: Any) -> None:
        is_list = isinstance(value, list)
        items = value if is_list else [value]
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            # A value-only or reference-only node ({"@value": ...} or {"@id": "..."})
            # is not a nested entity.
            if "@value" in item or ("@id" in item and "@type" not in item):
                continue
            seg = f"{key}[{idx}]" if is_list else key
            child_path = f"{parent.json_path}.{seg}"
            if not is_typed_node(item):
                if "@graph" in item:
                    g = item["@graph"]
                    glist = g if isinstance(g, list) else [g]
                    for gnode in glist:
                        if isinstance(gnode, dict) and is_typed_node(gnode):
                            child = self._build_tree(
                                gnode,
                                idx,
                                parent.block_index,
                                child_path,
                            )
                            parent.nested.append(child)
                continue
            child = self._build_tree(
                item,
                idx,
                parent.block_index,
                child_path,
            )
            parent.nested.append(child)

    def _to_detected(self, tree: EntityTree, source_map: Any) -> DetectedItem:
        pr = None
        if source_map is not None:
            # The item's own range: its @type value if present, else its first
            # property, else the block start.
            item_path = tree.json_path
            prop = None
            if "@type" in tree.node:
                prop = self._join(item_path, "@type")
            elif tree.node:
                first_key = next(iter(tree.node))
                prop = self._join(item_path, first_key)
            if prop:
                pr = source_map.locate(tree.block_index, prop) or source_map.locate_any(
                    prop.lstrip("0123456789.")
                )
            if pr is None:
                bl = source_map.block_locations.get(tree.block_index)
                if bl is not None:
                    pr = SimpleRange(
                        html_line=bl.text_start_line,
                        start_offset=bl.start_offset,
                        end_offset=bl.end_offset,
                    )
        item = DetectedItem(
            type=tree.type,
            id=tree.id,
            index=tree.index,
            block_index=tree.block_index,
            json_path=tree.json_path,
            source_start_line=pr.html_line if pr else 0,
            source_end_line=0,
        )
        if pr is not None:
            item.source_start_offset = pr.start_offset
            item.source_end_offset = pr.end_offset
            item.source_start_line = pr.html_line
        # source_end_line from the value end
        if pr is not None and source_map is not None and hasattr(source_map, "html_line_map"):
            _, end_line = source_map.html_line_map.line_col(pr.end_offset) if source_map.html_line_map else (0, 0)
            item.source_end_line = end_line
        return item

    @staticmethod
    def _join(parent: str, key: str) -> str:
        return f"{parent}.{key}" if parent else key

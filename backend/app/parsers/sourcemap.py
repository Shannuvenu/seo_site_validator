"""Source-aware JSON-LD mapping.

Builds a mapping from JSON paths (like $.newsArticle.author.@type) to exact
positions in the ORIGINAL HTML: line, column, and character offsets for both the
property key and the full value range. The mapping survives @graph, nested
objects, arrays, and multiple blocks.

Strategy (accurate over convenient):

1. Locate every JSON-LD script block in the HTML (line numbers + offsets).
2. For each block, run a location-aware JSON scanner that walks the *parsed*
   tree in document order while scanning the raw block text with a moving
   cursor. Every object key maps to (json_line, json_col); the value range
   start/end offsets are computed with a small JSON-aware value scanner.
3. JSON positions are translated to HTML positions via the block's absolute
   offset in the page.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .sourceloc import JsonLdBlockLocation, JsonLineScanner, LineMap, find_jsonld_blocks


@dataclass
class PropRange:
    """Exact range of one JSON property in the original HTML."""

    json_path: str
    property_name: str
    block_index: int
    json_line: int  # line within the JSON block text
    json_col: int  # column within that line
    html_line: int  # line in the original HTML
    html_col: int
    start_offset: int  # char offset of the property key in the HTML
    end_offset: int  # char offset just past the value
    value_start_offset: int  # char offset of the value's first char


@dataclass
class ValueRange:
    """Start/end of a value relative to its block text."""

    start: int
    end: int


class ValueScanner:
    """Computes the char range of a JSON value starting at an offset."""

    def __init__(self, text: str):
        self.text = text

    def value_end(self, start: int) -> int:
        text = self.text
        n = len(text)
        i = start
        if i >= n:
            return n
        if text[i] == '"':
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == '"':
                    return i + 1
                i += 1
            return n
        if text[i] in "[{":
            depth: List[str] = []
            in_str = False
            escape = False
            while i < n:
                c = text[i]
                if in_str:
                    if escape:
                        escape = False
                    elif c == "\\":
                        escape = True
                    elif c == '"':
                        in_str = False
                else:
                    if c == '"':
                        in_str = True
                    elif c in "[{":
                        depth.append(c)
                    elif c in "]}":
                        if depth:
                            depth.pop()
                            if not depth:
                                return i + 1
                i += 1
            return n
        while i < n:
            c = text[i]
            if c in ",}]":
                return i
            i += 1
        return n


class SourceMap:
    """Full source map for one page's structured data."""

    def __init__(self) -> None:
        self.block_locations: Dict[int, JsonLdBlockLocation] = {}
        self.block_props: Dict[int, Dict[str, PropRange]] = {}
        self.prop_locations: Dict[str, PropRange] = {}
        self.html: str = ""
        self.html_line_map: Optional[LineMap] = None

    def build(self, html: str) -> "SourceMap":
        self.html = html
        self.html_line_map = LineMap.build(html)
        blocks = find_jsonld_blocks(html)
        for b in blocks:
            idx = b.block_index
            self.block_locations[idx] = b
            scanner = JsonLineScanner(b.raw_text)
            scan = scanner.scan()
            block_props: Dict[str, PropRange] = {}
            # The JSON text begins right after the ">" of the script tag.
            script_open_end = self._open_end_rel(html, b.start_offset)
            json_text_offset = script_open_end
            raw_map = LineMap.build(b.raw_text)
            for path, (jline, jcol) in scan["paths"].items():
                # Translate JSON (line, col) to an absolute HTML offset by
                # adding the raw-text offset of that JSON position.
                raw_offset = raw_map.line_starts[jline - 1] + (jcol - 1)
                abs_offset = json_text_offset + raw_offset
                html_line, html_col = self.html_line_map.line_col(abs_offset)
                start_offset = abs_offset
                # find the value start/end within the raw text
                raw_vstart = raw_offset + self._value_start_rel(b.raw_text, raw_offset)
                vs = ValueScanner(b.raw_text)
                vend = vs.value_end(raw_vstart)
                pr = PropRange(
                    json_path=path,
                    property_name=path.rsplit(".", 1)[-1].split("[", 1)[0],
                    block_index=idx,
                    json_line=jline,
                    json_col=jcol,
                    html_line=html_line,
                    html_col=html_col,
                    start_offset=start_offset,
                    end_offset=json_text_offset + vend,
                    value_start_offset=json_text_offset + raw_vstart,
                )
                block_props[path] = pr
            self.block_props[idx] = block_props
            for path, pr in block_props.items():
                self.prop_locations.setdefault(path, pr)
        return self

    def _open_end_rel(self, html: str, block_start: int) -> int:
        """Absolute char offset of the end of the <script ...> open tag."""
        text = html[block_start:]
        m = re.compile(r">").search(text)
        return block_start + (m.start() + 1 if m else 0)

    def _value_start_rel(self, text: str, raw_start: int) -> int:
        """Offset from the property key start to the first value char."""
        i = raw_start
        n = len(text)
        # skip the quoted key and colon, then whitespace
        while i < n and text[i] != ":":
            i += 1
        if i < n:
            i += 1
        while i < n and text[i].isspace():
            i += 1
        return i - raw_start

    def locate(self, block_index: int, json_path: str) -> Optional[PropRange]:
        """Locate a property by path in a block; graph-prefixed paths like
        '0.headline' are normalized to block-relative 'headline'."""
        props = self.block_props.get(block_index, {})
        pr = props.get(json_path)
        if pr is None and "." in json_path:
            head, rest = json_path.split(".", 1)
            if head.isdigit():
                pr = props.get(rest)
        return pr

    def locate_any(self, json_path: str) -> Optional[PropRange]:
        """Locate a property in any block."""
        if json_path in self.prop_locations:
            return self.prop_locations[json_path]
        if "." in json_path:
            head, rest = json_path.split(".", 1)
            if head.isdigit() and rest in self.prop_locations:
                return self.prop_locations[rest]
        return None

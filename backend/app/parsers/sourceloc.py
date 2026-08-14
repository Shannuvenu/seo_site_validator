"""HTML source analysis helpers: line mapping and JSON-LD block location."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import json


@dataclass
class LineMap:
    """Line-numbering for a body of text."""

    line_starts: List[int] = field(default_factory=list)
    total_lines: int = 0

    @classmethod
    def build(cls, text: str) -> "LineMap":
        starts = [0]
        for m in re.finditer(r"\n", text):
            starts.append(m.start() + 1)
        return cls(line_starts=starts, total_lines=len(starts))

    def line_col(self, offset: int) -> Tuple[int, int]:
        """1-indexed (line, column) for a character offset."""
        starts = self.line_starts
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1, offset - starts[lo] + 1

    def line_text(self, text: str, line_no: int) -> str:
        if line_no < 1 or line_no > self.total_lines:
            return ""
        start = self.line_starts[line_no - 1]
        end = self.line_starts[line_no] - 1 if line_no < self.total_lines else len(text)
        return text[start:end]


SCRIPT_OPEN_RE = re.compile(
    r"<script\b(?P<attrs>[^>]*?)\btype\s*=\s*(['\"])(?P<typeval>.*?)\2[^>]*>",
    re.IGNORECASE,
)
CLOSING_SCRIPT_RE = re.compile(r"</script\s*>", re.IGNORECASE)


@dataclass
class JsonLdBlockLocation:
    """HTML source range of one JSON-LD script block."""

    block_index: int
    start_line: int
    end_line: int
    start_offset: int
    end_offset: int
    script_open_line: int = 0
    text_start_line: int = 0  # first line of the JSON text itself
    raw_text: str = ""
    script_line_text: str = ""


def find_jsonld_blocks(html: str) -> List[JsonLdBlockLocation]:
    """Locate every <script type="application/ld+json"> block in raw HTML.

    Returns block records with exact line numbers and character offsets into
    the original HTML. Handles the type attribute in any position within the
    script tag and any quoting style.
    """
    line_map = LineMap.build(html)
    blocks: List[JsonLdBlockLocation] = []
    pos = 0
    while True:
        m = SCRIPT_OPEN_RE.search(html, pos)
        if m is None:
            break
        typeval = m.group("typeval").strip().lower()
        if "ld+json" not in typeval:
            pos = m.end()
            continue
        open_end = m.end()
        end_m = CLOSING_SCRIPT_RE.search(html, open_end)
        if end_m is None:
            break
        raw_text = html[open_end:end_m.start()]
        if not raw_text.strip():
            pos = end_m.end()
            continue
        start_line, _ = line_map.line_col(m.start())
        open_line, _ = line_map.line_col(open_end)
        text_start_line, _ = line_map.line_col(open_end + (1 if html[open_end:open_end+1] == "\n" else 0))
        end_line, _ = line_map.line_col(end_m.end())
        blocks.append(
            JsonLdBlockLocation(
                block_index=len(blocks),
                start_line=start_line,
                end_line=end_line,
                start_offset=m.start(),
                end_offset=end_m.end(),
                script_open_line=open_line,
                text_start_line=text_start_line,
                raw_text=raw_text,
                script_line_text=line_map.line_text(html, start_line),
            )
        )
        pos = end_m.end()
    return blocks


class JsonLineScanner:
    """Maps JSON paths to (line, col) positions inside raw JSON text.

    We parse with json.loads for structure, then re-walk the *parsed* tree in
    document order while a moving cursor scans the raw text, so every property
    keeps its exact character position. Dicts preserve insertion order, which
    makes this reliable for JSON produced in document order.
    """

    def __init__(self, text: str):
        self.text = text
        self.line_map = LineMap.build(text)

    def line_col(self, offset: int) -> Tuple[int, int]:
        return self.line_map.line_col(offset)

    def _value_end(self, start: int) -> int:
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

    def scan(self) -> Dict[str, Any]:
        """Return {paths: {json_path: (line, col)}, raw: parsed}."""
        paths: Dict[str, Tuple[int, int]] = {}
        try:
            parsed = json.loads(self.text)
        except json.JSONDecodeError:
            return {"paths": {}, "raw": None}
        self._walk(parsed, "", paths, 0)
        return {"paths": paths, "raw": parsed}

    def _walk(self, node: Any, prefix: str, paths: Dict[str, Tuple[int, int]], cursor: int) -> int:
        """Walk node in document order, recording key positions.

        Returns the text cursor just past the value consumed, so callers can
        continue scanning for later elements at the right position.
        """
        if isinstance(node, dict):
            for k, v in node.items():
                pattern = re.compile(r'"' + re.escape(k) + r'"\s*:', re.DOTALL)
                m = pattern.search(self.text, cursor)
                if m:
                    line, col = self.line_col(m.start())
                    path = f"{prefix}.{k}" if prefix else k
                    paths[path] = (line, col)
                    vstart = m.end()
                    while vstart < len(self.text) and self.text[vstart].isspace():
                        vstart += 1
                    vend = self._value_end(vstart)
                    cursor = self._walk(v, path, paths, vstart)
                    if cursor <= vstart:
                        cursor = vend
                else:
                    path = f"{prefix}.{k}" if prefix else k
                    cursor = self._walk(v, path, paths, cursor)
            return cursor
        if isinstance(node, list):
            for idx, item in enumerate(node):
                if isinstance(item, (dict, list)):
                    cursor = self._walk(item, f"{prefix}[{idx}]", paths, cursor)
            return cursor
        return cursor

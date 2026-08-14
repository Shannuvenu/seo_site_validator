"""Source-aware JSON-LD extraction from raw HTML.

Every <script type="application/ld+json"> block is located in the original
source (line numbers + character offsets), its raw text is decoded with HTML
entity handling, and each block is parsed as JSON. Malformed blocks never abort
the scan: they are recorded with their JSON parse error location and all other
blocks still validate.
"""
from __future__ import annotations

import html as html_mod
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .sourceloc import JsonLdBlockLocation, find_jsonld_blocks


@dataclass
class ExtractedBlock:
    """One JSON-LD block with its source metadata and parse outcome."""

    index: int
    raw_text: str
    script: JsonLdBlockLocation
    parsed: bool = False
    malformed: bool = False
    error: Optional[str] = None
    error_detail: Optional[str] = None
    json_error_line: Optional[int] = None
    json_error_column: Optional[int] = None
    raw: Any = None
    context: Optional[str] = None


class JsonLdExtractor:
    """Extract and parse every JSON-LD block from a raw HTML string."""

    def __init__(self) -> None:
        pass

    def extract(self, html_text: str) -> List[ExtractedBlock]:
        blocks: List[ExtractedBlock] = []
        located = find_jsonld_blocks(html_text)
        for loc in located:
            raw_text = loc.raw_text
            cleaned = self._clean_text(raw_text)
            block = ExtractedBlock(
                index=loc.block_index,
                raw_text=raw_text,
                script=loc,
                context=None,
            )
            if not cleaned:
                block.malformed = True
                block.error = "Empty JSON-LD block"
                block.error_detail = "The script block contains no JSON."
                blocks.append(block)
                continue
            parsed = self._parse(cleaned)
            if parsed is None:
                block.malformed = True
                block.error = "Malformed JSON-LD"
                block.error_detail = self._malformed_detail(cleaned)
                block.json_error_line = self._last_json_error.lineno if self._last_json_error else None
                block.json_error_column = self._last_json_error.colno if self._last_json_error else None
            else:
                block.parsed = True
                block.raw = parsed
                block.context = self._context_of(parsed)
            blocks.append(block)
        return blocks

    def _clean_text(self, text: str) -> str:
        text = text.replace("\ufeff", "")
        text = html_mod.unescape(text)
        return text.strip()

    def _parse(self, text: str) -> Optional[Any]:
        self._last_json_error = None
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            self._last_json_error = exc
            salvaged = self._salvage(text)
            if salvaged is not None and salvaged != text:
                try:
                    return json.loads(salvaged)
                except json.JSONDecodeError:
                    return None
            return None

    def _salvage(self, text: str) -> Optional[str]:
        stripped = text.strip()
        if not stripped:
            return None
        candidate = self._strip_trailing_commas(stripped)
        if candidate != stripped:
            return candidate
        return None

    @staticmethod
    def _strip_trailing_commas(text: str) -> str:
        out: List[str] = []
        for ch in text:
            if ch in "]}":
                while out and out[-1] in " \t\r\n":
                    out.pop()
                if out and out[-1] == ",":
                    out.pop()
            out.append(ch)
        return "".join(out)

    def _malformed_detail(self, text: str) -> str:
        exc = self._last_json_error
        if exc is not None and isinstance(exc, json.JSONDecodeError):
            return f"JSONDecodeError at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        return "The block could not be parsed as JSON."

    @staticmethod
    def _context_of(value: Any) -> Optional[str]:
        if not isinstance(value, dict):
            return None
        ctx = value.get("@context")
        if isinstance(ctx, str):
            return ctx
        if isinstance(ctx, dict):
            for v in ctx.values():
                if isinstance(v, str) and "schema.org" in v:
                    return v
        return None

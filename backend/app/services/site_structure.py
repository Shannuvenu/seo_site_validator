"""Site Structure service: builds the section tree from a Quintype site's
config API (the authoritative source for section hierarchy on Deccan Herald /
Prajavani)."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx

from ..config import USER_AGENT
from ..models.schemas import SiteNode, SiteStructureResult

QUINTYPE_CONFIG_URLS = {
    "deccanherald": "https://www.deccanherald.com/api/v1/config",
    "prajavani": "https://www.prajavani.net/api/v1/config",
}


def normalize_site_name(name: str) -> str:
    name = (name or "").strip().lower()
    name = name.replace("www.", "").replace(".com", "").replace(".net", "").replace("_", "")
    name = name.replace("-", "").replace(" ", "")
    for key, url in QUINTYPE_CONFIG_URLS.items():
        if key in name or key.replace("deccanherald", "deccan-herald") in name:
            return key
    if name.startswith("deccan"):
        return "deccanherald"
    if name.startswith("prajavani"):
        return "prajavani"
    return name


def config_url_for(site: str) -> Optional[str]:
    return QUINTYPE_CONFIG_URLS.get(normalize_site_name(site))


class SiteStructureService:
    """Fetches and normalizes a Quintype section tree."""

    def __init__(self) -> None:
        self._cache: Dict[str, Dict[str, Any]] = {}

    async def fetch_config(self, site: str, force: bool = False) -> SiteStructureResult:
        url = config_url_for(site)
        if url is None:
            return SiteStructureResult(site=site, error=f"Unknown site '{site}'. Supported sites: Deccan Herald, Prajavani.")

        cached = self._cache.get(url)
        if cached and not force and time.time() - cached["at"] < 300:
            return cached["result"]

        try:
            async with httpx.AsyncClient(
                timeout=20.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            return SiteStructureResult(site=site, config_url=url, error=f"Failed to fetch config: {exc}")
        except Exception as exc:  # noqa: BLE001
            return SiteStructureResult(site=site, config_url=url, error=f"Failed to parse config: {exc}")

        result = self._build_tree(site, url, data)
        self._cache[url] = {"at": time.time(), "result": result}
        return result

    def _build_tree(self, site: str, config_url: str, data: Dict[str, Any]) -> SiteStructureResult:
        sections = self._collect_sections(data)
        result = SiteStructureResult(
            site=site,
            config_url=config_url,
            nodes=sections,
            node_count=len(sections),
            fetched_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        if sections:
            result.root = self._tree_of(sections)
        return result

    def _collect_sections(self, data: Dict[str, Any]) -> List[SiteNode]:
        """Gather all section nodes from the config JSON, deduplicating by id."""
        sections: Dict[str, SiteNode] = {}

        def add(node: Dict[str, Any], parent_id: Optional[str] = None) -> None:
            nid = str(node.get("_id", node.get("id", "")))
            if not nid:
                return
            name = node.get("name") or node.get("display_name") or node.get("title") or nid
            slug = node.get("slug") or node.get("url") or ""
            if nid in sections:
                # merge parent if we now know it
                if parent_id and not sections[nid].parent_id:
                    sections[nid].parent_id = parent_id
                return
            sections[nid] = SiteNode(
                section_id=nid,
                name=name,
                slug=slug,
                parent_id=parent_id,
                collection_type=node.get("collection_type"),
                display_name=node.get("display_name"),
            )

        def walk(value: Any, parent_id: Optional[str] = None) -> None:
            if isinstance(value, list):
                for item in value:
                    walk(item, parent_id)
            elif isinstance(value, dict):
                nid = str(value.get("_id", value.get("id", "")))
                if nid and ("name" in value or "slug" in value):
                    add(value, parent_id)
                    new_parent = nid
                else:
                    new_parent = parent_id
                for key, child in value.items():
                    if key in ("__v", "_id", "id", "name", "slug", "display_name", "collection_type"):
                        continue
                    walk(child, new_parent)

        # The config usually has a "sections" array; walk the whole payload anyway.
        walk(data.get("sections", data))
        return list(sections.values())

    def _tree_of(self, nodes: List[SiteNode]) -> SiteNode:
        by_id = {n.section_id: n for n in nodes}
        roots = [n for n in nodes if not n.parent_id or n.parent_id not in by_id]
        if not roots and nodes:
            roots = [nodes[0]]

        def attach(parent: SiteNode) -> None:
            parent.children = [
                n for n in nodes if n.parent_id == parent.section_id
            ]
            parent.children.sort(key=lambda n: n.name.lower())
            for c in parent.children:
                attach(c)

        # If there are multiple roots, wrap them in a virtual root.
        if len(roots) == 1:
            root = roots[0]
            attach(root)
            return root
        virtual = SiteNode(section_id="__root__", name="Site", slug="", parent_id=None)
        for r in roots:
            attach(r)
            virtual.children.append(r)
        virtual.children.sort(key=lambda n: n.name.lower())
        return virtual

    def _site_title(self, name: str) -> str:
        return {"deccanherald": "Deccan Herald", "prajavani": "Prajavani"}.get(
            normalize_site_name(name), "Site"
        )

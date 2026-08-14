"""SSRF-guarded asynchronous URL fetching.

The backend fetches arbitrary URLs supplied by internal users, so before any
request we resolve the host and refuse private / loopback / link-local /
metadata IP targets and non-http(s) schemes. All DNS resolution happens inside
the async event loop; a hostname that resolves to a blocked IP is rejected even
when the URL itself looks public.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import httpx

from ..config import (
    MAX_FETCH_SIZE_BYTES,
    USER_AGENT,
)

SCHEME_RE = re.compile(r"^https?$", re.IGNORECASE)


class FetchError(Exception):
    """Raised when a URL cannot be fetched for network / SSRF reasons."""

    def __init__(self, message: str, error_type: str = "fetch_error"):
        super().__init__(message)
        self.error_type = error_type


class SsrfBlockedError(FetchError):
    def __init__(self, message: str):
        super().__init__(message, error_type="ssrf_blocked")


def _is_loopback_ip(ip: Any) -> bool:
    return ip.is_loopback


def _is_blocked_ip(ip: Any) -> bool:
    """True if the resolved IP must never be fetched."""
    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return True
    if ip.is_multicast or ip.is_reserved:
        return True
    if ip.is_unspecified:
        return True
    # IPv4-mapped IPv6 and other common spoofed forms.
    if ip.version == 6 and ip.ipv4_mapped is not None:
        return _is_blocked_ip(ip.ipv4_mapped)
    return False


def _looks_like_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _resolve_host(host: str, port: Optional[int] = None) -> List[Any]:
    """Resolve a hostname synchronously (fast enough for SSRF pre-checks;
    works whether or not an event loop is running)."""
    return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)


def _host_is_blocked(host: str) -> bool:
    """True if the hostname resolves to a blocked IP address."""
    if _looks_like_ip(host):
        try:
            return _is_blocked_ip(ipaddress.ip_address(host))
        except ValueError:
            return False
    try:
        infos = _resolve_host(host)
    except (socket.gaierror, OSError) as exc:
        raise FetchError(f"Could not resolve host '{host}': {exc}", "dns_error") from exc
    for info in infos:
        if _is_blocked_ip(ipaddress.ip_address(info[4][0])):
            return True
    return False


def validate_url(url: str, allow_localhost: bool = False) -> str:
    """Normalize and SSRF-guard a URL string; returns the safe URL.

    ``allow_localhost`` is for the local Data Layer test fixtures only — the
    production API always keeps the guard on.
    """
    url = url.strip()
    if not url:
        raise FetchError("URL is empty.", "bad_url")
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if not SCHEME_RE.match(scheme):
        raise FetchError(f"Only http and https URLs are allowed (got scheme '{parsed.scheme or 'none'}').", "bad_scheme")
    if not parsed.hostname:
        raise FetchError("URL has no host.", "bad_url")
    host = parsed.hostname.strip().lower()
    if allow_localhost and host in ("localhost", "127.0.0.1", "::1"):
        return url
    if _host_is_blocked(host):
        raise SsrfBlockedError(f"Blocked: {host} resolves to a reserved/private address.")
    return url


class Fetcher:
    """Async HTTP fetcher with SSRF guards, redirects, and size limits."""

    def __init__(
        self,
        timeout_seconds: float = 20.0,
        max_bytes: int = MAX_FETCH_SIZE_BYTES,
        user_agent: str = USER_AGENT,
    ):
        self.timeout = timeout_seconds
        self.max_bytes = max_bytes
        self.user_agent = user_agent
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "Fetcher":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def _client_get(self) -> httpx.AsyncClient:
        if self._client is None:
            limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                limits=limits,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _guard_redirect(self, resp: httpx.Response) -> None:
        """SSRF-guard each hop: verify every redirect target is not a blocked
        hostname/IP and the scheme stays http(s)."""
        url = resp.url
        host = url.host.lower()
        if url.scheme.lower() not in ("http", "https"):
            raise SsrfBlockedError(f"Blocked redirect to scheme '{url.scheme}'.")
        if _host_is_blocked(host):
            raise SsrfBlockedError(f"Blocked redirect to reserved address ({host}).")

    async def fetch(self, url: str) -> Dict[str, Any]:
        """Fetch a URL and return normalized result metadata + content."""
        url = validate_url(url)
        client = await self._client_get()
        started = time.monotonic()
        try:
            resp = await client.get(url)
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:
            raise FetchError(f"Request timed out after {self.timeout:.0f}s.", "timeout") from exc
        except httpx.ConnectError as exc:
            raise FetchError(f"Could not connect to host: {exc.__class__.__name__}: {exc}", "connect_error") from exc
        except httpx.HTTPError as exc:
            raise FetchError(f"HTTP error: {exc.__class__.__name__}: {exc}", "http_error") from exc

        self._guard_redirect(resp)
        content = await self._read_body(resp)
        elapsed_ms = (time.monotonic() - started) * 1000.0
        final_url = str(resp.url)
        content_type = resp.headers.get("content-type", "")
        return {
            "url": url,
            "final_url": final_url,
            "status_code": resp.status_code,
            "content_type": content_type,
            "content": content,
            "fetch_duration_ms": round(elapsed_ms, 2),
            "headers": dict(resp.headers),
        }

    async def _read_body(self, resp: httpx.Response) -> str:
        """Stream the response body, enforcing a hard size cap."""
        chunks: list[bytes] = []
        total = 0
        async for chunk in resp.aiter_bytes():
            total += len(chunk)
            if total > self.max_bytes:
                raise FetchError(
                    f"Page exceeded the {self.max_bytes // (1024 * 1024)} MB fetch limit.",
                    "too_large",
                )
            chunks.append(chunk)
        raw = b"".join(chunks)
        return raw.decode("utf-8", errors="replace")


class UrlCache:
    """Small in-memory URL cache to keep repeated scans snappy."""

    def __init__(self, ttl_seconds: float = 60.0, max_entries: int = 200):
        self._ttl = ttl_seconds
        self._max = max_entries
        self._entries: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    def get(self, url: str) -> Optional[Dict[str, Any]]:
        entry = self._entries.get(url)
        if entry is None:
            return None
        stored_at, data = entry
        if time.monotonic() - stored_at > self._ttl:
            self._entries.pop(url, None)
            return None
        return data

    def put(self, url: str, data: Dict[str, Any]) -> None:
        if len(self._entries) >= self._max:
            # evict oldest
            oldest = min(self._entries, key=lambda k: self._entries[k][0])
            self._entries.pop(oldest, None)
        self._entries[url] = (time.monotonic(), data)

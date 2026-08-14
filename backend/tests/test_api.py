"""Tests for the SSRF-guarded fetcher and API endpoints."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.fetcher import SsrfBlockedError, validate_url

client = TestClient(app)


class TestSsrFGuard:
    def test_blocks_localhost(self):
        import pytest

        with pytest.raises(SsrfBlockedError):
            validate_url("http://localhost:8000/foo")

    def test_blocks_127_0_0_1(self):
        import pytest

        with pytest.raises(SsrfBlockedError):
            validate_url("http://127.0.0.1/secret")

    def test_blocks_private_range(self):
        import pytest

        for ip in ("10.0.0.5", "192.168.1.1", "172.16.0.1", "169.254.1.1"):
            with pytest.raises(SsrfBlockedError):
                validate_url(f"http://{ip}/")

    def test_blocks_bad_scheme(self):
        import pytest

        with pytest.raises(Exception) as exc_info:
            validate_url("file:///etc/passwd")
        assert exc_info.value.error_type == "bad_scheme"

    def test_blocks_redirect_to_private(self):
        import pytest

        with pytest.raises(SsrfBlockedError):
            validate_url("http://localhost/redirect-to-private")


class TestApi:
    def test_health(self):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_vocab_status(self):
        r = client.get("/api/vocab/status")
        assert r.status_code == 200
        body = r.json()
        assert body["loaded"] is True
        assert body["types"] > 100
        assert body["properties"] > 100

    def test_scan_requires_urls(self):
        r = client.post("/api/scan", json={"urls": []})
        assert r.status_code in (422, 500)

    def test_scan_blocks_ssrf(self):
        r = client.post("/api/scan", json={"urls": ["http://127.0.0.1/"]})
        assert r.status_code == 200
        body = r.json()
        assert body["results"][0]["fetch_error_type"] == "ssrf_blocked"

    def test_validate_html_endpoint(self):
        html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"NewsArticle","headline":"X"}'
            "</script>"
        )
        r = client.post("/api/structured-data/validate-html", json={"html": html})
        assert r.status_code == 200
        body = r.json()
        assert body["structured_data"]["item_count"] == 1
        assert body["structured_data"]["error_count"] == 0

    def test_validate_html_with_error(self):
        html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"NewsArticle","headline":"X","bogus":1}'
            "</script>"
        )
        r = client.post("/api/structured-data/validate-html", json={"html": html})
        assert r.status_code == 200
        body = r.json()
        errors = [f for f in body["structured_data"]["findings"] if f["severity"] == "ERROR"]
        assert len(errors) == 1
        assert errors[0]["property"] == "bogus"
        assert errors[0]["source"]["html_line"] > 0

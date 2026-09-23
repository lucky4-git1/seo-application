"""Step-3 tests: SSRF guard, URL normalization, HTML extraction, robots/sitemap."""
from __future__ import annotations

import socket

import pytest

from app.crawler import discovery
from app.crawler import normalize as N
from app.crawler import parse as P
from app.crawler.safety import UnsafeUrlError, validate_url


@pytest.mark.parametrize("url", [
    "http://localhost/",
    "http://localhost:8000/api",
    "http://foo.localhost/bar",
    "http://127.0.0.1/",
    "http://127.1.2.3:9000/",
    "http://0.0.0.0/",
    "http://10.0.0.5/",
    "http://172.16.4.4/",
    "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "http://[fc00::1]/",
    "ftp://example.com/file",
    "file:///etc/passwd",
    "http://user:pass@example.com/",
    "javascript:alert(1)",
    "",
    "http://",
])
def test_blocked_urls(url):
    with pytest.raises(UnsafeUrlError):
        validate_url(url)


def test_public_host_allowed_with_mock_dns(monkeypatch):
    def fake_getaddrinfo(host, port, **kwargs):
        assert host == "example.com"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert validate_url("https://example.com/some/page") == "https://example.com/some/page"


def test_private_dns_answer_blocked(monkeypatch):
    def fake_getaddrinfo(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.9.9.9", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeUrlError):
        validate_url("http://internal.example/")


def test_normalize_url():
    assert N.normalize_url("https://Example.COM/Path/?utm_source=x&a=1#frag") == \
        "https://example.com/Path/?a=1"
    assert N.normalize_url("http://example.com:80/") == "http://example.com/"
    assert N.same_site("example.com", "www.example.com")
    assert N.same_site("www.example.com", "example.com")
    assert not N.same_site("example.com", "evil.com")
    assert not N.same_site("example.com", "sub.example.com")  # documented: separate site


HTML = b"""<!doctype html><html lang="en"><head>
<title>Test Page Title Here For Sure</title>
<meta name="description" content="A fine description of the test page.">
<meta name="robots" content="index, follow">
<link rel="canonical" href="https://example.com/page">
<meta property="og:title" content="OG Title">
<meta name="twitter:card" content="summary">
<script type="application/ld+json">{"@type":"Article"}</script>
<link rel="alternate" hreflang="en" href="https://example.com/page">
<link rel="alternate" hreflang="xx" href="https://example.com/xx">
</head><body>
<h1>Hello World</h1>
<p>Some body text with enough words to count properly for the parser test.</p>
<img src="/a.png" alt="ok"><img src="/b.png">
<a href="/internal">in</a><a href="https://external.com/x" rel="nofollow">out</a>
<a href="mailto:a@b.c">mail</a>
</body></html>"""


def test_parse_html_extracts_signals():
    sig = P.parse_html("https://example.com/page", HTML)
    assert sig["title"] == "Test Page Title Here For Sure"
    assert sig["title_length"] == len("Test Page Title Here For Sure")
    assert sig["meta_description"] == "A fine description of the test page."
    assert sig["canonical"] == "https://example.com/page"
    assert sig["h1_count"] == 1
    assert sig["h1_text"] == ["Hello World"]
    assert sig["word_count"] > 10
    assert sig["language"] == "en"
    assert sig["images_count"] == 2
    assert sig["images_missing_alt"] == 1
    assert sig["internal_links"] == 1
    assert sig["external_links"] == 1
    assert sig["is_noindex"] is False
    assert sig["schema_presence"] == ["Article"]
    assert sig["open_graph"] == {"title": "OG Title"}
    assert sig["twitter_cards"] == {"card": "summary"}
    assert sig["hreflang"] == {"en": "https://example.com/page", "xx": "https://example.com/xx"}
    assert len(sig["content_hash"]) == 64
    assert len(sig["links"]) == 2
    assert sig["links"][1]["rel"] == "nofollow"


def test_parse_noindex_and_empty():
    sig = P.parse_html("https://example.com/x",
                       b"<html><head><meta name='robots' content='noindex'></head></html>")
    assert sig["is_noindex"] is True
    assert sig["title"] is None
    empty = P.parse_html("https://example.com/x", b"")
    assert empty["word_count"] == 0


def test_parse_robots_and_sitemap():
    robots = discovery.parse_robots(
        "User-agent: *\nDisallow: /admin/\nSitemap: https://example.com/s.xml\n")
    assert robots["disallows"] == ["/admin/"]
    assert robots["sitemaps"] == ["https://example.com/s.xml"]
    assert discovery.is_allowed("/blog", robots["disallows"])
    assert not discovery.is_allowed("/admin/x", robots["disallows"])

    pages, nested = discovery.parse_sitemap(
        b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b'<url><loc>https://example.com/a</loc></url></urlset>')
    assert pages == ["https://example.com/a"]
    assert nested == []
    pages, nested = discovery.parse_sitemap(
        b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b'<sitemap><loc>https://example.com/s1.xml</loc></sitemap></sitemapindex>')
    assert nested == ["https://example.com/s1.xml"]


def test_fetch_redirect_chain_and_errors(monkeypatch):
    import httpx

    from app.crawler import fetch as F

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/old":
            return httpx.Response(301, headers={"location": "/mid"})
        if path == "/mid":
            return httpx.Response(302, headers={"location": "/new"})
        if path == "/new":
            return httpx.Response(200, headers={"content-type": "text/html"},
                                  content=b"<html><head><title>t</title></head></html>")
        if path == "/loop":
            return httpx.Response(301, headers={"location": "/loop"})
        return httpx.Response(404, content=b"nope")

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(F, "_client",
                        lambda: httpx.Client(transport=transport, follow_redirects=False))
    # validate_url still runs — mock DNS for example.com
    import socket as _socket

    def fake_getaddrinfo(host, port, **kwargs):
        return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(_socket, "getaddrinfo", fake_getaddrinfo)

    r = F.fetch_url("https://example.com/old")
    assert r.status_code == 200
    assert r.url == "https://example.com/new"
    assert len(r.redirect_chain) == 2
    assert b"<title>t</title>" in r.body

    loop = F.fetch_url("https://example.com/loop")
    assert loop.error == "too many redirects"

    nf = F.fetch_url("https://example.com/missing")
    assert nf.status_code == 404

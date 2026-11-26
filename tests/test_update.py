"""Backend tests for the in-app update check.

No real network is used: GitHub is always stubbed or replaced by a local
``http.server.ThreadingHTTPServer`` on 127.0.0.1.  Run with the workspace recipe
from ``.lead/CONTRACT.md`` section 7::

    $env:PYTHONPATH = (Resolve-Path .lead)
    $env:TEMP = (Resolve-Path .lead\\run-backend); $env:TMP = $env:TEMP
    python -m pytest tests/test_update.py -q -p no:cacheprovider -p nomode700
"""

from __future__ import annotations

import hashlib
import http.server
import json
import threading
import time
from pathlib import Path

import pytest

import app
from core import config, update

CURRENT = app.APP_VERSION
NEWER = f"{update.version_tuple(CURRENT)[0]}.{update.version_tuple(CURRENT)[1] + 1}.0"
EVEN_NEWER = f"{update.version_tuple(CURRENT)[0]}.{update.version_tuple(CURRENT)[1] + 2}.0"

PAYLOAD_KEYS = {
    "ok", "current", "latest", "update_available", "skipped", "skip_version",
    "auto_check", "release", "source", "checked_at", "stale", "error",
}
DOWNLOAD_KEYS = {
    "state", "version", "asset", "path", "received", "total", "percent",
    "sha256_ok", "error", "started_at", "finished_at",
}

ZIP_NAME = "BabelDOC-Studio-Windows-x64.zip"


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Point settings + cache at a temp dir and reset the download state."""
    app_dir = tmp_path / "app"
    monkeypatch.setattr(config, "APP_DIR", app_dir)
    monkeypatch.setattr(config, "SETTINGS_FILE", app_dir / "settings.json")
    monkeypatch.delenv("READPI_UPDATE_FEED", raising=False)
    monkeypatch.setattr(update, "_download", update._fresh_download_state())
    monkeypatch.setattr(update, "_download_thread", None)
    update._download_cancel.clear()
    yield


@pytest.fixture()
def client(_isolate):
    return app.app.test_client()


def _payload_for(version, body="## 更新\n\n- 修复一些已知问题", assets=None):
    return {
        "tag_name": f"v{version}",
        "name": f"ReadPI {version}",
        "html_url": f"https://github.com/PiDesign-314/ReadPI/releases/tag/v{version}",
        "published_at": "2026-11-01T09:00:00Z",
        "body": body,
        "assets": assets or [],
    }


def _release(version, **kwargs):
    return update.normalize_release(_payload_for(version, **kwargs), "api")


def _stub_fetch(version, calls=None, source="api"):
    release = update.normalize_release(_payload_for(version), source)
    calls = calls if calls is not None else []

    def fake(timeout=update.DEFAULT_TIMEOUT):
        calls.append(version)
        return dict(release)

    return fake


def _forbidden_fetch(*args, **kwargs):
    raise AssertionError("this test must not touch the network")


def _boom(message="GitHub 暂时不可用"):
    def fake(*args, **kwargs):
        raise update.UpdateError(message)

    return fake


def _seed_cache(release=None, checked_at=None, ok=True, error="", source="api"):
    record = {
        "checked_at": update._now() if checked_at is None else checked_at,
        "ok": ok,
        "error": error,
        "source": source,
        "release": release,
    }
    update._write_cache(record)
    return record


def _cached_download_release(base_url, version=NEWER, name=ZIP_NAME, sha=True, size=0):
    """A cache record shaped like a normalised release but with local http URLs."""
    return {
        "tag": f"v{version}",
        "version": version,
        "name": f"ReadPI {version}",
        "url": f"https://github.com/PiDesign-314/ReadPI/releases/tag/v{version}",
        "page_url": update.RELEASES_URL,
        "published_at": "2026-11-01T09:00:00Z",
        "notes": "",
        "notes_excerpt": "",
        "assets": [
            {
                "name": name,
                "size": size,
                "download_url": f"{base_url}/{name}",
                "sha256_url": f"{base_url}/{name}.sha256" if sha else "",
            }
        ],
        "source": "api",
    }


def _wait_for_download(timeout=20.0):
    deadline = time.time() + timeout
    state = update.download_state()
    while state["state"] == "running" and time.time() < deadline:
        time.sleep(0.02)
        state = update.download_state()
    return state


class _FakeResponse:
    def __init__(self, body=b"", url=""):
        self._body = body
        self._url = url

    def read(self, *args):
        return self._body

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _UpdateHandler(http.server.BaseHTTPRequestHandler):
    routes: dict = {}
    requests: list = []

    def do_GET(self):
        _UpdateHandler.requests.append((self.path, dict(self.headers)))
        status, body, content_type = _UpdateHandler.routes.get(
            self.path.split("?", 1)[0], (404, b"not found", "text/plain")
        )
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def local_server():
    _UpdateHandler.routes = {}
    _UpdateHandler.requests = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _UpdateHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base_url, _UpdateHandler.routes
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# --------------------------------------------------------------------------- #
# App wiring
# --------------------------------------------------------------------------- #
def test_app_version_and_feature_flag():
    assert update.version_tuple(app.APP_VERSION) >= (1, 9, 0)
    assert "update-check" in app.API_FEATURES
    assert app.APP_VERSION in update.user_agent()


def test_user_agent_matches_contract():
    assert update.user_agent() == (
        f"ReadPI/{app.APP_VERSION} (+https://github.com/PiDesign-314/ReadPI)"
    )


# --------------------------------------------------------------------------- #
# Version parsing / comparison
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("v1.9.0", (1, 9, 0)),
        ("1.9.0", (1, 9, 0)),
        ("1.9", (1, 9, 0)),
        ("V1.9.0", (1, 9, 0)),
        ("1.9.0-beta.1", (1, 9, 0)),
        ("ReadPI 1.9.0", (1, 9, 0)),
        ("2", (2, 0, 0)),
        ("1.9.0.123", (1, 9, 0)),
        ("build-42", (42, 0, 0)),
        ("", (0, 0, 0)),
        ("garbage", (0, 0, 0)),
        (None, (0, 0, 0)),
    ],
)
def test_version_tuple_table(text, expected):
    assert update.version_tuple(text) == expected


@pytest.mark.parametrize(
    ("latest", "current", "expected"),
    [
        ("2.0.0", "1.9.0", True),
        ("v2.0.0", "ReadPI 1.9.0", True),
        ("1.9.1", "1.9.0", True),
        ("1.10.0", "1.9.9", True),
        ("1.9.0", "1.9.0", False),
        ("1.9", "1.9.0", False),
        ("1.9.0", "2.0.0", False),
        ("garbage", "1.9.0", False),
        ("1.9.0-beta.1", "1.9.0", False),   # pre-release never beats equal stable
        ("1.9.0-rc.1", "1.9", False),
        ("1.9.0", "1.9.0-beta.1", True),    # pre-release local loses to stable
        ("1.9.0-beta.2", "1.9.0-beta.1", False),
        ("2.0.0-beta.1", "1.9.0", True),
        ("v1.9.0", "1.8.1", True),          # prose example from the contract
    ],
)
def test_is_newer_table(latest, current, expected):
    assert update.is_newer(latest, current) is expected


def test_normalize_version():
    assert update.normalize_version("v1.9.0") == "1.9.0"
    assert update.normalize_version("ReadPI 1.9") == "1.9.0"
    assert update.normalize_version("") == ""
    assert update.normalize_version("no digits") == ""


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #
API_FIXTURE = {
    "tag_name": "v2.0.0",
    "name": "ReadPI 2.0.0",
    "html_url": "https://github.com/PiDesign-314/ReadPI/releases/tag/v2.0.0",
    "published_at": "2026-11-01T09:00:00Z",
    "body": "<h2>更新</h2>\n\n- 新增 <b>检查更新</b> 功能\n" + "x" * 25000,
    "assets": [
        {"name": ZIP_NAME, "size": 123456789,
         "browser_download_url": "https://example.com/pkg.zip"},
        {"name": ZIP_NAME + ".sha256", "size": 64,
         "browser_download_url": "https://example.com/pkg.zip.sha256"},
        {"name": "notes.txt", "size": 10,
         "browser_download_url": "http://example.com/notes.txt"},
        {"name": "", "size": 1, "browser_download_url": "https://example.com/blank"},
        "garbage",
    ],
}


def test_normalize_release_from_api_fixture():
    release = update.normalize_release(API_FIXTURE, "api")
    assert release["tag"] == "v2.0.0"
    assert release["version"] == "2.0.0"
    assert release["name"] == "ReadPI 2.0.0"
    assert release["url"] == API_FIXTURE["html_url"]
    assert release["page_url"] == update.RELEASES_URL
    assert release["published_at"] == "2026-11-01T09:00:00Z"
    assert release["source"] == "api"
    assert len(release["notes"]) == update.NOTES_LIMIT
    excerpt = release["notes_excerpt"]
    assert len(excerpt) <= update.EXCERPT_LIMIT
    assert "<" not in excerpt and "\n" not in excerpt
    assert "更新" in excerpt and "检查更新" in excerpt
    names = [asset["name"] for asset in release["assets"]]
    assert names == [ZIP_NAME, ZIP_NAME + ".sha256"]
    assert release["assets"][0]["sha256_url"] == "https://example.com/pkg.zip.sha256"
    assert release["assets"][0]["size"] == 123456789
    assert release["assets"][1]["sha256_url"] == ""


def test_normalize_release_degrades():
    for payload in ({}, None, [], {"tag_name": ""}, {"assets": "nope"}):
        release = update.normalize_release(payload, "api")
        assert release["version"] == ""
        assert release["tag"] == ""
        assert release["url"] == update.RELEASES_URL
        assert release["notes"] == ""
        assert release["notes_excerpt"] == ""
        assert release["assets"] == []


def test_normalize_release_builds_tag_url_without_html_url():
    release = update.normalize_release({"tag_name": "v3.0.1", "name": "ReadPI 3.0.1"})
    assert release["version"] == "3.0.1"
    assert release["url"] == f"{update.RELEASES_URL}/tag/v3.0.1"


# --------------------------------------------------------------------------- #
# Atom / redirect helpers
# --------------------------------------------------------------------------- #
ATOM_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <id>tag:github.com,2008:/PiDesign-314/ReadPI/releases</id>
  <title>Release notes from ReadPI</title>
  <entry>
    <id>tag:github.com,2008:Repository/1/v2.0.0</id>
    <updated>2026-11-01T09:00:00Z</updated>
    <link rel="alternate" type="text/html"
          href="https://github.com/PiDesign-314/ReadPI/releases/tag/v2.0.0"/>
    <title>ReadPI 2.0.0</title>
    <content type="html">&lt;h2&gt;更新&lt;/h2&gt;&lt;p&gt;新增 &lt;b&gt;检查更新&lt;/b&gt;&lt;/p&gt;</content>
  </entry>
  <entry>
    <id>tag:github.com,2008:Repository/1/v1.9.9</id>
    <updated>2026-10-01T09:00:00Z</updated>
    <link rel="alternate" type="text/html"
          href="https://github.com/PiDesign-314/ReadPI/releases/tag/v1.9.9"/>
    <title>ReadPI 1.9.9</title>
    <content type="html">old</content>
  </entry>
</feed>
"""

UNNAMESPACED_ATOM = """<feed>
  <entry>
    <title>notes only</title>
    <link href="https://github.com/PiDesign-314/ReadPI/releases/tag/v3.1.4"/>
    <updated>2026-01-01T00:00:00Z</updated>
    <content>plain text</content>
  </entry>
</feed>"""


def test_parse_atom_fixture():
    release = update.parse_atom(ATOM_FIXTURE)
    assert release["version"] == "2.0.0"
    assert release["tag"] == "v2.0.0"
    assert release["source"] == "atom"
    assert release["published_at"] == "2026-11-01T09:00:00Z"
    assert release["url"].endswith("/tag/v2.0.0")
    assert "更新" in release["notes"] and "检查更新" in release["notes"]
    assert "<" not in release["notes"]
    assert release["assets"] == []


def test_parse_atom_without_namespace_uses_link_tag():
    release = update.parse_atom(UNNAMESPACED_ATOM)
    assert release["version"] == "3.1.4"
    assert release["tag"] == "v3.1.4"
    assert release["notes"] == "plain text"


def test_parse_atom_rejects_garbage():
    with pytest.raises(update.UpdateError):
        update.parse_atom("<not-xml")
    with pytest.raises(update.UpdateError):
        update.parse_atom("<feed></feed>")


def test_tag_from_url():
    assert update.tag_from_url(
        "https://github.com/PiDesign-314/ReadPI/releases/tag/v1.9.0"
    ) == "v1.9.0"
    assert update.tag_from_url(
        "https://github.com/PiDesign-314/ReadPI/releases/tag/v1.9.0?foo=1"
    ) == "v1.9.0"
    assert update.tag_from_url(
        "https://github.com/PiDesign-314/ReadPI/releases/tag/ReadPI%201.9.0"
    ) == "ReadPI 1.9.0"
    assert update.tag_from_url("https://github.com/PiDesign-314/ReadPI/releases") == ""
    assert update.tag_from_url("") == ""


def test_probe_redirect_parses_final_url(monkeypatch):
    final_url = f"https://github.com/PiDesign-314/ReadPI/releases/tag/v{NEWER}"

    def fake_open(url, timeout=update.DEFAULT_TIMEOUT, headers=None):
        return _FakeResponse(url=final_url)

    monkeypatch.setattr(update, "_open", fake_open)
    release = update.probe_redirect()
    assert release["version"] == NEWER
    assert release["source"] == "redirect"
    assert release["url"] == final_url
    assert release["notes"] == ""


def test_probe_redirect_without_tag_raises(monkeypatch):
    monkeypatch.setattr(
        update,
        "_open",
        lambda *_args, **_kwargs: _FakeResponse(
            url="https://github.com/PiDesign-314/ReadPI/releases"
        ),
    )
    with pytest.raises(update.UpdateError):
        update.probe_redirect()


def test_fetch_via_api_sends_contract_headers(monkeypatch):
    captured = {}

    def fake_open(url, timeout=update.DEFAULT_TIMEOUT, headers=None):
        captured["url"] = url
        captured["headers"] = dict(headers or {})
        return _FakeResponse(body=json.dumps(_payload_for(NEWER)).encode("utf-8"))

    monkeypatch.setattr(update, "_open", fake_open)
    release = update._fetch_via_api(2.0)
    assert captured["url"] == update.API_URL
    # ``_open`` merges the contract User-Agent into every request; the stub above
    # replaces it, so only the per-call headers are visible here.
    assert captured["headers"]["Accept"] == "application/vnd.github+json"
    assert release["source"] == "api"
    assert release["version"] == NEWER


def test_open_merges_user_agent_into_request(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["user_agent"] = request.get_header("User-agent")
        captured["accept"] = request.get_header("Accept")
        return _FakeResponse(body=b"{}")

    monkeypatch.setattr(update.urllib.request, "urlopen", fake_urlopen)
    update._open(update.API_URL, 2.0, {"Accept": "application/vnd.github+json"})
    assert captured["url"] == update.API_URL
    assert captured["user_agent"] == update.user_agent()
    assert captured["accept"] == "application/vnd.github+json"


# --------------------------------------------------------------------------- #
# Source order
# --------------------------------------------------------------------------- #
def test_feed_file_override(tmp_path, monkeypatch):
    feed = tmp_path / "feed.json"
    feed.write_text(json.dumps(_payload_for(NEWER)), encoding="utf-8")
    monkeypatch.setenv("READPI_UPDATE_FEED", str(feed))
    monkeypatch.setattr(update, "_fetch_via_api", _forbidden_fetch)
    monkeypatch.setattr(update, "_fetch_via_atom", _forbidden_fetch)
    monkeypatch.setattr(update, "probe_redirect", _forbidden_fetch)

    release = update.fetch_release()
    assert release["source"] == "feed"
    assert release["version"] == NEWER


def test_feed_http_override(local_server, monkeypatch):
    base_url, routes = local_server
    routes["/feed.json"] = (
        200, json.dumps(_payload_for(NEWER)).encode("utf-8"), "application/json"
    )
    monkeypatch.setenv("READPI_UPDATE_FEED", base_url + "/feed.json")
    monkeypatch.setattr(update, "_fetch_via_api", _forbidden_fetch)
    monkeypatch.setattr(update, "_fetch_via_atom", _forbidden_fetch)
    monkeypatch.setattr(update, "probe_redirect", _forbidden_fetch)

    release = update.fetch_release()
    assert release["source"] == "feed"
    assert release["version"] == NEWER
    assert _UpdateHandler.requests
    _, headers = _UpdateHandler.requests[0]
    assert headers["User-Agent"] == update.user_agent()


def test_feed_failure_falls_back_to_api(tmp_path, monkeypatch):
    monkeypatch.setenv("READPI_UPDATE_FEED", str(tmp_path / "missing.json"))
    api_release = _release(NEWER)
    monkeypatch.setattr(update, "_fetch_via_api", lambda timeout=8: dict(api_release))
    monkeypatch.setattr(update, "_fetch_via_atom", _forbidden_fetch)
    monkeypatch.setattr(update, "probe_redirect", _forbidden_fetch)
    assert update.fetch_release()["source"] == "api"


def test_fetch_release_falls_back_to_atom(monkeypatch):
    atom_release = update.normalize_release(_payload_for(NEWER), "atom")
    monkeypatch.setattr(update, "_fetch_via_api", _boom())
    monkeypatch.setattr(update, "_fetch_via_atom", lambda timeout=8: dict(atom_release))
    monkeypatch.setattr(update, "probe_redirect", _forbidden_fetch)
    release = update.fetch_release()
    assert release["source"] == "atom"
    assert release["version"] == NEWER


def test_fetch_release_total_failure(monkeypatch):
    monkeypatch.setattr(update, "_fetch_via_api", _boom())
    monkeypatch.setattr(update, "_fetch_via_atom", _boom())
    monkeypatch.setattr(update, "probe_redirect", _boom())
    with pytest.raises(update.UpdateError) as caught:
        update.fetch_release(timeout=0.2)
    assert "无法检查更新" in str(caught.value)


# --------------------------------------------------------------------------- #
# check() / cache
# --------------------------------------------------------------------------- #
def test_cache_roundtrip_and_ttl(monkeypatch):
    calls = []
    monkeypatch.setattr(update, "fetch_release", _stub_fetch(NEWER, calls))

    first = update.check()
    assert first["ok"] is True
    assert first["update_available"] is True
    assert first["latest"] == NEWER
    assert first["current"] == app.APP_VERSION
    assert first["source"] == "api"
    assert first["stale"] is False
    assert first["error"] == ""
    assert first["checked_at"] > 0
    assert calls == [NEWER]

    cache = update.cached()
    assert isinstance(cache, dict)
    assert set(cache) >= {"checked_at", "ok", "error", "source", "release"}
    assert cache["release"]["version"] == NEWER

    again = update.check()
    assert again["latest"] == NEWER
    assert calls == [NEWER]  # fresh cache, no second fetch

    checked = float(first["checked_at"])
    monkeypatch.setattr(update, "_now", lambda: checked + update.CACHE_TTL + 1.0)
    refreshed = update.check()
    assert refreshed["latest"] == NEWER
    assert calls == [NEWER, NEWER]  # TTL expired -> refetch


def test_check_force_refetches(monkeypatch):
    calls = []
    monkeypatch.setattr(update, "fetch_release", _stub_fetch(NEWER, calls))
    update.check()
    update.check(force=True)
    assert calls == [NEWER, NEWER]


def test_cache_only_never_fetches(monkeypatch):
    monkeypatch.setattr(update, "fetch_release", _forbidden_fetch)

    empty = update.check(cache_only=True)
    assert empty["ok"] is False
    assert empty["release"] is None
    assert empty["checked_at"] == 0.0
    assert empty["source"] == "none"
    assert empty["error"] == ""

    release = _release(NEWER)
    monkeypatch.setattr(update, "_now", lambda: 1000.0)
    _seed_cache(release, checked_at=1000.0)
    fresh = update.check(cache_only=True)
    assert fresh["ok"] is True
    assert fresh["latest"] == NEWER
    assert fresh["source"] == "cache"
    assert fresh["stale"] is False

    monkeypatch.setattr(update, "_now", lambda: 1000.0 + update.CACHE_TTL + 5)
    stale = update.check(cache_only=True)
    assert stale["ok"] is True
    assert stale["stale"] is True


def test_cache_only_reports_failed_cache(monkeypatch):
    monkeypatch.setattr(update, "fetch_release", _forbidden_fetch)
    monkeypatch.setattr(update, "_now", lambda: 2000.0)
    _seed_cache(release=None, checked_at=2000.0, ok=False, error="网络不可用")
    payload = update.check(cache_only=True)
    assert payload["ok"] is False
    assert payload["release"] is None
    assert payload["error"] == "网络不可用"
    assert payload["source"] == "cache"


def test_failure_cache_keeps_stale_release_and_retries(monkeypatch):
    base = 1_800_000_000.0
    monkeypatch.setattr(update, "_now", lambda: base)
    release = _release(NEWER)
    _seed_cache(release, checked_at=base - update.CACHE_TTL - 10)

    calls = []

    def failing(timeout=update.DEFAULT_TIMEOUT):
        calls.append(1)
        raise update.UpdateError("网络不可用")

    monkeypatch.setattr(update, "fetch_release", failing)

    first = update.check()
    assert first["ok"] is True
    assert first["stale"] is True
    assert first["release"]["version"] == NEWER
    assert first["error"]  # soft Chinese message
    assert first["source"] == "cache"
    assert calls == [1]

    second = update.check()  # failure cache younger than FAIL_TTL -> no retry
    assert second["ok"] is True and second["stale"] is True
    assert calls == [1]

    monkeypatch.setattr(update, "_now", lambda: base + update.FAIL_TTL + 5)
    third = update.check()  # retried, fails again
    assert third["ok"] is True and third["stale"] is True
    assert calls == [1, 1]

    cache = update.cached()
    assert cache["ok"] is False
    assert cache["release"]["version"] == NEWER


def test_failure_without_previous_release(monkeypatch):
    monkeypatch.setattr(update, "_now", lambda: 5000.0)
    monkeypatch.setattr(update, "fetch_release", _boom("GitHub 暂时不可用"))

    payload = update.check()
    assert payload["ok"] is False
    assert payload["release"] is None
    assert payload["latest"] == ""
    assert payload["update_available"] is False
    assert payload["error"] == "GitHub 暂时不可用"

    cache = update.cached()
    assert cache["ok"] is False
    assert cache["release"] is None

    monkeypatch.setattr(update, "fetch_release", _forbidden_fetch)
    again = update.check()  # recent failure is served from cache, no retry
    assert again["ok"] is False
    assert again["error"] == "GitHub 暂时不可用"


def test_check_payload_shape(monkeypatch):
    monkeypatch.setattr(update, "fetch_release", _stub_fetch(NEWER))
    payload = update.check(force=True)
    assert set(payload) == PAYLOAD_KEYS
    assert payload["current"] == app.APP_VERSION
    assert payload["latest"] == NEWER
    assert payload["update_available"] is True
    assert isinstance(payload["checked_at"], float)
    assert isinstance(payload["release"], dict)
    assert payload["release"]["version"] == NEWER


def test_same_version_is_not_an_update(monkeypatch):
    monkeypatch.setattr(update, "fetch_release", _stub_fetch(CURRENT))
    payload = update.check(force=True)
    assert payload["latest"] == update.normalize_version(CURRENT)
    assert payload["update_available"] is False
    assert payload["skipped"] is False


def test_feed_with_current_version_is_not_an_update(tmp_path, monkeypatch):
    feed = tmp_path / "feed.json"
    feed.write_text(json.dumps(_payload_for(CURRENT)), encoding="utf-8")
    monkeypatch.setenv("READPI_UPDATE_FEED", str(feed))
    monkeypatch.setattr(update, "_fetch_via_api", _forbidden_fetch)
    monkeypatch.setattr(update, "_fetch_via_atom", _forbidden_fetch)
    monkeypatch.setattr(update, "probe_redirect", _forbidden_fetch)

    payload = update.check(force=True)
    assert payload["latest"] == update.normalize_version(CURRENT)
    assert payload["update_available"] is False


def test_skip_and_prefs_roundtrip(monkeypatch):
    monkeypatch.setattr(update, "fetch_release", _stub_fetch(NEWER))

    payload = update.check(force=True)
    assert payload["update_available"] is True
    assert payload["skipped"] is False

    assert update.set_skip_version(payload["latest"]) == payload["latest"]
    assert update.skip_version() == payload["latest"]

    monkeypatch.setattr(update, "fetch_release", _forbidden_fetch)
    skipped = update.check(cache_only=True)
    assert skipped["skipped"] is True
    assert skipped["skip_version"] == payload["latest"]

    assert update.set_skip_version("") == ""
    assert update.skip_version() == ""
    assert update.check(cache_only=True)["skipped"] is False

    # A non-version string clears the skip instead of storing garbage.
    assert update.set_skip_version("not a version") == ""
    assert update.skip_version() == ""

    assert update.prefs() == {"auto_check": True}
    assert update.save_prefs({"auto_check": False}) == {"auto_check": False}
    assert update.prefs()["auto_check"] is False
    assert update.check(cache_only=True)["auto_check"] is False
    assert update.save_prefs({}) == {"auto_check": False}  # missing key keeps value
    assert update.save_prefs({"auto_check": True}) == {"auto_check": True}


# --------------------------------------------------------------------------- #
# HTTP routes
# --------------------------------------------------------------------------- #
def test_route_check(client, monkeypatch):
    monkeypatch.setattr(update, "fetch_release", _stub_fetch(NEWER))

    response = client.get("/api/update/check?force=1")
    assert response.status_code == 200
    assert response.is_json
    payload = response.get_json()
    assert set(payload) == PAYLOAD_KEYS
    assert payload["current"] == app.APP_VERSION
    assert payload["latest"] == NEWER
    assert payload["update_available"] is True

    cached_payload = client.get("/api/update/check?cache_only=1").get_json()
    assert cached_payload["ok"] is True
    assert cached_payload["latest"] == NEWER
    assert cached_payload["source"] == "cache"


UPDATE_ROUTES = [
    ("get", "/api/update/check"),
    ("get", "/api/update/download/status"),
    ("post", "/api/update/download"),
    ("post", "/api/update/download/cancel"),
    ("post", "/api/update/skip"),
    ("post", "/api/update/prefs"),
]


@pytest.mark.parametrize(("method", "path"), UPDATE_ROUTES)
def test_update_routes_are_loopback_only(client, method, path):
    kwargs = {"environ_overrides": {"REMOTE_ADDR": "203.0.113.7"}}
    if method == "post":
        kwargs["json"] = {}
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 403
    assert response.is_json
    assert response.get_json()["error"] == "仅本机可用"


def test_route_download_status(client):
    response = client.get("/api/update/download/status")
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert set(body["download"]) == DOWNLOAD_KEYS
    assert body["download"]["state"] == "idle"


def test_routes_skip_and_prefs(client):
    skip = client.post("/api/update/skip", json={"version": "v2.0.0"})
    assert skip.status_code == 200
    assert skip.get_json() == {"ok": True, "skip_version": "2.0.0"}
    assert update.skip_version() == "2.0.0"

    cleared = client.post("/api/update/skip", json={"version": ""})
    assert cleared.get_json()["skip_version"] == ""
    assert update.skip_version() == ""

    off = client.post("/api/update/prefs", json={"auto_check": False})
    assert off.status_code == 200
    assert off.get_json() == {"ok": True, "auto_check": False}
    assert update.prefs()["auto_check"] is False

    on = client.post("/api/update/prefs", json={"auto_check": True})
    assert on.get_json() == {"ok": True, "auto_check": True}


def test_route_download_cancel_when_idle(client):
    response = client.post("/api/update/download/cancel")
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["download"]["state"] == "idle"


def test_route_download_without_asset(client):
    response = client.post("/api/update/download", json={})
    assert response.status_code == 400
    assert response.is_json
    assert response.get_json()["error"] == "没有可下载的安装包"


def test_routes_tolerate_bad_json(client):
    for method, path in (
        ("post", "/api/update/prefs"),
        ("post", "/api/update/skip"),
        ("post", "/api/update/download/cancel"),
    ):
        response = getattr(client, method)(
            path, data="{not json", content_type="application/json"
        )
        assert response.status_code == 200, path
        assert response.is_json
    response = client.post(
        "/api/update/download", data="{not json", content_type="application/json"
    )
    assert response.status_code == 400
    assert response.is_json


# --------------------------------------------------------------------------- #
# Downloads (real transfer against a local threaded HTTP server)
# --------------------------------------------------------------------------- #
def test_download_success_and_sha256(monkeypatch, tmp_path, local_server):
    base_url, routes = local_server
    payload = b"PK\x03\x04" + bytes(value % 256 for value in range(20000))
    checksum = hashlib.sha256(payload).hexdigest()
    routes[f"/{ZIP_NAME}"] = (200, payload, "application/zip")
    routes[f"/{ZIP_NAME}.sha256"] = (
        200, f"{checksum}  {ZIP_NAME}\n".encode("utf-8"), "text/plain"
    )
    _seed_cache(_cached_download_release(base_url, size=len(payload)))
    target_dir = tmp_path / "downloads"
    monkeypatch.setattr(update, "download_dir", lambda: target_dir)

    started = update.start_download()
    assert started["state"] in {"running", "done"}
    state = _wait_for_download()
    assert state["state"] == "done", state
    assert state["sha256_ok"] is True
    assert state["percent"] == 100
    assert state["received"] == len(payload)
    assert state["total"] == len(payload)
    assert state["error"] == ""
    downloaded = Path(state["path"])
    assert downloaded.parent == target_dir
    assert downloaded.name == ZIP_NAME
    assert downloaded.read_bytes() == payload
    assert not downloaded.with_name(downloaded.name + ".part").exists()


def test_download_sha256_mismatch_deletes_file(monkeypatch, tmp_path, local_server):
    base_url, routes = local_server
    name = "ReadPI-Windows-x64.zip"
    payload = b"PK\x03\x04" + b"tampered" * 500
    routes[f"/{name}"] = (200, payload, "application/zip")
    routes[f"/{name}.sha256"] = (200, ("0" * 64 + f"  {name}\n").encode(), "text/plain")
    _seed_cache(_cached_download_release(base_url, name=name, size=len(payload)))
    target_dir = tmp_path / "downloads"
    monkeypatch.setattr(update, "download_dir", lambda: target_dir)

    update.start_download()
    state = _wait_for_download()
    assert state["state"] == "error", state
    assert state["sha256_ok"] is False
    assert "校验" in state["error"]
    assert not Path(state["path"]).exists()
    assert list(target_dir.glob("*.part")) == []


def test_download_without_checksum_completes(monkeypatch, tmp_path, local_server):
    base_url, routes = local_server
    name = "ReadPI-NoSum.zip"
    payload = b"PK\x03\x04" + b"x" * 4096
    routes[f"/{name}"] = (200, payload, "application/zip")
    _seed_cache(_cached_download_release(base_url, name=name, sha=False, size=len(payload)))
    target_dir = tmp_path / "downloads"
    monkeypatch.setattr(update, "download_dir", lambda: target_dir)

    update.start_download()
    state = _wait_for_download()
    assert state["state"] == "done", state
    assert state["sha256_ok"] is False
    assert Path(state["path"]).read_bytes() == payload


def test_download_requires_cached_asset():
    state = update.start_download()
    assert state["state"] == "error"
    assert state["error"] == "没有可下载的安装包"
    assert state["asset"] == ""


def test_start_download_joins_running_transfer(monkeypatch, tmp_path, local_server):
    base_url, routes = local_server
    name = "ReadPI-Slow.zip"
    payload = b"PK\x03\x04" + b"y" * 4096
    routes[f"/{name}"] = (200, payload, "application/zip")
    _seed_cache(_cached_download_release(base_url, name=name, sha=False))
    monkeypatch.setattr(update, "download_dir", lambda: tmp_path / "downloads")

    first = update.start_download()
    second = update.start_download()  # a running transfer is joined, not duplicated
    assert second["state"] in {"running", "done"}
    assert second["version"] == first["version"]
    state = _wait_for_download()
    assert state["state"] == "done", state


def test_cancel_when_idle_keeps_idle_state():
    assert update.download_state()["state"] == "idle"
    assert update.cancel_download()["state"] == "idle"


def test_download_state_returns_a_copy():
    snapshot = update.download_state()
    snapshot["state"] = "hacked"
    assert update.download_state()["state"] == "idle"


def test_pick_asset_prefers_zip():
    release = {
        "assets": [
            {"name": "notes.txt", "download_url": "https://example.com/notes.txt"},
            {"name": ZIP_NAME, "download_url": "https://example.com/pkg.zip"},
        ]
    }
    assert update._pick_asset(release)["name"] == ZIP_NAME
    assert update._pick_asset(release, "notes.txt")["name"] == "notes.txt"
    assert update._pick_asset(release, "missing.zip")["name"] == ZIP_NAME
    assert update._pick_asset(None) is None
    assert update._pick_asset({"assets": []}) is None

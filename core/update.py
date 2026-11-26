"""In-app update checks for ReadPI (GitHub Releases).

The portable Windows build cannot replace itself while it is running (the
interpreter locks its own files), so the app only *reports* new releases and can
download the release ZIP for the user.  Everything here is best-effort: a
missing network, a rate-limited GitHub API or a read-only profile must degrade
to a cached answer or a soft Chinese message and must never break the app.

Only the Python standard library is used.  Every outbound request carries the
``ReadPI/<version>`` user agent so GitHub traffic is attributable.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from . import config

# --------------------------------------------------------------------------- #
# Repository / network constants
# --------------------------------------------------------------------------- #
REPO = "PiDesign-314/ReadPI"
RELEASES_URL = "https://github.com/PiDesign-314/ReadPI/releases"
LATEST_PAGE = "https://github.com/PiDesign-314/ReadPI/releases/latest"
API_URL = "https://api.github.com/repos/PiDesign-314/ReadPI/releases/latest"
ATOM_URL = "https://github.com/PiDesign-314/ReadPI/releases.atom"

CACHE_TTL = 6 * 3600        # successful check
FAIL_TTL = 10 * 60          # failed check

DEFAULT_TIMEOUT = 8.0
DOWNLOAD_TIMEOUT = 20.0
DOWNLOAD_CHUNK = 256 * 1024

NOTES_LIMIT = 20000
EXCERPT_LIMIT = 600

SOFT_ERROR = "无法检查更新，请稍后重试"
NO_ASSET_ERROR = "没有可下载的安装包"
SHA_MISMATCH_ERROR = "SHA-256 校验失败，下载的文件可能不完整，请重试"

# ``core`` must not import ``app`` at module level (app imports this module);
# the version is resolved lazily so tests and the app always agree.
FALLBACK_VERSION = "1.9.1"
_UA_SUFFIX = "(+https://github.com/PiDesign-314/ReadPI)"

_VERSION_RE = re.compile(r"(\d+(?:\.\d+)*)")
_TAG_RE = re.compile(r"/releases/tag/([^/?#\s]+)")
_SHA_RE = re.compile(r"[0-9a-fA-F]{64}")
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


class UpdateError(Exception):
    """No source produced a usable release (message is user-facing Chinese)."""

    def __init__(self, message: str = SOFT_ERROR, failures: list | None = None):
        super().__init__(message)
        self.failures = list(failures or [])


def current_version() -> str:
    """Local app version; read from ``app`` lazily to avoid an import cycle."""
    try:
        from app import APP_VERSION  # noqa: PLC0415 - intentional lazy import
        return str(APP_VERSION or FALLBACK_VERSION)
    except Exception:
        return FALLBACK_VERSION


def user_agent() -> str:
    return f"ReadPI/{current_version()} {_UA_SUFFIX}"


def _now() -> float:
    return time.time()


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# Version handling
# --------------------------------------------------------------------------- #
def _version_parts(text) -> tuple[tuple[int, int, int], bool]:
    """Numeric core padded to three ints plus a "this is a pre-release" flag."""
    raw = str(text or "")
    match = _VERSION_RE.search(raw)
    if not match:
        return (0, 0, 0), False
    parts = [int(part) for part in match.group(1).split(".")][:3]
    while len(parts) < 3:
        parts.append(0)
    rest = raw[match.end():].strip()
    prerelease = bool(rest) and (rest[0] in "-_ " or rest[0].isalpha())
    return (parts[0], parts[1], parts[2]), prerelease


def version_tuple(text: str) -> tuple[int, int, int]:
    """First ``\\d+(\\.\\d+)*`` in *text*, padded/truncated to three ints."""
    return _version_parts(text)[0]


def is_newer(latest: str, current: str) -> bool:
    """Strict ``>`` on the numeric core, with the pre-release rule applied."""
    newer, newer_pre = _version_parts(latest)
    older, older_pre = _version_parts(current)
    if newer != older:
        return newer > older
    # Same numeric core: a pre-release loses to the stable release, so a
    # pre-release never announces itself over an equal stable local version.
    if newer_pre and not older_pre:
        return False
    if older_pre and not newer_pre:
        return True
    return False


def normalize_version(text: str) -> str:
    """``"v1.9.0-beta"`` -> ``"1.9.0"``; ``""`` when there is no numeric core."""
    parts = version_tuple(text)
    if parts == (0, 0, 0):
        return ""
    return ".".join(str(part) for part in parts)


# --------------------------------------------------------------------------- #
# Release normalisation
# --------------------------------------------------------------------------- #
def _text(value) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def strip_html(text: str) -> str:
    """Crude tag stripping for the excerpt (never used to render markup)."""
    value = str(text or "")
    value = re.sub(r"<(script|style)\b.*?</\1>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html_lib.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _html_to_text(value: str) -> str:
    """Turn an Atom HTML body into readable plain text (fallback source)."""
    text = str(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(?:p|div|li|h[1-6]|tr|pre|blockquote)>", "\n", text, flags=re.I)
    text = re.sub(r"<li\b[^>]*>", "- ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_lib.unescape(text)
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _normalize_assets(raw_assets) -> list:
    assets = []
    if not isinstance(raw_assets, list):
        return assets
    for item in raw_assets:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name")).strip()
        url = _text(
            item.get("browser_download_url") or item.get("download_url") or item.get("url")
        ).strip()
        if not name or not url.startswith("https://"):
            continue
        try:
            size = int(item.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        assets.append(
            {"name": name, "size": size, "download_url": url, "sha256_url": ""}
        )
    by_name = {asset["name"]: asset for asset in assets}
    for asset in assets:
        checksum = by_name.get(asset["name"] + ".sha256")
        if checksum is not None:
            asset["sha256_url"] = checksum["download_url"]
    return assets


def normalize_release(payload: dict, source: str = "api") -> dict:
    """Normalise a GitHub-API-shaped payload; odd/missing fields degrade to ``""``."""
    data = payload if isinstance(payload, dict) else {}
    tag = _text(data.get("tag_name") or data.get("tag") or data.get("title")).strip()
    name = _text(data.get("name") or data.get("title") or tag).strip()
    version = (
        normalize_version(tag)
        or normalize_version(name)
        or normalize_version(_text(data.get("version")))
    )
    url = _text(data.get("html_url")).strip()
    if not url.startswith("https://"):
        url = f"{RELEASES_URL}/tag/v{version}" if version else RELEASES_URL
    published_at = _text(
        data.get("published_at") or data.get("created_at") or data.get("updated")
    ).strip()
    notes = _text(data.get("body") or data.get("content") or "")[:NOTES_LIMIT]
    return {
        "tag": tag,
        "version": version,
        "name": name or tag,
        "url": url,
        "page_url": RELEASES_URL,
        "published_at": published_at,
        "notes": notes,
        "notes_excerpt": strip_html(notes)[:EXCERPT_LIMIT],
        "assets": _normalize_assets(data.get("assets")),
        # Kept so ``check()`` can label the payload; harmless extra key for the UI.
        "source": source,
    }


# --------------------------------------------------------------------------- #
# Atom feed (no API rate limit)
# --------------------------------------------------------------------------- #
def tag_from_url(url: str) -> str:
    """``.../releases/tag/v1.9.0`` -> ``v1.9.0`` (URL-decoded, ``""`` if none)."""
    match = _TAG_RE.search(str(url or ""))
    if not match:
        return ""
    return urllib.parse.unquote(match.group(1)).strip()


def _entry_text(entry, name: str) -> str:
    for tag in (f"atom:{name}", name):
        try:
            value = entry.findtext(tag, default="", namespaces=_ATOM_NS)
        except Exception:
            value = ""
        if value and value.strip():
            return value.strip()
    return ""


def _entry_link(entry) -> str:
    fallback = ""
    for tag in ("atom:link", "link"):
        try:
            nodes = entry.findall(tag, _ATOM_NS)
        except Exception:
            nodes = []
        for node in nodes:
            href = _text(node.get("href")).strip()
            if not href:
                continue
            if "/releases/tag/" in href:
                return href
            fallback = fallback or href
    return fallback


def parse_atom(text: str, source: str = "atom") -> dict:
    """Parse a GitHub ``releases.atom`` feed into the normalised release dict."""
    try:
        root = ET.fromstring(str(text or ""))
    except ET.ParseError as exc:
        raise UpdateError("更新源返回的数据格式不正确", [str(exc)]) from exc
    entries = root.findall("atom:entry", _ATOM_NS) or root.findall("entry")
    if not entries:
        raise UpdateError("更新源没有可用的发布记录")
    for entry in entries:
        title = _entry_text(entry, "title")
        link = _entry_link(entry)
        updated = _entry_text(entry, "updated") or _entry_text(entry, "published")
        content = _entry_text(entry, "content") or _entry_text(entry, "summary")
        tag = tag_from_url(link)
        if not normalize_version(tag or title):
            continue
        payload = {
            "tag_name": tag or title,
            "name": title,
            "html_url": link,
            "published_at": updated,
            "body": _html_to_text(content),
            "assets": [],
        }
        return normalize_release(payload, source)
    raise UpdateError("更新源没有可用的版本号")


# --------------------------------------------------------------------------- #
# Network fetchers
# --------------------------------------------------------------------------- #
def _open(url: str, timeout: float = DEFAULT_TIMEOUT, headers: dict | None = None):
    request_headers = {"User-Agent": user_agent()}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    try:
        seconds = float(timeout)
    except (TypeError, ValueError):
        seconds = DEFAULT_TIMEOUT
    return urllib.request.urlopen(request, timeout=max(0.5, seconds))


def _read_url(url: str, timeout: float = DEFAULT_TIMEOUT, headers: dict | None = None) -> bytes:
    with _open(url, timeout, headers) as response:
        return response.read()


def _decode_json(raw: bytes) -> dict:
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    data = json.loads(text.lstrip("\ufeff"))
    if not isinstance(data, dict):
        raise UpdateError("更新源返回的数据格式不正确")
    return data


def _fetch_from_feed(feed: str, timeout: float) -> dict:
    """``READPI_UPDATE_FEED``: http(s) JSON URL or a local GitHub-API-shaped file."""
    value = str(feed or "").strip()
    if value.startswith(("http://", "https://")):
        raw = _read_url(value, timeout)
    else:
        raw = Path(value).expanduser().read_text(encoding="utf-8", errors="replace")
    release = normalize_release(_decode_json(raw), "feed")
    if not release["version"]:
        raise UpdateError("更新源没有可用的版本号")
    return release


def _fetch_via_api(timeout: float = DEFAULT_TIMEOUT) -> dict:
    raw = _read_url(API_URL, timeout, {"Accept": "application/vnd.github+json"})
    release = normalize_release(_decode_json(raw), "api")
    if not release["version"]:
        raise UpdateError("GitHub API 返回的版本号无法识别")
    return release


def _fetch_via_atom(timeout: float = DEFAULT_TIMEOUT) -> dict:
    raw = _read_url(ATOM_URL, timeout, {"Accept": "application/atom+xml"})
    return parse_atom(raw.decode("utf-8", "replace"), "atom")


def probe_redirect(timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Follow ``/releases/latest`` and read the version out of the final URL."""
    with _open(LATEST_PAGE, timeout) as response:
        final_url = response.geturl()
    tag = tag_from_url(final_url)
    if not normalize_version(tag):
        raise UpdateError("GitHub Releases 页面没有指向具体版本")
    payload = {
        "tag_name": tag,
        "name": tag,
        "html_url": final_url if str(final_url).startswith("https://") else "",
        "published_at": "",
        "body": "",
        "assets": [],
    }
    return normalize_release(payload, "redirect")


def fetch_release(timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Newest release from the first usable source.

    Order: ``READPI_UPDATE_FEED`` override -> GitHub API -> atom feed ->
    ``/releases/latest`` redirect probe.  Raises :class:`UpdateError` when no
    source yields a version.  The overall time budget is *timeout* seconds.
    """
    try:
        seconds = float(timeout)
    except (TypeError, ValueError):
        seconds = DEFAULT_TIMEOUT
    deadline = time.monotonic() + max(0.5, seconds)

    def remaining() -> float:
        return max(0.5, deadline - time.monotonic())

    failures: list[str] = []
    feed = (os.environ.get("READPI_UPDATE_FEED") or "").strip()
    if feed:
        try:
            release = _fetch_from_feed(feed, remaining())
            if release.get("version"):
                return release
            failures.append("feed: no version")
        except Exception as exc:  # fall through to GitHub proper
            failures.append(f"feed: {exc}")
    for name, fetcher in (
        ("api", _fetch_via_api),
        ("atom", _fetch_via_atom),
        ("redirect", probe_redirect),
    ):
        try:
            release = fetcher(remaining())
            if release and release.get("version"):
                return release
            failures.append(f"{name}: no version")
        except Exception as exc:
            failures.append(f"{name}: {exc}")
    raise UpdateError(SOFT_ERROR, failures)


# --------------------------------------------------------------------------- #
# Cache (config.APP_DIR/update-cache.json)
# --------------------------------------------------------------------------- #
def cache_path() -> Path:
    return Path(config.APP_DIR) / "update-cache.json"


def cached() -> dict | None:
    """Raw cache record, or ``None`` when absent/unreadable."""
    try:
        data = json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_cache(record: dict) -> None:
    """Atomic write; a read-only profile only loses the cache, never the feature."""
    path = cache_path()
    tmp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        try:
            if tmp is not None and tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _previous_good(record: dict | None) -> tuple[dict | None, float]:
    """Last known good release and when it was fetched (0.0 when none)."""
    if not isinstance(record, dict):
        return None, 0.0
    release = record.get("release")
    if not isinstance(release, dict) or not release.get("version"):
        return None, 0.0
    checked = _as_float(
        record.get("release_checked_at") or record.get("checked_at") or 0.0
    )
    return release, checked


def _record_failure(now: float, message: str, previous: tuple[dict | None, float]) -> None:
    release, checked = previous
    _write_cache(
        {
            "checked_at": now,
            "ok": False,
            "error": message,
            "source": "none",
            "release": release,
            "release_checked_at": checked,
        }
    )


# --------------------------------------------------------------------------- #
# Preferences / skipped version
# --------------------------------------------------------------------------- #
_prefs_lock = threading.Lock()


def prefs() -> dict:
    try:
        return {"auto_check": bool(config.load_raw().get("update_auto_check", True))}
    except Exception:
        return {"auto_check": True}


def save_prefs(payload: dict) -> dict:
    desired = None
    if isinstance(payload, dict) and "auto_check" in payload:
        desired = bool(payload.get("auto_check"))
    with _prefs_lock:
        if desired is None:
            return {"auto_check": prefs()["auto_check"]}
        try:
            settings = config.load_raw()
            settings["update_auto_check"] = desired
            config.save_raw(settings)
        except Exception:
            pass
    return {"auto_check": desired}


def skip_version() -> str:
    try:
        value = config.load_raw().get("update_skip_version") or ""
    except Exception:
        return ""
    return normalize_version(str(value))


def set_skip_version(version: str) -> str:
    normalized = normalize_version(str(version or ""))
    with _prefs_lock:
        try:
            settings = config.load_raw()
            settings["update_skip_version"] = normalized
            config.save_raw(settings)
        except Exception:
            pass
    return normalized


# --------------------------------------------------------------------------- #
# check() — the payload behind GET /api/update/check
# --------------------------------------------------------------------------- #
def _payload(
    release: dict | None,
    source: str,
    checked_at: float,
    stale: bool,
    error: str,
) -> dict:
    latest = str(release.get("version") or "") if isinstance(release, dict) else ""
    current = current_version()
    update_available = bool(latest) and is_newer(latest, current)
    skipped_version = skip_version()
    skipped = bool(
        update_available
        and skipped_version
        and version_tuple(skipped_version) == version_tuple(latest)
    )
    return {
        "ok": bool(latest),
        "current": current,
        "latest": latest,
        "update_available": update_available,
        "skipped": skipped,
        "skip_version": skipped_version,
        "auto_check": prefs()["auto_check"],
        "release": release if isinstance(release, dict) else None,
        "source": source,
        "checked_at": float(checked_at or 0.0),
        "stale": bool(stale),
        "error": error or "",
    }


def _offline_payload(message: str = SOFT_ERROR) -> dict:
    return {
        "ok": False,
        "current": FALLBACK_VERSION,
        "latest": "",
        "update_available": False,
        "skipped": False,
        "skip_version": "",
        "auto_check": True,
        "release": None,
        "source": "none",
        "checked_at": 0.0,
        "stale": False,
        "error": message,
    }


def check(force: bool = False, cache_only: bool = False) -> dict:
    """Return the update payload; never raises and never blocks past the timeout."""
    try:
        now = _now()
        record = cached()

        if cache_only:
            if not isinstance(record, dict):
                return _payload(None, "none", 0.0, False, "")
            release, release_checked = _previous_good(record)
            checked = _as_float(record.get("checked_at"))
            if release:
                stale = (now - release_checked) > CACHE_TTL
                error = "" if record.get("ok") else str(record.get("error") or "")
                return _payload(release, "cache", release_checked, stale, error or "")
            stale = (now - checked) > CACHE_TTL
            return _payload(
                None, "cache", checked, stale, str(record.get("error") or "") or SOFT_ERROR
            )

        if not force and isinstance(record, dict):
            checked = _as_float(record.get("checked_at"))
            age = now - checked
            release, release_checked = _previous_good(record)
            if record.get("ok"):
                if release and age < CACHE_TTL:
                    return _payload(release, "cache", release_checked or checked, False, "")
            elif age < FAIL_TTL:
                # A recent failure is not retried; still surface cached data.
                error = str(record.get("error") or "") or SOFT_ERROR
                if release:
                    return _payload(release, "cache", release_checked, True, error)
                return _payload(None, "cache", checked, False, error)

        previous = _previous_good(record)
        try:
            fetched = fetch_release()
        except Exception as exc:
            message = str(exc).strip() or SOFT_ERROR
            _record_failure(now, message, previous)
            if previous[0] is not None:
                return _payload(previous[0], "cache", previous[1], True, message)
            return _payload(None, "none", now, False, message)

        release = dict(fetched) if isinstance(fetched, dict) else None
        if not release or not release.get("version"):
            _record_failure(now, SOFT_ERROR, previous)
            if previous[0] is not None:
                return _payload(previous[0], "cache", previous[1], True, SOFT_ERROR)
            return _payload(None, "none", now, False, SOFT_ERROR)
        source = str(release.get("source") or "") or "api"
        _write_cache(
            {"checked_at": now, "ok": True, "error": "", "source": source, "release": release}
        )
        return _payload(release, source, now, False, "")
    except Exception:
        return _offline_payload()


# --------------------------------------------------------------------------- #
# Download state machine (explicit user trigger only)
# --------------------------------------------------------------------------- #
class _DownloadCancelled(Exception):
    """Internal control-flow marker for a user-cancelled transfer."""


_download_lock = threading.Lock()
_download_cancel = threading.Event()
_download_thread: threading.Thread | None = None


def _fresh_download_state() -> dict:
    return {
        "state": "idle",
        "version": "",
        "asset": "",
        "path": "",
        "received": 0,
        "total": 0,
        "percent": 0,
        "sha256_ok": False,
        "error": "",
        "started_at": 0.0,
        "finished_at": 0.0,
    }


_download: dict = _fresh_download_state()


def download_state() -> dict:
    with _download_lock:
        return dict(_download)


def _update_download(**fields) -> None:
    with _download_lock:
        _download.update(fields)


def download_dir() -> Path:
    """``~/Downloads`` when it exists, else ``config.APP_DIR/updates``."""
    try:
        downloads = Path.home() / "Downloads"
        if downloads.is_dir():
            return downloads
    except Exception:
        pass
    return Path(config.APP_DIR) / "updates"


def _cached_release() -> dict | None:
    release, _ = _previous_good(cached())
    return release


def _pick_asset(release: dict | None, asset_name: str = "") -> dict | None:
    if not isinstance(release, dict):
        return None
    assets = release.get("assets")
    if not isinstance(assets, list):
        return None
    usable = [
        asset
        for asset in assets
        if isinstance(asset, dict)
        and str(asset.get("name") or "").strip()
        and str(asset.get("download_url") or "").startswith(("http://", "https://"))
    ]
    wanted = str(asset_name or "").strip()
    if wanted:
        for asset in usable:
            if str(asset.get("name")) == wanted:
                return asset
    for asset in usable:
        if str(asset.get("name")).lower().endswith(".zip"):
            return asset
    return usable[0] if usable else None


def start_download(asset_name: str = "") -> dict:
    """Start (or join) the single background download; returns the current state."""
    global _download, _download_thread
    with _download_lock:
        if _download.get("state") == "running":
            return dict(_download)
        release = _cached_release()
        version = str((release or {}).get("version") or "")
        asset = _pick_asset(release, asset_name)
        if asset is None:
            _download = _fresh_download_state()
            _download.update(
                {
                    "state": "error",
                    "version": version,
                    "error": NO_ASSET_ERROR,
                    "started_at": _now(),
                    "finished_at": _now(),
                }
            )
            return dict(_download)
        safe_name = Path(str(asset.get("name"))).name
        if not safe_name or safe_name in {".", ".."}:
            _download = _fresh_download_state()
            _download.update(
                {
                    "state": "error",
                    "version": version,
                    "error": NO_ASSET_ERROR,
                    "started_at": _now(),
                    "finished_at": _now(),
                }
            )
            return dict(_download)
        try:
            target = download_dir() / safe_name
        except Exception:
            _download = _fresh_download_state()
            _download.update(
                {
                    "state": "error",
                    "version": version,
                    "asset": safe_name,
                    "error": "无法确定下载位置",
                    "started_at": _now(),
                    "finished_at": _now(),
                }
            )
            return dict(_download)
        total = 0
        try:
            total = int(asset.get("size") or 0)
        except (TypeError, ValueError):
            total = 0
        _download = _fresh_download_state()
        _download.update(
            {
                "state": "running",
                "version": version,
                "asset": safe_name,
                "path": str(target),
                "received": 0,
                "total": total,
                "percent": 0,
                "started_at": _now(),
            }
        )
        _download_cancel.clear()
        thread = threading.Thread(
            target=_run_download,
            args=(dict(asset), target, version),
            daemon=True,
            name="readpi-update-download",
        )
        _download_thread = thread
        thread.start()
        return dict(_download)


def cancel_download() -> dict:
    """Ask the running transfer to stop; the worker owns the final state."""
    with _download_lock:
        if _download.get("state") == "running":
            _download_cancel.set()
        return dict(_download)


def _remove_file(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _verify_sha256(path: Path, sha_url: str) -> bool | None:
    """``True`` match, ``False`` mismatch, ``None`` when it could not be checked."""
    try:
        raw = _read_url(sha_url, DOWNLOAD_TIMEOUT)
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        match = _SHA_RE.search(text)
        if not match:
            return None
        expected = match.group(0).lower()
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(DOWNLOAD_CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest() == expected
    except Exception:
        return None


def _run_download(asset: dict, target: Path, version: str) -> None:
    part = target.with_name(target.name + ".part")
    received = 0
    try:
        total = int(asset.get("size") or 0)
    except (TypeError, ValueError):
        total = 0
    sha_url = str(asset.get("sha256_url") or "")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(
            str(asset.get("download_url")), headers={"User-Agent": user_agent()}
        )
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
            header_length = _text(response.headers.get("Content-Length")).strip()
            if header_length.isdigit() and int(header_length) > 0:
                if total <= 0:
                    total = int(header_length)
                    _update_download(total=total, percent=0)
            with open(part, "wb") as handle:
                while True:
                    if _download_cancel.is_set():
                        raise _DownloadCancelled()
                    chunk = response.read(DOWNLOAD_CHUNK)
                    if not chunk:
                        break
                    handle.write(chunk)
                    received += len(chunk)
                    percent = int(received * 100 / total) if total > 0 else 0
                    _update_download(
                        received=received, total=total, percent=min(percent, 100)
                    )
        if _download_cancel.is_set():
            raise _DownloadCancelled()
        os.replace(part, target)
        if sha_url:
            verified = _verify_sha256(target, sha_url)
            if verified is False:
                _remove_file(target)
                _update_download(
                    state="error",
                    version=version,
                    path=str(target),
                    received=received,
                    total=total,
                    percent=0,
                    sha256_ok=False,
                    error=SHA_MISMATCH_ERROR,
                    finished_at=_now(),
                )
                return
            sha_ok = bool(verified)
        else:
            sha_ok = False
        _update_download(
            state="done",
            version=version,
            path=str(target),
            received=received,
            total=total,
            percent=100,
            sha256_ok=sha_ok,
            error="",
            finished_at=_now(),
        )
    except _DownloadCancelled:
        _remove_file(part)
        _update_download(
            state="cancelled",
            version=version,
            path=str(target),
            received=received,
            total=total,
            sha256_ok=False,
            error="",
            finished_at=_now(),
        )
    except Exception as exc:
        _remove_file(part)
        _update_download(
            state="error",
            version=version,
            path=str(target),
            received=received,
            total=total,
            sha256_ok=False,
            error=f"下载失败：{exc}",
            finished_at=_now(),
        )

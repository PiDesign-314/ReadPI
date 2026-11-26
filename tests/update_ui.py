"""Manual Playwright check for the in-app update UI (not collected by pytest).

Run:  python tests/update_ui.py

The script builds a GitHub-API-shaped fixture announcing a version strictly newer
than ``app.APP_VERSION`` and points ``READPI_UPDATE_FEED`` at it, then drives the
real pages (``/`` and ``/library``).

When ``app.py`` has no ``/api/update/*`` routes yet (backend workstream still in
flight) the script installs tiny stub routes **in this process only** so the
frontend can be exercised; nothing is written into ``web/update.js``. Once the
real routes exist the script uses them and the stub is skipped.
"""

import json
import os
import re
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flask import jsonify, request
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

import app

from core import config

TMP = ROOT / ".tmp" / ("update-ui-" + uuid.uuid4().hex[:6])
TMP.mkdir(parents=True, exist_ok=True)
LEAD = ROOT / ".lead"
LEAD.mkdir(exist_ok=True)

CURRENT = str(getattr(app, "APP_VERSION", "") or "1.8.1").strip()


def bump_major(version):
    numbers = [int(part) for part in re.findall(r"\d+", version)[:3]]
    while len(numbers) < 3:
        numbers.append(0)
    return f"{numbers[0] + 1}.0.0"


NEWER = bump_major(CURRENT)

ALERT_AND_MARKUP = """
# ReadPI 1.9 更新说明

## 新增
- 支持在应用内检查更新，不必再手动逛 GitHub
- 下载完成后自动定位到安装包所在文件夹
  - 子项：保留设置与批注
1. 打开应用
2. 查看顶部提示

> [!IMPORTANT]
> **Windows 11「智能应用控制」用户请先读这里。**
>
> - 解压前：右键 ZIP → 属性 → 勾选「解除锁定」
> - 已经解压的：在解压目录打开 PowerShell，执行
>   `Get-ChildItem -Recurse -File | Unblock-File`；
> - 详见 [更新说明](https://example.com/notes) 与 <https://example.com/help>。

### 修复
- 修复了 `update_skip_version` 的边界问题

```powershell
Get-ChildItem -Recurse -File | Unblock-File
```

普通段落里包含 <b>raw html</b> 与 <img src=x onerror=alert(1)>，应当按纯文本显示。
"""

LONG_TAIL = "这是一段很长的补充说明，用来触发 3000 字折叠。" * 120
NEWER_NOTES = ALERT_AND_MARKUP + "\n\n" + LONG_TAIL + "\n\n折叠后的结尾标记-ZZZ\n"
CURRENT_NOTES = "## 已是最新\n- 当前版本就是最新版本\n"


def write_feed(name, version, notes):
    target = TMP / name
    target.write_text(
        json.dumps(
            {
                "tag_name": f"v{version}",
                "name": f"ReadPI {version}",
                "html_url": f"https://github.com/PiDesign-314/ReadPI/releases/tag/v{version}",
                "published_at": "2026-11-01T09:00:00Z",
                "body": notes,
                "assets": [
                    {
                        "name": "BabelDOC-Studio-Windows-x64.zip",
                        "size": 123456789,
                        "browser_download_url": "https://127.0.0.1:9/BabelDOC-Studio-Windows-x64.zip",
                    },
                    {
                        "name": "BabelDOC-Studio-Windows-x64.zip.sha256",
                        "size": 64,
                        "browser_download_url": "https://127.0.0.1:9/BabelDOC-Studio-Windows-x64.zip.sha256",
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return target


NEWER_FEED = write_feed("newer.json", NEWER, NEWER_NOTES)
CURRENT_FEED = write_feed("current.json", CURRENT, CURRENT_NOTES)

os.environ["READPI_UPDATE_FEED"] = str(NEWER_FEED)


def set_feed(path):
    os.environ["READPI_UPDATE_FEED"] = str(path)


# --------------------------------------------------------------------------- #
# Backend: real routes when present, otherwise a temporary in-process stub.
# --------------------------------------------------------------------------- #
REAL_BACKEND = any(str(rule) == "/api/update/check" for rule in app.app.url_map.iter_rules())
DOWNLOAD_STUB = {
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


def version_tuple(text):
    numbers = [int(part) for part in re.findall(r"\d+", str(text or ""))[:3]]
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers[:3])


def load_feed():
    raw = Path(os.environ["READPI_UPDATE_FEED"]).read_text(encoding="utf-8")
    data = json.loads(raw)
    tag = str(data.get("tag_name") or "").strip()
    version = ".".join(str(part) for part in version_tuple(tag))
    assets = []
    for asset in data.get("assets") or []:
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        assets.append({"name": name, "size": asset.get("size") or 0, "download_url": url})
    for asset in assets:
        if asset["name"].lower().endswith(".zip"):
            sha_name = asset["name"] + ".sha256"
            for other in assets:
                if other["name"] == sha_name:
                    asset["sha256_url"] = other["download_url"]
                    break
            else:
                asset["sha256_url"] = ""
    release = {
        "tag": tag,
        "version": version,
        "name": str(data.get("name") or tag),
        "url": str(data.get("html_url") or ""),
        "page_url": "https://github.com/PiDesign-314/ReadPI/releases",
        "published_at": str(data.get("published_at") or ""),
        "notes": str(data.get("body") or ""),
        "notes_excerpt": str(data.get("body") or "")[:600],
        "assets": assets,
    }
    return release


STUB = {"release": None, "checked_at": 0.0, "skip_version": "", "auto_check": True}


def stub_payload(release, checked_at, stale=False, error=""):
    latest = release["version"] if release else ""
    update_available = bool(latest) and version_tuple(latest) > version_tuple(CURRENT)
    skipped = bool(update_available and STUB["skip_version"] == latest)
    return {
        "ok": release is not None,
        "current": CURRENT,
        "latest": latest,
        "update_available": update_available,
        "skipped": skipped,
        "skip_version": STUB["skip_version"],
        "auto_check": STUB["auto_check"],
        "release": release,
        "source": "feed" if release else "none",
        "checked_at": checked_at,
        "stale": stale,
        "error": error,
    }


def install_stub_backend():
    @app.app.get("/api/update/check")
    def stub_update_check():
        if request.args.get("cache_only") in ("1", "true"):
            return jsonify(stub_payload(STUB["release"], STUB["checked_at"]))
        release = load_feed()
        STUB["release"] = release
        STUB["checked_at"] = time.time()
        return jsonify(stub_payload(release, STUB["checked_at"]))

    @app.app.get("/api/update/download/status")
    def stub_update_download_status():
        state = DOWNLOAD_STUB
        if state["state"] == "running":
            state["received"] = min(state["total"], state["received"] + 250)
            state["percent"] = int(round(state["received"] * 100 / state["total"]))
            if state["received"] >= state["total"]:
                state.update(
                    state="done",
                    sha256_ok=True,
                    path=str(Path.home() / "Downloads" / "BabelDOC-Studio-Windows-x64.zip"),
                    finished_at=time.time(),
                )
        return jsonify({"ok": True, "download": dict(DOWNLOAD_STUB)})

    @app.app.post("/api/update/download")
    def stub_update_download():
        body = request.get_json(silent=True) or {}
        asset = body.get("asset") or "BabelDOC-Studio-Windows-x64.zip"
        DOWNLOAD_STUB.update(
            state="running",
            version=NEWER,
            asset=asset,
            path="",
            received=250,
            total=1000,
            percent=25,
            sha256_ok=False,
            error="",
            started_at=time.time(),
            finished_at=0.0,
        )
        return jsonify({"ok": True, "download": dict(DOWNLOAD_STUB)})

    @app.app.post("/api/update/download/cancel")
    def stub_update_download_cancel():
        DOWNLOAD_STUB.update(state="cancelled")
        return jsonify({"ok": True, "download": dict(DOWNLOAD_STUB)})

    @app.app.post("/api/update/skip")
    def stub_update_skip():
        body = request.get_json(silent=True) or {}
        STUB["skip_version"] = str(body.get("version") or "").strip()
        return jsonify({"ok": True, "skip_version": STUB["skip_version"]})

    @app.app.post("/api/update/prefs")
    def stub_update_prefs():
        body = request.get_json(silent=True) or {}
        if "auto_check" in body:
            STUB["auto_check"] = bool(body["auto_check"])
        return jsonify({"ok": True, "auto_check": STUB["auto_check"]})


if not REAL_BACKEND:
    install_stub_backend()

server = make_server("127.0.0.1", 0, app.app, threaded=True)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_port}"


def api(path, method="GET", body=None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def reset_skip():
    try:
        api("/api/update/skip", "POST", {"version": ""})
    except Exception:
        pass


def force_refresh():
    try:
        return api("/api/update/check?force=1")
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Cache / preference preservation (real backend writes to the user's profile).
# --------------------------------------------------------------------------- #
CACHE_FILE = Path(config.APP_DIR) / "update-cache.json"
saved_cache = CACHE_FILE.read_bytes() if CACHE_FILE.exists() else None
saved_skip = ""
saved_auto = True
if REAL_BACKEND:
    try:
        cached = api("/api/update/check?cache_only=1")
        saved_skip = str(cached.get("skip_version") or "")
        saved_auto = bool(cached.get("auto_check", True))
    except Exception:
        pass

downloaded_stub = False

try:
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge", headless=True, args=["--no-proxy-server"])
        except Exception:
            browser = p.chromium.launch(headless=True, args=["--no-proxy-server"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        # Fresh cache for the newer feed so the first paint shows the badge.
        set_feed(NEWER_FEED)
        reset_skip()
        force_refresh()

        # ------------------------------------------------------------------ /
        page.goto(BASE + "/")
        page.wait_for_selector("#btn-update", state="visible", timeout=20000)
        assert page.evaluate(
            "() => document.querySelector('.topbar-right').firstElementChild.id"
        ) == "btn-update", "update entry is not the first child of .topbar-right"
        label = page.inner_text("#update-entry-label")
        assert "有新版本" in label and f"v{NEWER}" in label, f"badge label: {label!r}"
        assert page.get_attribute("#btn-update", "aria-expanded") == "false"

        page.click("#btn-update")
        page.wait_for_selector("#update-modal", state="visible", timeout=5000)
        page.wait_for_selector("#update-notes .update-callout", state="visible", timeout=5000)
        assert page.get_attribute("#btn-update", "aria-expanded") == "true"

        current_pill = page.inner_text("#update-current")
        latest_pill = page.inner_text("#update-latest")
        assert f"v{CURRENT}" in current_pill, current_pill
        assert f"v{NEWER}" in latest_pill, latest_pill

        notes = page.locator("#update-notes")
        notes_text = notes.inner_text()
        for expected in (
            "支持在应用内检查更新",
            "新增",
            "修复",
            "Windows 11",
            "重要",
            "raw html",
            "在 GitHub 上查看完整说明",
        ):
            assert expected in notes_text, f"missing in release notes: {expected!r}"
        assert "[!IMPORTANT]" not in notes_text, "GitHub alert marker leaked as text"
        assert notes.locator(".update-callout[data-alert='important']").count() == 1
        assert "重要" in notes.locator(".update-callout-label").first.inner_text()
        assert notes.locator("h3, h4, h5").count() >= 2, "headings were not rendered"
        assert notes.locator("ul li").count() >= 3, "bullets were not rendered"
        assert notes.locator("ol li").count() >= 2, "ordered list was not rendered"
        assert notes.locator("pre code").count() >= 1, "fenced code block was not rendered"
        assert notes.locator("strong").count() >= 1, "bold was not rendered"
        assert notes.locator("code").count() >= 2, "inline code was not rendered"
        assert notes.locator("a[href='https://example.com/notes']").count() == 1
        assert notes.locator("a[href='https://example.com/help']").count() == 1
        assert notes.locator("script").count() == 0, "raw <script> was injected as markup"
        assert notes.locator("b").count() == 0, "raw <b> was injected as markup"
        assert notes.locator("img").count() == 0, "raw <img> was injected as markup"
        assert "&lt;b&gt;raw html&lt;/b&gt;" in notes.inner_html(), "HTML text was not escaped"
        collapse = notes.locator(".update-more a")
        assert collapse.count() == 1, "3000-char collapse link missing"
        assert f"/releases/tag/v{NEWER}" in collapse.get_attribute("href")
        assert "折叠后的结尾标记-ZZZ" not in notes_text, "collapsed tail leaked into the dialog"
        assert page.is_visible("#update-download"), "下载更新 should be visible when a .zip asset exists"
        assert page.is_visible("#update-page"), "打开下载页 must always be available"

        page.screenshot(path=str(LEAD / "update-ui-dialog.png"))

        # Download flow: POST + 700 ms polling + progress / hint.
        page.click("#update-download")
        page.wait_for_selector("#update-progress", state="visible", timeout=10000)
        if REAL_BACKEND:
            # The fixture asset URL is intentionally unreachable: expect a soft,
            # Chinese error instead of a hard failure.
            page.wait_for_function(
                """() => {
                  const hint = document.querySelector('#update-hint');
                  return hint && hint.textContent.trim().length > 0;
                }""",
                timeout=40000,
            )
            hint = page.inner_text("#update-hint")
            assert re.search(r"[\u4e00-\u9fff]", hint), f"download error is not Chinese: {hint!r}"
        else:
            downloaded_stub = True
            page.wait_for_function(
                """() => {
                  const hint = document.querySelector('#update-hint');
                  return hint && hint.textContent.includes('已下载到');
                }""",
                timeout=20000,
            )
            hint = page.inner_text("#update-hint")
            assert "已下载到" in hint, hint
            assert "解压后覆盖原程序目录即可完成更新" in hint, hint
            assert page.is_visible("#update-open-folder"), "打开文件夹 button missing after download"
            assert page.eval_on_selector(
                "[role='progressbar']", "el => el.getAttribute('aria-valuenow')"
            ) == "100"

        # Escape closes and restores focus to the entry button.
        page.keyboard.press("Escape")
        page.wait_for_selector("#update-modal", state="hidden", timeout=5000)
        assert page.get_attribute("#btn-update", "aria-expanded") == "false"
        page.wait_for_timeout(150)
        assert page.evaluate("document.activeElement && document.activeElement.id") == "btn-update"

        # 跳过此版本 persists and hides the badge.
        page.click("#btn-update")
        page.wait_for_selector("#update-modal", state="visible", timeout=5000)
        page.click("#update-skip")
        page.wait_for_selector("#btn-update", state="hidden", timeout=10000)
        page.wait_for_timeout(300)
        assert page.locator("#btn-update").is_hidden()

        # ------------------------------------------- settings: 检查更新 row
        set_feed(CURRENT_FEED)
        reset_skip()
        force_refresh()
        page.click("#btn-settings-entry")
        page.wait_for_selector("#update-settings-section", state="visible", timeout=5000)
        current_version = page.inner_text("#update-current-version")
        assert f"v{CURRENT}" in current_version, current_version
        page.click("#update-check-now")
        page.wait_for_function(
            """() => {
              const el = document.querySelector('#update-check-result');
              return el && el.textContent.includes('已是最新版本');
            }""",
            timeout=30000,
        )
        page.screenshot(path=str(LEAD / "update-ui-settings.png"))
        page.locator("#settings-modal .settings-panel").screenshot(
            path=str(LEAD / "update-ui-settings-panel.png")
        )
        page.click("#settings-close")
        page.wait_for_selector("#settings-modal", state="hidden", timeout=5000)

        # No update available → dialog shows 已是最新版本 and only close/page.
        page.evaluate("window.ReadPIUpdate.open()")
        page.wait_for_selector("#update-modal", state="visible", timeout=5000)
        no_update = page.inner_text("#update-notes")
        assert f"已是最新版本 v{CURRENT}" in no_update, no_update
        assert page.locator("#update-skip").is_hidden()
        assert page.locator("#update-download").is_hidden()
        assert page.is_visible("#update-page")
        page.keyboard.press("Escape")
        page.wait_for_selector("#update-modal", state="hidden", timeout=5000)

        # ---------------------------------------------------------- /library
        set_feed(NEWER_FEED)
        reset_skip()
        force_refresh()
        page.goto(BASE + "/library")
        page.wait_for_selector("#btn-update", state="visible", timeout=20000)
        label = page.inner_text("#update-entry-label")
        assert "有新版本" in label and f"v{NEWER}" in label, f"library badge: {label!r}"
        assert page.locator("#update-settings-section").count() == 0, (
            "library.html has no settings sheet; the update section must not be injected"
        )
        page.click("#btn-update")
        page.wait_for_selector("#update-modal", state="visible", timeout=5000)
        page.wait_for_selector("#update-notes .update-callout", state="visible", timeout=5000)
        assert f"v{CURRENT}" in page.inner_text("#update-current")
        assert f"v{NEWER}" in page.inner_text("#update-latest")
        assert "支持在应用内检查更新" in page.inner_text("#update-notes")
        page.screenshot(path=str(LEAD / "update-ui-library.png"))
        page.keyboard.press("Escape")
        page.wait_for_selector("#update-modal", state="hidden", timeout=5000)
        assert page.get_attribute("#btn-update", "aria-expanded") == "false"

        update_errors = [error for error in errors if "update" in error.lower()]
        assert not update_errors, update_errors

        browser.close()

    mode = "REAL backend" if REAL_BACKEND else "in-process stub backend"
    print(
        f"UPDATE UI PASS ({mode}): badge v{NEWER}, dialog v{CURRENT} → v{NEWER}, "
        "safe notes (callout/bold/code/link, no HTML injection, 3000-char collapse), "
        "download progress/hint, skip hides badge, Escape closes + restores focus, "
        "settings 检查更新 → 已是最新版本, /library parity; screenshots in .lead/"
    )
finally:
    server.shutdown()
    if REAL_BACKEND:
        try:
            api("/api/update/skip", "POST", {"version": saved_skip})
            api("/api/update/prefs", "POST", {"auto_check": saved_auto})
        except Exception:
            pass
        try:
            if saved_cache is None:
                CACHE_FILE.unlink(missing_ok=True)
            else:
                CACHE_FILE.write_bytes(saved_cache)
        except Exception:
            pass
    os.environ.pop("READPI_UPDATE_FEED", None)

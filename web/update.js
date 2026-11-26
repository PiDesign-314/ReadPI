/* ReadPI in-app update UI — self-contained.
 *
 * Loaded by index.html and library.html.  Talks to the /api/update/* routes and
 * renders GitHub release notes as DOM nodes; remote markup never reaches
 * innerHTML (only textContent), so a hostile release body cannot inject HTML.
 *
 * Contract: .lead/UPDATE-CONTRACT.md section 3.
 */
(function () {
  "use strict";

  if (window.ReadPIUpdate) return;

  var RELEASES_PAGE = "https://github.com/PiDesign-314/ReadPI/releases";
  var SEEN_KEY = "readpi-update-seen";
  var POLL_MS = 700;
  var NOTES_LIMIT = 3000;
  var AUTO_CHECK_DELAY = 1500;
  var CACHE_TTL = 6 * 3600;
  var ALERT_LABELS = {
    IMPORTANT: "重要",
    NOTE: "注意",
    WARNING: "提醒",
    TIP: "提示",
    CAUTION: "小心",
  };
  var FOCUSABLE =
    'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]),' +
    ' textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

  var state = {
    started: false,
    payload: null,
    release: null,
    current: "",
    latest: "",
    assetName: "",
    downloadPath: "",
    downloading: false,
    skipping: false,
    pollTimer: 0,
    pollMisses: 0,
    resumePending: false,
    opener: null,
  };

  /* Referenced DOM nodes, filled by ensure*(). */
  var ui = {
    entry: null,
    label: null,
    modal: null,
    panel: null,
    title: null,
    current: null,
    latest: null,
    versions: null,
    meta: null,
    notes: null,
    progress: null,
    progressTrack: null,
    progressText: null,
    bar: null,
    hint: null,
    openFolder: null,
    close: null,
    skip: null,
    later: null,
    page: null,
    download: null,
    settingsSection: null,
    currentVersion: null,
    checkNow: null,
    checkResult: null,
    autoCheck: null,
  };

  /* ------------------------------------------------------------- helpers -- */

  function $(selector, root) {
    return (root || document).querySelector(selector);
  }

  function node(tag, attrs, children) {
    var el = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        var value = attrs[key];
        if (value === null || value === undefined) return;
        if (key === "class") el.className = value;
        else if (key === "text") el.textContent = value;
        else if (key === "hidden") el.hidden = !!value;
        else el.setAttribute(key, value);
      });
    }
    (children || []).forEach(function (child) {
      if (child === null || child === undefined) return;
      el.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return el;
  }

  function textOf(value) {
    return value === null || value === undefined ? "" : String(value);
  }

  function softError(err, fallback) {
    var message = err && err.message ? String(err.message) : "";
    return /[\u4e00-\u9fff]/.test(message) ? message : fallback;
  }

  async function api(path, options) {
    var opts = Object.assign({ cache: "no-store" }, options || {});
    if (opts.body !== undefined) {
      opts.headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
      opts.body = JSON.stringify(opts.body);
    }
    var response = await fetch(path, opts);
    var data = null;
    try {
      data = await response.json();
    } catch (err) {
      data = null;
    }
    if (!response.ok) {
      throw new Error((data && data.error) || "请求失败（" + response.status + "）");
    }
    return data;
  }

  function toast(message, kind) {
    var host = $("#toasts") || $(".toasts");
    if (!host) {
      host = node("div", { class: "toasts", id: "readpi-update-toasts" });
      document.body.appendChild(host);
    }
    var el = node("div", { class: "toast" + (kind ? " " + kind : ""), text: message });
    host.appendChild(el);
    setTimeout(function () {
      el.remove();
    }, 4200);
  }

  /* --------------------------------------------------------- topbar entry -- */

  function ensureEntry() {
    var existing = $("#btn-update");
    if (existing) {
      ui.entry = existing;
      ui.label = $("#update-entry-label", existing);
      return;
    }
    var right = $(".topbar-right");
    if (!right) return;
    var btn = node(
      "button",
      {
        class: "pill-btn update-entry",
        id: "btn-update",
        type: "button",
        title: "发现新版本，点击查看",
        "aria-haspopup": "dialog",
        "aria-expanded": "false",
        "aria-controls": "update-modal",
        hidden: true,
      },
      [
        node("span", { class: "update-entry-label", id: "update-entry-label", text: "有新版本" }),
        node("span", { class: "update-dot", "aria-hidden": "true" }),
      ]
    );
    right.insertBefore(btn, right.firstChild);
    btn.addEventListener("click", function () {
      openDialog(btn);
    });
    ui.entry = btn;
    ui.label = $("#update-entry-label", btn);
  }

  /* -------------------------------------------------------------- dialog -- */

  function ensureDialog() {
    if (ui.modal) return;
    ui.panel = node("div", {
      class: "update-panel",
      role: "dialog",
      "aria-modal": "true",
      "aria-labelledby": "update-title",
    });

    ui.title = node("h2", { id: "update-title", text: "发现新版本" });
    ui.close = node("button", {
      class: "update-x",
      id: "update-close",
      type: "button",
      "aria-label": "关闭",
      text: "✕",
    });
    var head = node("header", { class: "update-head" }, [ui.title, ui.close]);

    ui.current = node("span", {
      class: "update-pill update-pill-current",
      id: "update-current",
      text: "当前版本",
    });
    ui.latest = node("span", {
      class: "update-pill update-pill-latest",
      id: "update-latest",
      text: "最新版本",
    });
    ui.versions = node("p", { class: "update-versions" }, [
      ui.current,
      node("span", { class: "update-arrow", "aria-hidden": "true", text: "→" }),
      ui.latest,
    ]);

    ui.meta = node("p", { class: "update-meta", id: "update-meta" });
    ui.notes = node("div", { class: "update-notes", id: "update-notes" });

    ui.bar = node("span", { id: "update-progress-bar" });
    ui.progressTrack = node(
      "div",
      {
        class: "update-progress-track",
        role: "progressbar",
        "aria-valuemin": "0",
        "aria-valuemax": "100",
        "aria-valuenow": "0",
        "aria-label": "下载进度",
      },
      [ui.bar]
    );
    ui.progressText = node("p", { class: "update-progress-text", id: "update-progress-text" });
    ui.progress = node("div", { class: "update-progress", id: "update-progress", hidden: true }, [
      ui.progressTrack,
      ui.progressText,
    ]);

    ui.hint = node("p", { class: "update-hint", id: "update-hint" });
    ui.openFolder = node("button", {
      class: "btn btn-secondary small update-open-folder",
      id: "update-open-folder",
      type: "button",
      hidden: true,
      text: "打开文件夹",
    });

    var body = node("div", { class: "update-body" }, [
      ui.versions,
      ui.meta,
      ui.notes,
      ui.progress,
      ui.hint,
      ui.openFolder,
    ]);

    ui.skip = node("button", { class: "btn btn-ghost", id: "update-skip", type: "button", text: "跳过此版本" });
    ui.later = node("button", { class: "btn btn-ghost", id: "update-later", type: "button", text: "稍后提醒" });
    ui.page = node("a", {
      class: "btn btn-secondary",
      id: "update-page",
      target: "_blank",
      rel: "noopener noreferrer",
      href: RELEASES_PAGE,
      text: "打开下载页",
    });
    ui.download = node("button", {
      class: "btn btn-primary",
      id: "update-download",
      type: "button",
      text: "下载更新",
    });
    var foot = node("footer", { class: "update-foot" }, [ui.skip, ui.later, ui.page, ui.download]);

    ui.panel.appendChild(head);
    ui.panel.appendChild(body);
    ui.panel.appendChild(foot);

    ui.modal = node("div", { class: "update-backdrop", id: "update-modal", hidden: true }, [ui.panel]);
    document.body.appendChild(ui.modal);

    ui.close.addEventListener("click", function () {
      closeDialog();
    });
    ui.skip.addEventListener("click", function () {
      skipVersion();
    });
    ui.later.addEventListener("click", function () {
      closeDialog();
    });
    ui.download.addEventListener("click", function () {
      startDownload();
    });
    ui.openFolder.addEventListener("click", function () {
      openFolder();
    });
    ui.modal.addEventListener("click", function (event) {
      if (event.target === ui.modal) closeDialog();
    });
    document.addEventListener("keydown", onDocumentKeydown);
  }

  function onDocumentKeydown(event) {
    if (!ui.modal || ui.modal.hidden) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeDialog();
      return;
    }
    if (event.key === "Tab") trapFocus(event);
  }

  function trapFocus(event) {
    if (!ui.panel) return;
    var items = Array.prototype.filter.call(
      ui.panel.querySelectorAll(FOCUSABLE),
      function (el) {
        return !el.hidden && el.offsetParent !== null;
      }
    );
    if (!items.length) return;
    var first = items[0];
    var last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  /* ------------------------------------------------------ release content -- */

  function releaseUrl() {
    var release = state.release || {};
    if (typeof release.url === "string" && /^https?:\/\//i.test(release.url)) return release.url;
    return RELEASES_PAGE + "/latest";
  }

  function pageUrl() {
    var release = state.release || {};
    if (typeof release.page_url === "string" && /^https?:\/\//i.test(release.page_url)) {
      return release.page_url;
    }
    return RELEASES_PAGE;
  }

  function formatDate(value) {
    if (!value) return "";
    var date = new Date(value);
    if (isNaN(date.getTime())) return "";
    var month = String(date.getMonth() + 1).padStart(2, "0");
    var day = String(date.getDate()).padStart(2, "0");
    return date.getFullYear() + "-" + month + "-" + day;
  }

  function zipAsset(release) {
    var assets = release && Array.isArray(release.assets) ? release.assets : [];
    for (var i = 0; i < assets.length; i += 1) {
      var asset = assets[i];
      if (!asset || typeof asset.name !== "string") continue;
      if (!/\.zip$/i.test(asset.name)) continue;
      if (typeof asset.download_url !== "string" || !/^https:\/\//i.test(asset.download_url)) continue;
      return asset;
    }
    return null;
  }

  function cutAtBoundary(text, limit) {
    var slice = text.slice(0, limit);
    var newline = slice.lastIndexOf("\n");
    if (newline > limit * 0.6) return slice.slice(0, newline);
    return slice;
  }

  function renderNotes(host, markdown) {
    host.textContent = "";
    var source = textOf(markdown).replace(/\r\n?/g, "\n");
    var truncated = source.length > NOTES_LIMIT;
    var visible = truncated ? cutAtBoundary(source, NOTES_LIMIT) : source;
    renderBlocks(host, visible.split("\n"), 0);
    if (!host.firstChild) {
      host.appendChild(node("p", { class: "update-empty", text: "暂无更新说明，可打开下载页查看。" }));
    }
    if (truncated) {
      var more = node("p", { class: "update-more" });
      more.appendChild(
        node("a", {
          href: releaseUrl(),
          target: "_blank",
          rel: "noopener noreferrer",
          text: "在 GitHub 上查看完整说明",
        })
      );
      host.appendChild(more);
    }
  }

  function renderBlocks(host, lines, depth) {
    var paragraph = [];
    var list = null;

    function flushParagraph() {
      if (!paragraph.length) return;
      var p = node("p");
      appendInline(p, paragraph.join(" "), 0);
      host.appendChild(p);
      paragraph = [];
    }

    function flushList() {
      list = null;
    }

    function pushListItem(tag, text) {
      if (!list || list.tag !== tag) {
        list = { tag: tag, el: node(tag, { class: "update-list" }) };
        host.appendChild(list.el);
      }
      var li = node("li");
      appendInline(li, text, 0);
      list.el.appendChild(li);
    }

    var i = 0;
    while (i < lines.length) {
      var raw = lines[i];
      var trim = raw.trim();

      if (!trim) {
        flushParagraph();
        flushList();
        i += 1;
        continue;
      }

      if (/^```/.test(trim)) {
        flushParagraph();
        flushList();
        var code = [];
        i += 1;
        while (i < lines.length && !/^```/.test(lines[i].trim())) {
          code.push(lines[i]);
          i += 1;
        }
        if (i < lines.length) i += 1;
        host.appendChild(node("pre", { class: "update-code" }, [node("code", { text: code.join("\n") })]));
        continue;
      }

      if (depth === 0) {
        var alert = /^>\s*\[!(IMPORTANT|NOTE|WARNING|TIP|CAUTION)\]\s*$/i.exec(trim);
        if (alert) {
          flushParagraph();
          flushList();
          var alertBody = [];
          i += 1;
          while (i < lines.length && /^\s*>/.test(lines[i])) {
            alertBody.push(lines[i].replace(/^\s*>\s?/, ""));
            i += 1;
          }
          host.appendChild(renderCallout(alert[1].toUpperCase(), alertBody));
          continue;
        }
        if (/^>/.test(trim)) {
          flushParagraph();
          flushList();
          var quote = [];
          while (i < lines.length && /^\s*>/.test(lines[i])) {
            quote.push(lines[i].replace(/^\s*>\s?/, ""));
            i += 1;
          }
          var quoteP = node("p");
          appendInline(quoteP, quote.join(" "), 0);
          host.appendChild(node("blockquote", { class: "update-quote" }, [quoteP]));
          continue;
        }
      }

      var heading = /^(#{1,6})\s+(.*)$/.exec(trim);
      if (heading) {
        flushParagraph();
        flushList();
        var level = Math.min(heading[1].length + 2, 6);
        var h = node("h" + level, { class: "update-note-heading" });
        appendInline(h, heading[2], 0);
        host.appendChild(h);
        i += 1;
        continue;
      }

      if (/^([-*_])(\s*\1){2,}\s*$/.test(trim)) {
        flushParagraph();
        flushList();
        host.appendChild(node("hr", { class: "update-rule" }));
        i += 1;
        continue;
      }

      var bullet = /^[-*+]\s+(.*)$/.exec(trim);
      if (bullet) {
        flushParagraph();
        pushListItem("ul", bullet[1]);
        i += 1;
        continue;
      }

      var ordered = /^\d+[.)]\s+(.*)$/.exec(trim);
      if (ordered) {
        flushParagraph();
        pushListItem("ol", ordered[1]);
        i += 1;
        continue;
      }

      flushList();
      paragraph.push(trim);
      i += 1;
    }
    flushParagraph();
  }

  function renderCallout(kind, lines) {
    var label = ALERT_LABELS[kind] || "提示";
    var aside = node("aside", {
      class: "update-callout",
      "data-alert": kind.toLowerCase(),
      role: "note",
      "aria-label": label,
    });
    aside.appendChild(node("p", { class: "update-callout-label", text: label }));
    var body = node("div", { class: "update-callout-body" });

    var paragraph = [];
    var listEl = null;

    function flushParagraph() {
      if (!paragraph.length) return;
      var p = node("p");
      appendInline(p, paragraph.join(" "), 0);
      body.appendChild(p);
      paragraph = [];
    }

    lines.forEach(function (raw) {
      var trim = raw.trim();
      if (!trim) {
        flushParagraph();
        listEl = null;
        return;
      }
      var bullet = /^[-*+]\s+(.*)$/.exec(trim);
      if (bullet) {
        flushParagraph();
        if (!listEl) {
          listEl = node("ul", { class: "update-list" });
          body.appendChild(listEl);
        }
        var li = node("li");
        appendInline(li, bullet[1], 0);
        listEl.appendChild(li);
        return;
      }
      if (listEl && /^\s{2,}\S/.test(raw)) {
        appendInline(listEl.lastChild, " " + trim, 0);
        return;
      }
      listEl = null;
      paragraph.push(trim);
    });
    flushParagraph();
    aside.appendChild(body);
    return aside;
  }

  var INLINE_PATTERNS = [
    { type: "code", re: /`([^`\n]+)`/ },
    { type: "link", re: /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/ },
    { type: "autolink", re: /<(https?:\/\/[^\s>]+)>/ },
    { type: "bold", re: /\*\*([^*\n]+)\*\*/ },
    { type: "bold", re: /__([^_\n]+)__/ },
    { type: "em", re: /\*([^*\n]+)\*/ },
    { type: "em", re: /(?<![\w])_([^_\n]+)_(?![\w])/ },
  ];

  function appendInline(parent, text, depth) {
    var rest = textOf(text);
    var cursor = 0;
    var guard = 0;
    var max = depth || 0;
    while (cursor < rest.length && guard < 500) {
      guard += 1;
      var best = null;
      for (var i = 0; i < INLINE_PATTERNS.length; i += 1) {
        var pattern = INLINE_PATTERNS[i];
        var re = new RegExp(pattern.re.source, "g");
        re.lastIndex = cursor;
        var match = re.exec(rest);
        if (match && (!best || match.index < best.match.index)) {
          best = { type: pattern.type, match: match };
        }
      }
      if (!best) {
        parent.appendChild(document.createTextNode(rest.slice(cursor)));
        return;
      }
      var m = best.match;
      if (m.index > cursor) parent.appendChild(document.createTextNode(rest.slice(cursor, m.index)));
      if (best.type === "code") {
        parent.appendChild(node("code", { class: "update-inline-code", text: m[1] }));
      } else if (best.type === "link" || best.type === "autolink") {
        var href = best.type === "link" ? m[2] : m[1];
        var label = best.type === "link" ? m[1] : m[1];
        var anchor = node("a", {
          href: href,
          target: "_blank",
          rel: "noopener noreferrer",
          text: label,
        });
        parent.appendChild(anchor);
      } else if (best.type === "bold") {
        var strong = node("strong");
        if (max < 3) appendInline(strong, m[1], max + 1);
        else strong.textContent = m[1];
        parent.appendChild(strong);
      } else if (best.type === "em") {
        var em = node("em");
        if (max < 3) appendInline(em, m[1], max + 1);
        else em.textContent = m[1];
        parent.appendChild(em);
      }
      cursor = m.index + m[0].length;
    }
    if (cursor < rest.length) parent.appendChild(document.createTextNode(rest.slice(cursor)));
  }

  /* -------------------------------------------------------------- dialog -- */

  function fillDialog() {
    if (!ui.modal) return;
    var payload = state.payload || {};
    var release = state.release || {};
    var current = state.current || "";
    var latest = state.latest || "";
    var hasUpdate = !!payload.update_available && !!latest;

    ui.title.textContent = hasUpdate ? "发现新版本" : "检查更新";
    ui.current.textContent = current ? "当前 v" + current : "当前版本未知";
    ui.latest.textContent = latest ? "最新 v" + latest : "最新版本未知";
    ui.versions.hidden = !hasUpdate;

    var published = formatDate(release.published_at);
    var hasNotes = !!(release.notes && String(release.notes).trim());
    var metaParts = [];
    if (published) metaParts.push("发布于 " + published);
    if (hasUpdate && hasNotes) metaParts.push("更新说明");
    if (hasUpdate) {
      ui.meta.textContent = metaParts.length ? metaParts.join(" · ") : "更新说明见 GitHub";
    } else {
      ui.meta.textContent = "";
    }
    ui.meta.hidden = !hasUpdate;

    ui.notes.textContent = "";
    if (!hasUpdate) {
      ui.notes.appendChild(
        node("p", {
          class: "update-empty",
          text: current ? "已是最新版本 v" + current : "已是最新版本",
        })
      );
    } else if (hasNotes) {
      renderNotes(ui.notes, release.notes);
    } else {
      ui.notes.appendChild(
        node("p", { class: "update-empty", text: "作者没有填写更新说明，可打开下载页查看。" })
      );
    }

    ui.skip.hidden = !hasUpdate;
    ui.later.hidden = !hasUpdate;
    ui.page.href = pageUrl();

    var asset = hasUpdate ? zipAsset(release) : null;
    state.assetName = asset ? asset.name : "";
    ui.download.hidden = !hasUpdate || !asset;
    if (asset && !state.downloading) {
      ui.download.disabled = false;
      ui.download.textContent = "下载更新";
    }

    if (!state.downloading) {
      ui.progress.hidden = true;
      ui.progressTrack.setAttribute("aria-valuenow", "0");
      ui.bar.style.width = "0%";
      ui.progressText.textContent = "";
      ui.hint.className = "update-hint";
      ui.hint.textContent = "";
      ui.openFolder.hidden = true;
      state.downloadPath = "";
    }
    if (hasUpdate) resumeDownloadState();
  }

  function openDialog(opener) {
    ensureEntry();
    ensureDialog();
    if (!ui.modal) return;
    state.opener = opener || document.activeElement || null;
    fillDialog();
    ui.modal.hidden = false;
    document.body.classList.add("update-open");
    if (ui.entry) ui.entry.setAttribute("aria-expanded", "true");
    if (!state.payload) refreshQuietly();
    window.setTimeout(function () {
      if (ui.close) ui.close.focus();
    }, 0);
  }

  function closeDialog() {
    if (!ui.modal || ui.modal.hidden) return;
    ui.modal.hidden = true;
    document.body.classList.remove("update-open");
    if (ui.entry) ui.entry.setAttribute("aria-expanded", "false");
    var target =
      state.opener && state.opener.isConnected && typeof state.opener.focus === "function"
        ? state.opener
        : ui.entry && !ui.entry.hidden
        ? ui.entry
        : null;
    state.opener = null;
    if (target) {
      window.setTimeout(function () {
        try {
          target.focus();
        } catch (err) {
          /* ignore */
        }
      }, 0);
    }
  }

  /* ----------------------------------------------------------- badge/skip -- */

  function syncBadge(show, latest) {
    if (!ui.entry) return;
    if (show) {
      var label = "有新版本" + (latest ? " v" + latest : "");
      if (ui.label) ui.label.textContent = label;
      ui.entry.title = "发现新版本" + (latest ? " v" + latest : "") + "，点击查看";
      ui.entry.hidden = false;
    } else {
      ui.entry.hidden = true;
      ui.entry.setAttribute("aria-expanded", "false");
    }
  }

  async function skipVersion() {
    if (state.skipping) return;
    var version = state.latest || (state.payload && state.payload.latest) || "";
    state.skipping = true;
    ui.skip.disabled = true;
    try {
      var data = await api("/api/update/skip", { method: "POST", body: { version: version } });
      if (data && data.ok === false) throw new Error(data.error || "");
      if (state.payload) state.payload.skipped = true;
      syncBadge(false);
      closeDialog();
    } catch (err) {
      toast("无法保存跳过设置，请稍后重试", "bad");
    } finally {
      state.skipping = false;
      ui.skip.disabled = false;
    }
  }

  /* ---------------------------------------------------------- preferences -- */

  function syncAutoCheck(value) {
    if (!ui.autoCheck || typeof value !== "boolean") return;
    ui.autoCheck.checked = value;
  }

  async function onAutoCheckChange() {
    if (!ui.autoCheck) return;
    var want = ui.autoCheck.checked;
    try {
      var data = await api("/api/update/prefs", { method: "POST", body: { auto_check: want } });
      if (data && typeof data.auto_check === "boolean") ui.autoCheck.checked = data.auto_check;
    } catch (err) {
      ui.autoCheck.checked = !want;
      toast("无法保存自动检查设置", "bad");
    }
  }

  function setCheckResult(message) {
    if (ui.checkResult) ui.checkResult.textContent = message || "";
  }

  async function checkNow() {
    if (!ui.checkNow || ui.checkNow.disabled) return;
    var original = ui.checkNow.textContent || "检查更新";
    ui.checkNow.disabled = true;
    ui.checkNow.textContent = "检查中…";
    setCheckResult("");
    try {
      var payload = await api("/api/update/check?force=1");
      if (payload) applyPayload(payload);
      if (!payload || (payload.ok === false && !payload.release)) {
        setCheckResult("无法检查更新");
      } else if (payload.update_available) {
        setCheckResult("发现新版本 v" + textOf(payload.latest));
      } else {
        setCheckResult("已是最新版本");
      }
    } catch (err) {
      setCheckResult("无法检查更新");
    } finally {
      ui.checkNow.disabled = false;
      ui.checkNow.textContent = original;
    }
  }

  /* ------------------------------------------------------------- download -- */

  function stopPoll() {
    if (state.pollTimer) {
      window.clearInterval(state.pollTimer);
      state.pollTimer = 0;
    }
  }

  function schedulePoll() {
    if (state.pollTimer) return;
    state.pollTimer = window.setInterval(pollStatus, POLL_MS);
  }

  async function pollStatus() {
    try {
      var data = await api("/api/update/download/status");
      state.pollMisses = 0;
      if (data && data.download) handleDownload(data.download);
    } catch (err) {
      state.pollMisses += 1;
      if (state.pollMisses >= 3) failDownload("无法获取下载进度，请稍后重试");
    }
  }

  function setProgress(percent, message) {
    var value = Math.max(0, Math.min(100, Number(percent) || 0));
    if (ui.bar) ui.bar.style.width = value + "%";
    if (ui.progressTrack) ui.progressTrack.setAttribute("aria-valuenow", String(Math.round(value)));
    if (ui.progressText && message !== undefined) ui.progressText.textContent = message;
  }

  function sizeLabel(bytes) {
    var size = Number(bytes) || 0;
    if (size < 1024) return size + " B";
    if (size < 1024 * 1024) return (size / 1024).toFixed(0) + " KB";
    if (size < 1024 * 1024 * 1024) return (size / 1024 / 1024).toFixed(1) + " MB";
    return (size / 1024 / 1024 / 1024).toFixed(2) + " GB";
  }

  function resetDownloadButton(label) {
    if (!ui.download) return;
    ui.download.disabled = false;
    ui.download.textContent = label || "下载更新";
  }

  function failDownload(message) {
    stopPoll();
    state.downloading = false;
    state.pollMisses = 0;
    if (!ui.progress) return;
    ui.progress.hidden = false;
    ui.hint.className = "update-hint bad";
    ui.hint.textContent = message || "下载失败，请稍后重试";
    ui.openFolder.hidden = true;
    resetDownloadButton("重试下载");
  }

  function handleDownload(dl) {
    if (!dl || !ui.progress) return;
    var percent = Math.max(0, Math.min(100, Number(dl.percent) || 0));
    var currentState = textOf(dl.state);

    if (currentState === "running") {
      state.downloading = true;
      ui.progress.hidden = false;
      var message = percent > 0 ? "下载中 " + Math.round(percent) + "%" : "正在连接…";
      if (dl.total) message += " · " + sizeLabel(dl.received) + " / " + sizeLabel(dl.total);
      setProgress(percent, message);
      ui.download.disabled = true;
      ui.download.textContent = "下载中…";
      ui.openFolder.hidden = true;
      return;
    }
    if (currentState === "done") {
      stopPoll();
      state.downloading = false;
      state.pollMisses = 0;
      setProgress(100, "下载完成");
      ui.progress.hidden = false;
      ui.hint.className = "update-hint";
      ui.hint.textContent = "";
      if (dl.sha256_ok === false) {
        ui.hint.className = "update-hint bad";
        ui.hint.textContent = "文件校验失败，请重试或打开下载页手动下载。";
        ui.openFolder.hidden = true;
      } else {
        state.downloadPath = textOf(dl.path);
        ui.hint.appendChild(
          node("span", { class: "update-path", text: "已下载到 " + (dl.path || "下载文件夹") })
        );
        ui.hint.appendChild(
          node("span", {
            class: "update-unzip-hint",
            text: "解压后覆盖原程序目录即可完成更新（会保留设置与批注）",
          })
        );
        ui.openFolder.hidden = !dl.path;
      }
      resetDownloadButton("重新下载");
      return;
    }
    if (currentState === "error") {
      failDownload(textOf(dl.error) || "下载失败，请稍后重试");
      return;
    }
    if (currentState === "cancelled") {
      stopPoll();
      state.downloading = false;
      setProgress(percent, "下载已取消");
      resetDownloadButton("重新下载");
    }
  }

  async function startDownload() {
    if (state.downloading) return;
    state.downloading = true;
    state.pollMisses = 0;
    ui.download.disabled = true;
    ui.download.textContent = "下载中…";
    ui.progress.hidden = false;
    ui.openFolder.hidden = true;
    ui.hint.className = "update-hint";
    ui.hint.textContent = "";
    setProgress(0, "正在准备下载…");
    try {
      var data = await api("/api/update/download", {
        method: "POST",
        body: { asset: state.assetName || "" },
      });
      if (data && data.ok === false) throw new Error(data.error || "没有可下载的安装包");
      handleDownload(data && data.download);
      schedulePoll();
    } catch (err) {
      failDownload(softError(err, "无法开始下载，请稍后重试"));
    }
  }

  function parentDir(path) {
    var value = textOf(path);
    var cut = Math.max(value.lastIndexOf("\\"), value.lastIndexOf("/"));
    return cut > 0 ? value.slice(0, cut) : value;
  }

  async function openFolder() {
    var folder = parentDir(state.downloadPath);
    if (!folder) return;
    try {
      var data = await api("/api/open", { method: "POST", body: { path: folder } });
      if (data && data.ok === false) throw new Error(data.error || "");
    } catch (err) {
      toast("无法打开文件夹，请手动前往下载目录", "bad");
    }
  }

  async function resumeDownloadState() {
    if (state.resumePending || state.downloading) return;
    state.resumePending = true;
    try {
      var data = await api("/api/update/download/status");
      var dl = data && data.download;
      if (!dl || !dl.state || dl.state === "idle") return;
      if (dl.state === "running") {
        state.downloading = true;
        ui.progress.hidden = false;
        ui.download.disabled = true;
        ui.download.textContent = "下载中…";
        handleDownload(dl);
        schedulePoll();
      } else if (dl.state === "done") {
        handleDownload(dl);
      }
    } catch (err) {
      /* soft: the status route may be missing on an old backend */
    } finally {
      state.resumePending = false;
    }
  }

  /* ----------------------------------------------------------------- data -- */

  function applyPayload(payload, options) {
    if (!payload || typeof payload !== "object") return;
    var opts = options || {};
    state.payload = payload;
    state.release = payload.release || null;
    if (payload.current) state.current = textOf(payload.current);
    var latest = payload.latest || (state.release && state.release.version) || "";
    if (latest) state.latest = textOf(latest);
    syncAutoCheck(payload.auto_check);
    if (ui.currentVersion) {
      ui.currentVersion.textContent = state.current ? "v" + state.current : "—";
    }
    syncBadge(!!payload.update_available && !payload.skipped, state.latest);
    if (opts.toast && payload.update_available && !payload.skipped && state.latest) {
      maybeToast(state.latest);
    }
    if (!ui.modal || ui.modal.hidden) return;
    fillDialog();
  }

  function maybeToast(version) {
    var seen = "";
    try {
      seen = window.localStorage.getItem(SEEN_KEY) || "";
    } catch (err) {
      seen = "";
    }
    if (seen === version) return;
    try {
      window.localStorage.setItem(SEEN_KEY, version);
    } catch (err) {
      /* private mode / disabled storage: toast anyway */
    }
    toast("发现新版本 v" + version + "，点击顶部提示查看");
  }

  function needsNetworkCheck(payload) {
    if (!payload) return false;
    if (payload.auto_check === false) return false;
    if (!payload.checked_at) return true;
    if (payload.stale === true) return true;
    return Date.now() / 1000 - Number(payload.checked_at) > CACHE_TTL;
  }

  async function refreshQuietly() {
    try {
      var payload = await api("/api/update/check?force=1");
      if (payload) {
        applyPayload(payload);
        if (ui.modal && !ui.modal.hidden) fillDialog();
      }
    } catch (err) {
      /* soft failure: the dialog keeps its placeholder state */
    }
  }

  async function networkCheck() {
    try {
      var payload = await api("/api/update/check");
      if (payload) applyPayload(payload, { toast: true });
    } catch (err) {
      /* never surface network errors as dialogs */
    }
  }

  /* ------------------------------------------------------------ settings -- */

  function ensureSettings() {
    var body = $("#settings-modal .settings-body");
    if (!body || $("#update-settings-section")) return;

    ui.currentVersion = node("span", {
      class: "update-version-value",
      id: "update-current-version",
      text: "—",
    });
    var rowVersion = node("div", { class: "row" }, [
      node("span", { class: "row-label", text: "当前版本" }),
      ui.currentVersion,
    ]);

    ui.checkResult = node("p", {
      class: "hint update-check-result",
      id: "update-check-result",
      "aria-live": "polite",
    });
    ui.checkNow = node("button", {
      class: "btn btn-secondary small",
      id: "update-check-now",
      type: "button",
      text: "检查更新",
    });
    var rowCheck = node("div", { class: "row" }, [
      node("div", { class: "row-text" }, [
        node("span", { class: "row-label", text: "检查更新" }),
        ui.checkResult,
      ]),
      ui.checkNow,
    ]);

    ui.autoCheck = node("input", { type: "checkbox", id: "update-auto-check" });
    var rowAuto = node("div", { class: "row toggle-row" }, [
      node("div", { class: "row-text" }, [
        node("label", {
          class: "row-label",
          for: "update-auto-check",
          text: "自动检查更新",
        }),
        node("p", { class: "hint", text: "启动时检查一次，发现新版本会在顶部提示" }),
      ]),
      node("label", { class: "switch" }, [ui.autoCheck, node("span", { class: "track" })]),
    ]);

    var section = node("section", {
      class: "group",
      id: "update-settings-section",
      "aria-label": "更新",
    }, [
      node("div", { class: "group-card" }, [
        node("p", { class: "subhead", text: "更新" }),
        node("div", { class: "rows" }, [rowVersion, rowCheck, rowAuto]),
      ]),
    ]);

    var zotero = body.querySelector('section[aria-label="Zotero 集成"]');
    if (zotero) body.insertBefore(section, zotero);
    else body.appendChild(section);

    ui.checkNow.addEventListener("click", function () {
      checkNow();
    });
    ui.autoCheck.addEventListener("change", function () {
      onAutoCheckChange();
    });
    ui.settingsSection = section;
  }

  /* ----------------------------------------------------------------- init -- */

  async function init() {
    if (state.started) return;
    state.started = true;
    ensureEntry();
    ensureDialog();
    ensureSettings();

    var cached = null;
    try {
      cached = await api("/api/update/check?cache_only=1");
    } catch (err) {
      cached = null;
    }
    if (cached) applyPayload(cached);
    if (!cached) syncAutoCheck(true);
    if (needsNetworkCheck(cached)) {
      window.setTimeout(function () {
        networkCheck();
      }, AUTO_CHECK_DELAY);
    }
  }

  function start() {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", init);
    } else {
      init();
    }
  }

  /* Debug handle (used by tests); not a public API. */
  window.ReadPIUpdate = {
    version: "1.0.0",
    open: function () {
      openDialog(ui.entry || null);
    },
    close: closeDialog,
    check: networkCheck,
    refresh: refreshQuietly,
    state: function () {
      return {
        current: state.current,
        latest: state.latest,
        downloading: state.downloading,
        payload: state.payload,
      };
    },
  };

  start();
})();

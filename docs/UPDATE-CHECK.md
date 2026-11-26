# 应用内检查更新：设计与发布说明

本页面向**维护者**：说明 ReadPI 如何发现新版本、用户会看到什么、各种失败情况怎么降级，
以及每次发版前必须逐项确认的清单。普通使用者只需要知道「顶栏出现『有新版本 vX.Y.Z』就点它」，
这部分写在 [README 的「检查更新」](../README.md#检查更新)。

适用版本：ReadPI **1.9.0** 及以后。实现分三块：

| 位置 | 职责 |
| --- | --- |
| `core/update.py` | 版本比较、多来源抓取、缓存、跳过/自动检查偏好、下载与 SHA-256 校验 |
| `app.py` | `/api/update/*` 路由（仅本机可访问）、`APP_VERSION`、`API_FEATURES` 中的 `update-check` |
| `web/update.js` + `web/update.css` | 顶栏提示、更新弹窗、设置里的检查更新区域；自包含，不依赖 `app.js` / `shared.js` |

`index.html` 与 `library.html` 都会加载这套脚本和样式；数据目录仍然是
`%APPDATA%\BabelDOC-Studio`。

## 1. 设计目标

- 让下载了免安装包的用户**在应用内**知道有新版本，而不是定期去翻 GitHub Releases。
- 只做「提醒 → 下载 → 引导解压」，**不静默替换正在运行的程序**：便携包无法覆盖自己正在使用的
  运行时，自动安装既不可靠也不安全。
- 任何网络问题都只能变成一句轻提示，不弹错误框、不拖慢启动、不影响翻译和阅读。
- 只有用户点「下载更新」才会下载安装包；检查更新本身只取几十 KB 的 JSON / Atom。

## 2. 用户看到什么

| 位置 | 内容 | 出现条件 |
| --- | --- | --- |
| 顶栏右侧 | 「有新版本 v1.9.0」按钮 + 呼吸圆点 | 检查到更新，且用户没有「跳过此版本」 |
| 更新弹窗 | 当前版本 → 最新版本、发布日期、更新说明、下载进度 | 点击顶栏按钮 |
| 弹窗底部 | 跳过此版本 / 稍后提醒 / 打开下载页 / 下载更新 | 检查到更新 |
| 翻译设置 → 检查更新 | 当前版本、检查更新按钮与结果、自动检查更新开关 | 打开设置面板 |
| 提示条 | `发现新版本 v1.9.0，点击顶部提示查看` | 每个版本最多一次（`localStorage` 记录） |

启动时序（`web/update.js`）：

1. 先读缓存（`GET /api/update/check?cache_only=1`），有更新就立刻画出顶栏按钮，不等待网络；
2. 自动检查开启、且缓存超过 6 小时或不存在时，约 1.5 秒后发一次真实请求；
3. 只显示按钮和一次性提示条，**不会每次启动都自动弹窗**；弹窗只由用户点击打开。

## 3. 检测流程

### 3.1 版本比较

`version_tuple()` 取字符串里第一个 `\d+(\.\d+)*` 作为数字核心，补齐 / 截断为三个整数；
`is_newer()` 做严格 `>` 比较。以下写法都能解析：

- `v1.9.0`、`V1.9.0`、`1.9.0`、`1.9`、`ReadPI 1.9.0`；
- 预发布 `1.9.0-beta.1`、`-rc.1`、` beta`：数字核心相同的正式版优先，预发布不会宣布自己高于
  正式版；反过来，1.9.0 的用户也不会被 `1.9.0-rc.1` 提示。

### 3.2 数据来源（按顺序尝试，第一个给出可用版本的来源胜出）

1. **`READPI_UPDATE_FEED` 覆盖**：测试、离线验证和内网镜像用。值以 `http://` / `https://` 开头
   时按 URL 取 JSON，否则当作本地文件路径读取。JSON 必须是 **GitHub API 形状**
   （`tag_name` / `name` / `html_url` / `published_at` / `body` / `assets`）。
2. **GitHub API**：`https://api.github.com/repos/PiDesign-314/ReadPI/releases/latest`，
   请求头 `Accept: application/vnd.github+json` 与
   `User-Agent: ReadPI/<APP_VERSION> (+https://github.com/PiDesign-314/ReadPI)`。
   只返回**已发布、非草稿、非预发布**的最新版本。
3. **Atom 订阅**：`https://github.com/PiDesign-314/ReadPI/releases.atom`。没有 API 限流，
   取最新 `<entry>` 的标题 / 链接 / 更新时间 / 内容，版本号来自标题或
   `/releases/tag/<tag>` 链接。
4. **重定向探测**：请求 `https://github.com/PiDesign-314/ReadPI/releases/latest`，从
   `resp.geturl()` 里取 `/releases/tag/<tag>`。这一级只有版本号，没有更新说明和附件。

归一化后的结构固定为
`tag` / `version` / `name` / `url` / `page_url` / `published_at` / `notes` / `notes_excerpt` /
`assets`；缺失或异常字段降级为空字符串，**不抛异常**。`assets` 只保留 `https://` 链接，并自动
配对同名 `<asset>.sha256`。`notes` 最多保留 20000 字符，`notes_excerpt` 是去 HTML、压缩空白后的
前 600 字符，供列表类场景使用。

任何一级抓取失败（超时、代理、DNS、451、403 限流、JSON 解析失败）都只是继续下一级；全部失败时
抛 `UpdateError`，由 `check()` 转换成中文轻提示，不会冒到路由外面。

### 3.3 缓存

缓存文件是 `%APPDATA%\BabelDOC-Studio\update-cache.json`，写入方式为临时文件 + `os.replace`
原子替换；只读配置目录下写入失败会被忽略，不影响检查本身。

```json
{"checked_at": 1794244174.7, "ok": true, "error": "", "source": "api",
 "release": {"tag": "v1.9.0", "version": "1.9.0", "…": "…"}}
```

- **成功结果缓存 6 小时**（`CACHE_TTL`）：期间启动直接复用，不重复请求 GitHub；
- **失败结果缓存 10 分钟**（`FAIL_TTL`）：10 分钟内不反复重试，之后自动再试；
- 网络失败但缓存里有上一次成功结果时，返回旧结果并标记 `stale: true`，只用于提示；
- `cache_only=1` 只读缓存、绝不联网，供页面首屏立刻画出顶栏提示。

### 3.4 跳过与自动检查

偏好存在 `settings.json`，`core/config.py` 的 `DEFAULTS` 已包含这两项，旧设置文件会合并补齐：

```json
{"update_auto_check": true, "update_skip_version": ""}
```

- `update_auto_check`：控制启动时是否自动检查；关闭后只能手动点「检查更新」。
- `update_skip_version`：用户点「跳过此版本」后记录版本号；仍有更新但不提示，遇到更新的版本会
  重新提示。只存 `1.9.0` 这种纯版本号，空字符串表示清除。

## 4. HTTP 接口

所有 `/api/update/*` 路由**只接受本机请求**：`request.remote_addr` 不在
`{"127.0.0.1", "::1"}` 时返回 `403 {"error": "仅本机可用"}`（与 `/api/app/restart` 一致）。
每个路由都捕获异常并返回 JSON，不会把异常抛给 Flask。

| 方法与路径 | 请求 | 响应 |
| --- | --- | --- |
| `GET /api/update/check` | `force=1` 强制联网刷新；`cache_only=1` 只读缓存 | §4.1 的结构 |
| `GET /api/update/download/status` | – | `{"ok": true, "download": {…}}` |
| `POST /api/update/download` | `{"asset": "<可选，资产名>"}` | `{"ok": true, "download": {…}}`；没有可下载资产时 `400 {"error": "没有可下载的安装包"}` |
| `POST /api/update/download/cancel` | – | `{"ok": true, "download": {…}}` |
| `POST /api/update/skip` | `{"version": "1.9.0"}`，`{"version": ""}` 清除 | `{"ok": true, "skip_version": "…"}` |
| `POST /api/update/prefs` | `{"auto_check": true \| false}` | `{"ok": true, "auto_check": true}` |

### 4.1 `GET /api/update/check` 返回结构

```json
{
  "ok": true,
  "current": "1.8.1",
  "latest": "1.9.0",
  "update_available": true,
  "skipped": false,
  "skip_version": "",
  "auto_check": true,
  "release": {
    "tag": "v1.9.0",
    "version": "1.9.0",
    "name": "ReadPI 1.9.0",
    "url": "https://github.com/PiDesign-314/ReadPI/releases/tag/v1.9.0",
    "page_url": "https://github.com/PiDesign-314/ReadPI/releases",
    "published_at": "2026-11-01T09:00:00Z",
    "notes": "## 主要更新\n- 应用内检查更新……",
    "notes_excerpt": "主要更新 - 应用内检查更新……",
    "assets": [
      {
        "name": "BabelDOC-Studio-Windows-x64.zip",
        "size": 123456789,
        "download_url": "https://github.com/PiDesign-314/ReadPI/releases/download/v1.9.0/BabelDOC-Studio-Windows-x64.zip",
        "sha256_url": "https://github.com/PiDesign-314/ReadPI/releases/download/v1.9.0/BabelDOC-Studio-Windows-x64.zip.sha256"
      }
    ]
  },
  "source": "api",
  "checked_at": 1794244174.7,
  "stale": false,
  "error": ""
}
```

- `ok`：是否拿到了可用版本（可能是缓存里的旧结果）；
- `latest` 为空表示完全不知道最新版本；`update_available` 只在 `latest > current` 时为真；
- `skipped` 是「有更新但用户跳过」的结果，前端据此隐藏顶栏按钮；
- `source` 取值 `api` / `atom` / `redirect` / `feed` / `cache` / `none`，便于排查；
- `error` 是中文、可直接展示；正常时为空字符串。

### 4.2 下载状态

```json
{"state": "idle", "version": "1.9.0", "asset": "BabelDOC-Studio-Windows-x64.zip",
 "path": "C:\\Users\\me\\Downloads\\BabelDOC-Studio-Windows-x64.zip",
 "received": 12345678, "total": 123456789, "percent": 9,
 "sha256_ok": true, "error": "", "started_at": 0.0, "finished_at": 0.0}
```

`state` 为 `idle` / `running` / `done` / `error` / `cancelled`。同一时间只允许一个下载：
已有任务在跑时再次 `POST /api/update/download` 直接返回当前状态，不报错。

## 5. 下载与校验

- 目标目录：系统「下载」文件夹（`Path.home() / "Downloads"`）；不存在时退到
  `%APPDATA%\BabelDOC-Studio\updates`，文件名沿用资产名。
- 先写 `<文件名>.part`，下载完成后 `os.replace` 成正式文件；分块 256 KiB，单次请求 `timeout=20`。
- 资产带同名 `.sha256` 时，下载完再取校验文件（纯文本 `<hex>  <文件名>`）比对；不一致就**删除**
  下载的文件，`state: "error"` 并给出中文原因。
- 下载完成不会自动解压或覆盖，只提示「解压后覆盖原程序目录即可完成更新（会保留设置与批注）」，
  并提供「打开文件夹」按钮（`POST /api/open`）。
- 下载只在用户点击「下载更新」时发生；弹窗每 700 ms 轮询一次状态，进度条带
  `role="progressbar"` 与 `aria-valuenow`。

## 6. 降级行为

| 场景 | 应用表现 |
| --- | --- |
| 完全离线 | 启动不受影响；检查在后台超时（8 秒）后结束。有旧缓存显示旧结果，没有则提示「无法检查更新」，不弹框 |
| `api.github.com` 被墙、超时或 451 | 依次回退 Atom、`/releases/latest` 重定向；都失败则轻提示 |
| API 限流（403 / 429） | 同失败处理；失败结果只缓存 10 分钟，Atom 来源没有该限制 |
| Release 还是草稿 | 三种来源都看不到它，用户端显示「已是最新版本」；发布（Publish）之后才会出现 |
| Release 被标记为 pre-release | `releases/latest` 与 Atom 都不会返回它，不会提示 |
| tag 无法解析出版本号 | 该来源视为无效，继续下一个来源；最终失败只轻提示 |
| 更新说明过长或含 HTML | 按纯文本渲染（逐行 `textContent`，不注入 HTML）；超过 3000 字符折叠，并给「在 GitHub 上查看完整说明」链接 |
| 下载中断、取消或校验失败 | 删除 `.part` / 校验不通过的文件，弹窗显示中文原因，保留「打开下载页」 |
| 设置文件或数据目录只读 | 缓存和偏好写入失败被忽略，检查与下载仍可进行（下载目标退到可用目录） |

## 7. 网络环境注意（中国大陆 / 代理 / IPv4）

- GitHub API 在中国大陆经常超时或被拦截，`github.com` 的 Atom 与重定向也可能不稳。应用把单次
  请求限制在 8 秒，逐级回退，最坏情况只是「无法检查更新」；翻译本身不依赖 GitHub，不受影响。
- 未认证的 GitHub API 限流约 60 次/小时/IP。正常使用有 6 小时缓存，一个 IP 下的多台机器共用
  出口也远低于限额；不要为了「实时」把 `CACHE_TTL` 调小。
- 系统代理：`urllib` 会读取 `HTTP_PROXY` / `HTTPS_PROXY` 环境变量。某些机器优先解析 IPv6，
  而代理或出口只有 IPv4，连接会一直等到 8 秒超时（表现仍是轻提示）。这类网络问题不是代码缺陷；
  需要稳定检查时，把代理设为全局或直连，或用 `READPI_UPDATE_FEED` 指向可访问的内网镜像。
- 检查更新只在应用进程内发起，不会后台常驻、不写日志、不做任何遥测。

## 8. 本地验证

用 `READPI_UPDATE_FEED` 把来源指向本地 fixture，不依赖真实 GitHub：

```powershell
# 1. 造一个 GitHub API 形状的 JSON，版本比当前高
$feed = Join-Path $env:TEMP 'readpi-feed.json'
@'
{
  "tag_name": "v1.9.0",
  "name": "ReadPI 1.9.0",
  "html_url": "https://github.com/PiDesign-314/ReadPI/releases/tag/v1.9.0",
  "published_at": "2026-11-01T09:00:00Z",
  "body": "## 主要更新\n- 应用内检查更新\n- 更新说明直接查看",
  "assets": []
}
'@ | Set-Content -LiteralPath $feed -Encoding utf8

# 2. 指向 fixture 启动应用
$env:READPI_UPDATE_FEED = $feed
python app.py
```

然后确认：

1. 顶栏出现「有新版本 v1.9.0」，点开是弹窗，版本行显示「当前 → 最新」，更新说明按纯文本显示；
2. 「翻译设置」面板里的「检查更新」显示当前版本，点按钮后结果为「发现新版本 v1.9.0」；
3. 点「跳过此版本」后顶栏提示消失，重启也不再提示同一版本；
4. 把 fixture 的 `tag_name` 改成当前 `APP_VERSION`，手动检查应显示「已是最新版本」；
5. 断开网络（或把 `READPI_UPDATE_FEED` 指向不存在的路径）后启动，只出现轻提示，翻译流程照常。

想直接看 HTTP 结果（避开 6 小时缓存）：

```powershell
# 应用默认从 8765 端口起监听，端口被占用时会顺延
curl.exe "http://127.0.0.1:8765/api/update/check?force=1"
```

调试时也可以删掉 `%APPDATA%\BabelDOC-Studio\update-cache.json` 再启动，等同于首次运行。
下载与校验的端到端验证：用一个本地 `http.server` 提供小 ZIP 和同名 `.sha256`，把
`READPI_UPDATE_FEED` 里的资产地址指向 `http://127.0.0.1:<port>/…`；故意改坏校验文件，
应看到文件被删除并报错。

## 9. 发布清单

发版前逐项确认。任何一项漏掉，用户端都会「看不到更新」：

- [ ] `app.py` 的 `APP_VERSION` 已改成这次要发布的版本（例如 `"1.9.0"`），并与 tag 完全一致；
- [ ] tag 形如 `vX.Y.Z`（例如 `v1.9.0`）；只有推送 `v*` tag 才会触发
      `.github/workflows/portable.yml` 构建；
- [ ] CI 创建的 Release 已经 **Publish**：workflow 里用的是 `gh release create --draft`，
      草稿对 `releases/latest`、`releases.atom` 和重定向探测都不可见，用户端不会收到提示；
- [ ] 发布时**不要**勾选「Set as a pre-release」：预发布会被 API 排除，也不会被提示；
- [ ] 资产里保留 `BabelDOC-Studio-Windows-x64.zip` 与
      `BabelDOC-Studio-Windows-x64.zip.sha256` 两个文件（应用靠 `.sha256` 校验下载；缺失时跳过
      校验，只提示下载完成）；
- [ ] Release 正文就是应用里显示的更新说明，发布前确认它能按纯文本正常阅读（标题、列表、
      fenced code 会被识别，HTML 会被当作纯文本）；
- [ ] 本机用 `READPI_UPDATE_FEED` 做一遍上面的「本地验证」，并额外验证「下载更新 → SHA-256
      校验 → 打开文件夹」；
- [ ] 用**上一个正式版**的应用点一次「检查更新」（最好换一个网络 / 代理环境），确认能取到刚发布的
      版本；再在设置里手动点一次「检查更新」，确认「已是最新版本」与「发现新版本」都正确；
- [ ] 发布后回来核对本页「适用版本」和 README 顶部的「主要更新」提示是否已更新到新版本。

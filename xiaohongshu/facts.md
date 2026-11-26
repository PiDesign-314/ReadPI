# ReadPI 小红书事实清单（fact sheet）

> 核对时间：2026-11-10 20:35（仓库快照）。
> 依据：`README.md`、`docs/ZOTERO-INTEGRATION.md`、`docs/AI-READER-SPEC.md`、`使用说明.txt`、`CHANGELOG.md`，并用仓库代码/构建产物交叉验证。
> **注意：核对期间 README / CHANGELOG / 使用说明 正在被并发修改**（新加 v1.9.0「检查更新」章节），所以对这几份文档改用**章节引用**而不是行号；`docs/` 两份文档未被改动，保留行号。
> 只列文档或产物里能查到的事实；查不到的标「未确认」，不要补写。

## 0. 版本基线（所有卖点共用）

- **已发布版本：ReadPI 1.8.1**，更新日志日期 **2026-11-10**（`CHANGELOG.md` §v1.8.1；`app.py` 的 `APP_VERSION = "1.8.1"`）。
- **Zotero 插件：1.0.6**，插件标识 `babeldoc-studio@pidesign.local`，`strict_min_version 7.0`、`strict_max_version 10.*`（`tools/zotero-plugin/manifest.json:4,13,15-16`）。
- **平台：Windows 10/11 x64**，只发 Windows 免安装包；无 macOS / Linux 安装包（`README.md` 顶部平台徽章、§从源码运行、§常见问题「支持 macOS / Linux 吗？」）。
- 发行包文件名 **`BabelDOC-Studio-Windows-x64.zip`**；产品名是 ReadPI，但包名与数据目录沿用 `BabelDOC-Studio`（`README.md` §「下载 Windows 免安装版」）。仓库原名 `Pi_BabelDOC-Studio`，现已更名（`README.md` 文末）。
- 官方定位句（可直接引用原文）：**「把 PDF 论文翻成双语，保留公式、图表和原始排版；翻译、AI 助读、笔记与批注在同一个本地窗口完成。」**（`README.md` 开头）
- 本地优先：Flask 本地服务 + Edge/Chrome 应用窗口；API Key 用 Windows DPAPI 加密；PDF、批注、笔记默认只留本机（`README.md` 开头、§设置与数据；`使用说明.txt`「说明」）。
- **仓库当前正在合并 v1.9.0「应用内检查更新」**：CHANGELOG 顶部已新增 v1.9.0 段、`docs/UPDATE-CHECK.md` 与 `web/update.js` 已出现，但 `app.py` 仍是 `APP_VERSION = "1.8.1"`，未看到后端更新接口 → **未发布、未确认**。文案先按 1.8.1 写，发布前以 `APP_VERSION` 和 GitHub Releases 再核对。

---

## 1. Zotero 集成（第一卖点）

**可写事实**

1. 三个入口：Zotero 文献列表右键、PDF 阅读器工具栏按钮、阅读器页面右键，菜单名都是 **「在 ReadPI 中阅读」**；只对**有本地 PDF 附件**的条目显示（`README.md` §Zotero 集成；`docs/ZOTERO-INTEGRATION.md:52-67`）。
2. 首次打开自动把 PDF 复制接入应用并建立与文献/附件的关联，不用手动导出再上传；应用没启动时会自动启动或引导启动（`docs/ZOTERO-INTEGRATION.md:11-16,74-75`；`README.md` §Zotero 集成）。
3. 再次打开同一附件**复用已有记录：译文、笔记、批注、阅读位置都保留**；关联键是 `libraryID + itemKey + attachmentKey`，内容 SHA-256 兜底，不依赖文件名（`README.md` §Zotero 集成；`docs/ZOTERO-INTEGRATION.md:18-19`）。
4. Zotero 顶部 ReadPI 图标提供 **翻译 / 阅读 / 打开结果库** 三项；「翻译」用应用已保存的设置直接建任务并打开进度页（`docs/ZOTERO-INTEGRATION.md:52-55`；`README.md` §Zotero 集成）。
5. 结果库显示 Zotero **嵌套文件夹**与带本地 PDF 的文献，可搜索、阅读、翻译；有 PDF 缩略图、浅色/深色两套界面（`README.md` §Zotero 集成；`docs/ZOTERO-INTEGRATION.md:55-57`）。
6. 位置衔接：从 Zotero 阅读器发起时定位到**当前页**，从文献列表发起时恢复**上次读到的页**；译文/双语按页映射，交替页模式原文第 n 页 → 输出第 **2n-1** 页（`docs/ZOTERO-INTEGRATION.md:93-105`）。
7. 安装三步：ReadPI「翻译设置 → Zotero 集成 → 下载插件」→ Zotero「工具 → 插件 → 右上角齿轮 → 从文件安装…」→ 装好**无需重启 Zotero**（`docs/ZOTERO-INTEGRATION.md:29-37`；`README.md` §Zotero 集成）。
8. 兼容性：面向 **Zotero 7–10**；插件 `strict_min_version 7.0` / `strict_max_version 10.*`；**1.0.4 已在 Zotero 10.0.8 独立配置实测**，1.0.6 沿用同一标识与工具栏位置并通过插件测试（`docs/ZOTERO-INTEGRATION.md:3-4,43-44`；`tools/zotero-plugin/manifest.json:15-16`）。

**营销可用数字/名字**

- 版本组合：ReadPI **1.8.1** + Zotero 插件 **1.0.6**（`README.md` v1.8.1 TIP）。
- 插件安装包：`dist/babeldoc-zotero-1.0.6.xpi`（核对时本地文件 49,073 字节）；应用内「下载插件」给的下载名是 `babeldoc-zotero.xpi`（`web/index.html` Zotero 集成卡片）。
- 本地服务默认端口 **8765**，被占用自动换；插件扫描 **8765–8804**（`app.py` 的 `_free_port()`；`docs/ZOTERO-INTEGRATION.md:114`）。
- 接入副本路径：`%APPDATA%\BabelDOC-Studio\zotero\imports\<link-id>\<原文件名>.pdf`（`docs/ZOTERO-INTEGRATION.md:81`）。
- 也可从 `http://127.0.0.1:<端口>/api/zotero/plugin.xpi` 下载插件（`docs/ZOTERO-INTEGRATION.md:31-32,149`）。

**注意/限制**

- **单向只读同步**：Zotero → ReadPI；**不会把笔记/批注写回 Zotero**，也不能在 ReadPI 里编辑 Zotero 文献或文件夹（`README.md` §Zotero 集成、§已知限制第 13 条；`docs/ZOTERO-INTEGRATION.md:153`）。
- 只对**已下载到本地**的 PDF 附件显示入口；只有网址、附件没下载或链接失效的条目不显示（`README.md` §常见问题「Zotero 里没有…」；`docs/ZOTERO-INTEGRATION.md:111-112`）。
- 需先启动一次 1.8.1，让它写出 `launch-info.json`，应用关闭时插件才能自动拉起（`docs/ZOTERO-INTEGRATION.md:24-26`）。
- 插件升级是**手动安装**；更新清单不含可自动安装的版本（`docs/ZOTERO-INTEGRATION.md:45`）。
- 旧版应用占着 8765 端口会提示「检测到旧版本」；插件只连 `/api/health` 的 `features` 含 `zotero` 的服务（`docs/ZOTERO-INTEGRATION.md:115`）。
- 只复制 PDF，Zotero 的原文件、目录结构、元数据都不改（`docs/ZOTERO-INTEGRATION.md:87`）。

**未确认**

- 「一键翻译整个 Zotero 文库」：文档只有**单篇**入口，未提批量。
- 「1.0.6 已在 Zotero 10.0.8 实测」：文档写的是 **1.0.4** 实测；别升级成 1.0.6。
- 「插件会自动更新」：文档明确现阶段手动安装。

---

## 2. AI 助读

**可写事实**

1. 在正文里选中一句 → 右键 **「引用提问…」**（或「解释这段」），选中的原文作为**引用卡片**进入右侧「AI 助读」面板；推荐问题含「这个结论有实验支撑吗？」「解释这段」「它和上下文矛盾吗？」（`README.md` §AI 助读与自动目录；`使用说明.txt`「说明」；`docs/AI-READER-SPEC.md:11-13`）。
2. 回答里每个论断后面有可点击的 **`p.N` 出处芯片**，点一下回到对应页并闪烁高亮原文；回答末尾还有 **「依据」列表**（页码 + 章节 + 原文片段）（`README.md` §AI 助读与自动目录；`CHANGELOG.md` §v1.5.0）。
3. 页码由模型按给定材料标注，再由**本机校验并补全引用片段**，不是让模型自由编页码（`README.md` §AI 助读与自动目录；`CHANGELOG.md` §v1.5.0）。
4. 默认自动检测本机已登录的 **Codex CLI / Kimi Code CLI / Claude Code** 并直接调用，**不需要 API Key**；也可在面板「模型设置」改用任意 OpenAI 兼容接口（Base URL + 模型名 + Key），Key 用 Windows DPAPI 加密（`README.md` §AI 助读与自动目录；`docs/AI-READER-SPEC.md:98-120`）。
5. 支持**图片提问**：点击、拖拽或粘贴图片，最多 **4 张**，单张 ≤ **6 MB**、总计 ≤ **12 MB**，只接受 PNG/JPEG/WebP/GIF（`docs/AI-READER-SPEC.md:74-76`；`CHANGELOG.md` §v1.7.0）。
6. **自动目录**：左侧「目录」页签，优先读 PDF 自带书签；没有书签时按字号、加粗、编号与常见章节名自动识别标题（双栏论文按 gutter 还原阅读顺序）；点击跳页并高亮标题、滚动跟随当前章节、支持标题过滤和「重新识别」（`README.md` §AI 助读与自动目录；`CHANGELOG.md` §v1.5.0）。
7. 每次检索 **6–10 段**、材料总长 ≤ **16,000 字符**；回答约束在 **400 字内**（`docs/AI-READER-SPEC.md:138-142`）。
8. 问答会话按文档存在本机 `localStorage`，最多 **40 条**，可一键清空（`docs/AI-READER-SPEC.md:210`；`CHANGELOG.md` §v1.5.0）。

**营销可用数字/名字**

- 默认模型来源：**Codex CLI / Kimi Code CLI / Claude Code**（本机已登录即可，无需 Key）；也可切任意 OpenAI 兼容 API（`README.md` §AI 助读与自动目录）。
- 出处格式：`[pN]` → 渲染成 `p.5` 这类可点击芯片（`docs/AI-READER-SPEC.md:207`）。
- 图片上限 4 张 / 6 MB / 12 MB；会话 40 条；目录最多扫描**前 80 页**（`README.md` §已知限制第 10 条）。

**注意/限制**

- 前提是 **CLI 已安装并登录**；未安装/未登录会报错并给出修复提示（如「Codex 未登录：在终端运行 codex login」）（`README.md` §AI 助读与自动目录、§已知限制第 9 条；`docs/AI-READER-SPEC.md:96`）。
- 自动目录是**启发式**：没有样式、没有编号的标题可能漏，且**最多扫描前 80 页**，可点「重新识别」（`README.md` §已知限制第 10 条）。
- 极少数压缩或特殊排版的 PDF 只能跳到对应页、无法高亮具体行（`README.md` §已知限制第 11 条）。
- 回答限 400 字，追问才更深入（`docs/AI-READER-SPEC.md:142`）。
- 隐私口径两处不一致：README 写「约 1 万字以内」，实现契约写 ≤16,000 字符。建议统一写 **「只把检索到的相关原文片段发给所选模型，不发整篇 PDF」**（`README.md` §AI 助读与自动目录；`docs/AI-READER-SPEC.md:140`）。

**未确认**

- 「完全离线/免费」：默认走本机 CLI，但 CLI 自身是否联网、是否占用订阅额度，文档未说明；**不要写「免费」或「离线」**。
- 「目录 100% 准确」：文档明确是启发式、可能漏。
- 「能理解论文所有图表」：文档只有「上传图片提问」，没有图表自动解析的声明。

---

## 3. AI 帮写

**可写事实**

1. 笔记是**独立悬浮窗口**：不挤占论文阅读区，可拖动、八向拉伸、最小化/恢复，像 Word 一样用工具栏排版（标题、加粗、重点高亮、待办列表）（`README.md` §笔记与 AI 帮写；`CHANGELOG.md` §v1.6.0「笔记（重做）」）。
2. 工具栏 **✦ AI 帮写** 内置六种动作：**润色表达、学术化表达、精简内容、扩展内容、整理结构、纠正语病**，外加「自定义要求」；范围可在「选中文本 / 整篇笔记」间切换（`README.md` §笔记与 AI 帮写；`CHANGELOG.md` §v1.7.0「AI 帮写」）。
3. 笔记里划词后的浮动工具栏也有 **✦ AI** 入口，点开变成一行输入框，直接写「使用 AI 编辑」的要求（类似 Notion）（`CHANGELOG.md` §v1.7.0「AI 帮写」）。
4. **先建议后写入**：结果进入建议面板，可切「建议 / 对比 / 原文」看差异，**确认后才写入正文**；支持替换原文 / 插入到下方 / 重新生成 / 取消，并可一键**撤销上次 AI 修改**（`README.md` §笔记与 AI 帮写；`CHANGELOG.md` §v1.7.0「AI 帮写」）。
5. 复用 AI 助读的模型配置（CLI 优先，或 OpenAI 兼容 API）；**不会后台上传笔记**，只有点 AI 动作时才发送当前笔记文本（`README.md` §笔记与 AI 帮写；`CHANGELOG.md` §v1.7.0）。
6. 笔记可与论文互相跳转：关联到某页或选中文字，来源信息单独显示，可修改或解除关联；独立笔记也能后补关联（`README.md` §笔记与 AI 帮写；`CHANGELOG.md` §v1.7.0「笔记与原文关联」）。
7. 编辑实时自动保存，可导出 **Markdown / HTML**（`README.md` §笔记与 AI 帮写；`CHANGELOG.md` §v1.6.0）。

**营销可用数字/名字**

- 六种预设动作 + 自定义要求（`CHANGELOG.md` §v1.7.0「AI 帮写」）。
- 三种结果视图：建议 / 对比 / 原文（`CHANGELOG.md` §v1.7.0）。
- 数据路径：笔记保存在 `%APPDATA%\BabelDOC-Studio\notes.json`（`README.md` §设置与数据、§常见问题「笔记会不会被上传？」）。

**注意/限制**

- **不是一键改写全文**：AI 帮写只给建议，用户确认后才写入正文——卖点应写「可控/可撤销」（`README.md` §笔记与 AI 帮写）。
- 会把你主动选中的笔记文本或整篇笔记发给模型；「不自动上传」不等于「纯本地」（`README.md` §笔记与 AI 帮写、§常见问题）。
- 整篇改写按 Markdown 结构保留标题层级/列表/加粗；提示词禁止编造事实、数据、引用或页码，但模型仍可能出错——可写「提示词层面禁止编造」，不要保证零错误（`CHANGELOG.md` §v1.7.0）。
- 笔记不写回 Zotero（`README.md` §已知限制第 13 条）。

**未确认**

- 笔记能否插入**图片/表格**：更新日志列了标题、加粗、斜体、下划线、删除线、颜色、高亮、列表、引用、代码块、分割线、链接，**没有图片和表格**，别写。
- 「多篇笔记合并/笔记知识库检索」：文档未见。

---

## 4. 免费翻译模型

**可写事实**

1. 四个免费/低成本选项（界面预设原名）：
   - **Google 翻译（免费）**：无需 Key，应用内置免费接口（`core/providers.py:58-62`；`README.md` §免费与本地模型）。
   - **Google Gemini（免费额度）**：需要 API Key，Google AI Studio 提供免费额度，部分地区需代理（`core/providers.py:66-70`；`README.md` §免费与本地模型）。
   - **OpenRouter 免费模型**：需要 Key，**模型名以 `:free` 结尾即免费**，通常限速或排队（`core/providers.py:74-82`；`README.md` §免费与本地模型）。
   - **Ollama 本地（免费）**：无需 Key，需先安装 Ollama 并 `ollama pull` 对应模型（`core/providers.py:86-90`；`README.md` §免费与本地模型）。
2. Google 免费翻译**不经过大模型**，是应用内置翻译接口；接入时会**自动关闭术语提取与富文本翻译**（`README.md` §免费与本地模型；`CHANGELOG.md` §v1.4.0）。
3. Google 免费接口是**非官方接口**，可能 **429 限流**或区域网络不可达；失败会在日志保留具体原因（`README.md` §免费与本地模型 WARNING、§常见问题「Google 翻译报错或一直排队？」）。
4. 质量最好的一档：OpenAI / DeepSeek / GLM / Qwen / Kimi，按服务商计费（`README.md` §免费与本地模型）。
5. 内置 DeepSeek 模型：**`deepseek-flash`（V4.1 Flash）** 与 **`deepseek-v4-pro`**；旧 `deepseek-chat` / `deepseek-reasoner` 仅保留费用估算兼容（`CHANGELOG.md` §v1.8.1「翻译工作区」）。
6. 费用可见：任务结束显示输入/输出 token 与按可配置单价估算的费用（`README.md` §翻译与版式「费用可见」）。
7. 术语统一：内置「AI / 大模型」与「交互设计」两套预设术语库，也可导入 CSV，支持翻译前自动提取术语（`README.md` §翻译与版式；`使用说明.txt`「说明」）。
8. 默认语言：源语言英文 `en` → 目标语言中文 `zh`（`使用说明.txt`「说明」）。

**营销可用数字/名字**

- `:free` 后缀 = OpenRouter 免费模型的判定规则（`README.md` §免费与本地模型）。
- Google 免费翻译在设置里显示为「Google 翻译（免费）」，Ollama 显示为「Ollama 本地（免费）」（`core/providers.py:59,87`）。
- 内置术语库两套：人工智能 · 大模型 / 交互设计 · 人机交互（`使用说明.txt`「说明」）。

**注意/限制**

- **「免费」≠「无限」**：Google 是非官方免费接口，限流、失效和区域网络问题不受项目控制；OpenRouter `:free` 会限速排队；Ollama 吃本机算力（`README.md` §免费与本地模型 WARNING、§已知限制第 3 条）。
- Google 免费翻译对复杂公式、占位符、长难句的效果不如 LLM；重要文档建议付费模型或配合术语库（`README.md` §免费与本地模型）。
- 桌面端首次翻译可能仍需下载模型/字体，耗时与网速有关（`README.md` §翻译与版式 TIP）。

**未确认**

- 各免费额度的具体数字（token 数、次数、速率）：文档未给，别编。
- 「Gemini 免费额度永久有效」：文档只说 AI Studio 提供免费额度。
- 「Google 免费翻译无限次」：与文档冲突，明确不要写。

---

## 5. 重做 UI（Apple HIG 风格）

**可写事实**

1. **v1.4.0 起**界面整体切到 **Apple HIG 设计语言**；首页/结果库按 HIG 重做：**34px 大标题、inset-grouped 分组卡片、44px 行高**、系统开关与分段控件、半透明毛玻璃导航栏；浅色 / 深色 / 900px 窄窗口都有适配（`CHANGELOG.md` §v1.4.0「界面（重制）」）。
2. 阅读器顶栏、侧栏、工具坞、浮层统一为同一套材质与排版；底部工具坞换成更接近 **SF Symbols** 的手绘线性图标，带按压与选中反馈（`CHANGELOG.md` §v1.4.0、§v1.3.0「阅读器修复」）。
3. 阅读器顶栏是固定悬浮的**半透明玻璃条**、文档标题居中；窄窗口自动收起标题，页面从玻璃下方穿过（`CHANGELOG.md` §v1.4.0）。
4. 阅读与批注：**八色高亮**（黄/绿/蓝/粉/橙/紫/青/红）+ **六种样式**（荧光笔、蜡笔、手绘下划线、实线划掉、铅笔划掉、波浪线）；便签、页面文字、页边距批注、`Ctrl+Z` 撤销、反色阅读、水墨屏纸面（`README.md` §阅读与批注）。
5. **v1.8.1 继续打磨**：页边距批注左右分栏 + 圆角正交引线、颜色标签可增删/拖拽排序、划词工具条「＋」新建重点色、手绘下划线三档笔触、反色阅读（`CHANGELOG.md` §v1.8.1「阅读器」）。
6. 尊重系统「减少动态效果」；深色系统下也能切回浅色主题（`CHANGELOG.md` §v1.3.0、§v1.8.1「翻译工作区」）。
7. 翻译完成弹出毛玻璃提示；首页/结果库/阅读器截图在 `docs/screenshots/`（`CHANGELOG.md` §v1.8.1；`README.md` §界面预览）。

**营销可用数字/名字**

- 关键尺寸：**34px 大标题、44px 行高、900px 窄窗口断点**（`CHANGELOG.md` §v1.4.0）。
- 批注规格：**8 色 × 6 种样式**；手绘下划线 **3 档笔触**（轻微 / 自然 / 明显）（`README.md` §阅读与批注；`CHANGELOG.md` §v1.8.1）。
- 图标风格：接近 SF Symbols 的手绘线性图标（`CHANGELOG.md` §v1.4.0）。

**注意/限制**

- 这是「**Apple HIG 风格 / 苹果风格设计语言**」，**不是 Apple 官方产品、没有 Apple 认证**（`CHANGELOG.md` §v1.4.0 末尾；`README.md` 开头）。
- 演示截图用公开论文 *Attention Is All You Need*（arXiv:1706.03762）；译文、批注和 Zotero 文库是演示数据（`README.md` §界面预览）。
- UI 重做是 **v1.4.0** 的事，1.8.1 是延续优化；写「v1.8.1 重做 UI」不准确，建议写「v1.4.0 起 Apple HIG 重做，1.8.1 继续打磨」。
- 界面由 **Edge / Chrome 应用窗口**承载，不是网页版（`README.md` 开头、§下载 Windows 免安装版）。

**未确认**

- 具体字体名（是否用 SF Pro 或内置字体）：文档只提「接近 SF Symbols 的手绘线性图标」，别写「使用 SF 字体」。
- 是否有 iPad 版 / 移动端：无。

---

## 6. 一键解压缩使用（便携 ZIP）

**可写事实**

1. 下载 **`BabelDOC-Studio-Windows-x64.zip`**（Releases 页），**不要下 GitHub 自动生成的 Source code ZIP**（`README.md` §「下载 Windows 免安装版」）。
2. 包内已含 **Python 运行时、BabelDOC、依赖、离线模型与字体**，解压即用，不需要自己装 Python（`README.md` 开头功能列表、§快速开始；ZIP 内实测有 `offline-assets/`、`runtime/Lib/site-packages/babeldoc-0.6.4`）。
3. 启动：双击 **`Start.bat`**；`BabelDOC Studio.exe` 是给代码签名预留的启动器，未签名版优先用 `Start.bat`（`README.md` §「下载 Windows 免安装版」）。
4. Windows 11 建议先「右键 ZIP → 属性 → 勾选解除锁定」再解压；`Start.bat` / `BabelDOC Studio.exe` 首次运行会**自动清掉整个目录的「来自 Internet」标记**并写 `.babeldoc-unblocked`（`README.md` §「下载 Windows 免安装版」、§「解压与智能应用控制」）。
5. **免安装、程序与数据分离**：设置/术语库/批注/笔记/译文在 `%APPDATA%\BabelDOC-Studio`；升级解压到新目录不会丢数据（`README.md` §「下载 Windows 免安装版」、§设置与数据）。
6. 核对时 `dist/BabelDOC-Studio-Windows-x64.zip` 实测：**454,695,116 字节（约 434 MiB）**、**14,243 个条目**、构建时间 **2026-11-10 19:14**；含 `Start.bat`、`BabelDOC Studio.exe`、`runtime/pythonw.exe`、`offline-assets/*.zip`、`web/viewer.html`（本仓库产物实测；重新构建后数字会变）。
7. 默认输出目录 `文档\BabelDOC-Studio`，产物自动命名 **`原文件名_译文.pdf`** 与 **`原文件名_双语对照.pdf`**，同一篇论文收进同名子文件夹（`使用说明.txt`「说明」；`README.md` §设置与数据）。
8. 只支持 **Windows 10/11 x64**；源码运行需 Python 3.10+，可 `python app.py --server-only` 后访问 `http://127.0.0.1:8765`（`README.md` §从源码运行）。

**营销可用数字/名字**

- ZIP 名、启动脚本名、数据目录名（见上）。
- 默认端口 `8765`（`app.py` 启动逻辑）。
- 包内 Python 运行时：`runtime\pythonw.exe`（ZIP 实测；`CHANGELOG.md` §v1.5.0「安装包与 Windows 兼容」）。

**注意/限制**

- **当前包未做代码签名**：会遇 SmartScreen「未知发布者」（点「更多信息 → 仍要运行」）；Win11 **智能应用控制（SAC）** 会拦 `Start.bat` / `pythonw.exe` / `*.pyd`（`README.md` §「下载 Windows 免安装版」NOTE、§已知限制第 12 条）。
  - 包内 `SIGNING-STATUS.txt`（本仓库 dist 版，生成于 2026-11-08）：**391 个 exe/dll/pyd 中 376 个未签名、15 个有效签名**（核对时产物实测，不同构建数字会变）。
- SAC **没有白名单**，只能关闭 SAC 或等签名版；关闭会降低系统防护，部分旧版 Windows 关后需重装系统才能再开（`README.md` §「解压与智能应用控制」）。
- 需要解压到**有写入权限**的目录（`README.md` §「下载 Windows 免安装版」）。
- 首次翻译可能仍需下载版面分析模型/字体（`README.md` §翻译与版式 TIP）；但包内带 `offline-assets`，源码 `tools/babeldoc_cli.py:6-9` 会调用 `restore_offline_assets_package` 还原。**便携包是否 100% 离线未确认**，建议写「内置离线资源」而不是「全程无需联网」。
- 升级：关闭旧程序后解压新版本（1.8.1 文档口径：解压到新目录；数据在 `%APPDATA%` 所以不会丢）。仓库正在加 v1.9.0 的「应用内检查更新」，其中描述可**覆盖**原程序目录，属未发布内容，等发布后再写。
- 卸载：删程序目录；要清个人数据需另删 `%APPDATA%\BabelDOC-Studio` 和「文档」下的 `BabelDOC-Studio`（`README.md` §常见问题「怎么更新或卸载？」）。

**未确认**

- README 说解压目录附带 `启动失败看这里.txt`（`README.md` §「下载 Windows 免安装版」附近），但 1.8.1 ZIP 的 14,243 个条目里**没有这个文件**（只在仓库根目录/源码构建目录存在）——别写「包里附带排错说明」。
- 是否弹防火墙/端口授权提示：文档未说。
- 无 Edge/Chrome 的机器上的行为：代码是 Edge → Chrome → 默认浏览器逐级回退（`app.py` 的 `_open_window()`），文档未承诺。
- **项目许可证 / 是否可商用**：仓库根目录**没有项目级 LICENSE**，README 未提许可证——**不要写「开源协议 XX」或「可商用」**。

---

## 7. 建议避开的表述（高风险）

| 不要写 | 为什么 |
| --- | --- |
| Zotero 双向同步 / 笔记回写 Zotero | 文档明确是**单向只读**（`README.md` §Zotero 集成、§已知限制第 13 条） |
| 逐句 / 逐词对齐 | 双语同步按**版面位置估算**，交替页模式不做同步（`README.md` §阅读与批注、§已知限制第 5 条） |
| 免费无限翻译 | Google 是**非官方接口**，会 429 限流；`:free` 也会排队（`README.md` §免费与本地模型 WARNING） |
| 双击 ZIP 即用、零拦截 | 需解压 + 解除锁定；未签名会被 SmartScreen / SAC 拦（`README.md` §快速开始） |
| 支持 macOS / Linux | 只发 Windows 10/11 x64（`README.md` §常见问题） |
| 插件 1.0.6 已在 Zotero 10.0.8 实测 | 实测的是 **1.0.4**；1.0.6 只写了「沿用同一标识 + 通过插件测试」（`docs/ZOTERO-INTEGRATION.md:43-44`） |
| 扫描版 PDF 全能翻 | 完整 OCR 流程仍在路线图（未勾选）（`README.md` §路线图、§已知限制第 4 条） |
| 100% 保留原排版 / 绝不丢公式 | 文档口径是「**尽量**维持原位置」（`README.md` §翻译与版式） |
| AI 帮写直接改正文 / 一键重写全文 | 实际是**先建议、确认后写入**（`README.md` §笔记与 AI 帮写） |
| 官方 Google API / 与 Google 合作 | 用的是**非官方免费接口**（`README.md` §免费与本地模型 WARNING；`app.py` 的 Google 网页翻译请求 `client=dict-chrome-ex`） |
| v1.8.1 重做 UI | 重做发生在 **v1.4.0**，1.8.1 是继续打磨（`CHANGELOG.md` §v1.4.0） |
| 开源项目 / 可商用 | 根目录无 LICENSE，许可证**未确认** |
| 完全离线、无需联网 | 首次可能下载模型/字体；AI 助读走本机 CLI 或在线 API（`README.md` §翻译与版式 TIP、§AI 助读与自动目录） |
| v1.9.0 已发布 / 有应用内更新 | 仓库正在合并，`app.py` 仍 1.8.1，**未确认** |

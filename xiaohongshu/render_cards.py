# -*- coding: utf-8 -*-
"""Render 1242x1656 (3:4) Xiaohongshu cards for ReadPI with Pillow."""
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1242, 1656
ROOT = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(ROOT)
SHOT = os.path.join(PROJ, "docs", "screenshots")
OUT = os.path.join(ROOT, "cards")
os.makedirs(OUT, exist_ok=True)

FD = r"C:\Windows\Fonts"
FBOLD = os.path.join(FD, "HarmonyOS_Sans_SC_Bold.ttf")
FREG = os.path.join(FD, "HarmonyOS_Sans_SC_Regular.ttf")

INK = (17, 17, 19)
SUB = (92, 92, 98)
MUTE = (166, 166, 174)
ACCENT = (255, 46, 85)
WHITE = (255, 255, 255)

_cache = {}
def font(size, bold=False):
    k = (size, bold)
    if k not in _cache:
        _cache[k] = ImageFont.truetype(FBOLD if bold else FREG, size)
    return _cache[k]

# ---------------- primitives ----------------
def paste_shadow(base, img, xy, radius=26, blur=34, off=(0, 14), alpha=44):
    sh = Image.new("RGBA", (img.width + blur * 4, img.height + blur * 4), (0, 0, 0, 0))
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.width - 1, img.height - 1],
                                           radius=radius, fill=alpha)
    sh.paste(Image.new("RGBA", img.size, (28, 24, 38, 255)), (blur * 2, blur * 2), mask)
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(sh, (xy[0] - blur * 2 + off[0], xy[1] - blur * 2 + off[1]))
    base.alpha_composite(img, xy)

def rounded_image(path, radius, target_w, crop_h=None, radius_btm=None, crop_box=None):
    im = Image.open(path).convert("RGB")
    if crop_box:
        im = im.crop(crop_box)
    s = target_w / im.width
    im = im.resize((target_w, int(round(im.height * s))), Image.LANCZOS)
    if crop_h:
        im = im.crop((0, 0, im.width, min(crop_h, im.height)))
    w, h = im.size
    r2 = radius if radius_btm is None else radius_btm
    im = im.convert("RGBA")
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    if r2 != radius:
        d.rectangle([0, h - r2 - 2, w - 1, h - 1], fill=255)
    im.putalpha(mask)
    return im

def bg():
    im = Image.new("RGBA", (W, H), (250, 250, 252, 255))
    for box, col, a in [((-280, -320, 660, 540), (255, 86, 116), 22),
                        ((W - 280, 60, W + 420, 720), (116, 148, 255), 12),
                        ((140, H - 460, 1000, H + 220), (255, 132, 156), 11)]:
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(lay).ellipse(box, fill=col + (a,))
        im.alpha_composite(lay.filter(ImageFilter.GaussianBlur(130)))
    ImageDraw.Draw(im).rectangle([0, 0, W, 3], fill=(0, 0, 0, 8))
    return im

def tokens(text):
    out, buf = [], ""
    for ch in text:
        if ch == "\n":
            if buf: out.append(buf); buf = ""
            out.append("\n")
        elif ord(ch) < 128 and not ch.isspace():
            buf += ch
        elif ch == " ":
            if buf: out.append(buf); buf = ""
            out.append(" ")
        else:
            if buf: out.append(buf); buf = ""
            out.append(ch)
    if buf: out.append(buf)
    return out

PUNCT = "，。、；：」』）】？！%…·,.;:!?)]}"

def wrap(d, text, fnt, max_w):
    lines, cur = [], ""
    for tk in tokens(text):
        if tk == "\n":
            lines.append(cur); cur = ""; continue
        trial = cur + tk
        if d.textlength(trial, font=fnt) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur.rstrip())
            cur = "" if tk == " " else tk
    if cur: lines.append(cur.rstrip())
    # CJK orphan control: never leave a line that is only punctuation
    i = 1
    while i < len(lines):
        if lines[i] and all(c in PUNCT for c in lines[i]) and len(lines[i]) <= 2:
            lines[i - 1] = lines[i - 1] + lines[i]
            del lines[i]
        else:
            i += 1
    return lines

def draw_lines(base, lines, xy, fnt, color, lh=1.2):
    d, x, y = ImageDraw.Draw(base), xy[0], xy[1]
    for ln in lines:
        d.text((x, y), ln, font=fnt, fill=color)
        y += int(fnt.size * lh)
    return y

def chip(base, xy, text, fg, bgc, size=30, padx=26, pady=10, bold=True):
    d = ImageDraw.Draw(base)
    f = font(size, bold)
    w = int(d.textlength(text, font=f) + padx * 2)
    h = int(size * 1.66)
    d.rounded_rectangle([xy[0], xy[1], xy[0] + w, xy[1] + h], radius=h // 2, fill=bgc)
    d.text((xy[0] + padx, xy[1] + (h - size * 1.24) / 2 - 1), text, font=f, fill=fg)
    return (xy[0] + w, xy[1] + h)

def logo(base, xy, size=68, radius=20):
    try:
        ic = Image.open(os.path.join(PROJ, "web", "babeldoc-icon.png")).convert("RGBA")
        ic = ic.resize((size, size), Image.LANCZOS)
        m = Image.new("L", (size, size), 0)
        ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
        ic.putalpha(m)
        base.alpha_composite(ic, xy)
    except Exception:
        ImageDraw.Draw(base).rounded_rectangle(
            [xy[0], xy[1], xy[0] + size, xy[1] + size], radius=radius, fill=ACCENT)

def bullets(base, xy, items, size=34, gap=32, max_w=1066):
    d = ImageDraw.Draw(base)
    f = font(size)
    x, y = xy
    for it in items:
        d.ellipse([x, y + int(size * 0.40), x + 12, y + int(size * 0.40) + 12], fill=ACCENT)
        for ln in wrap(d, it, f, max_w - 46):
            d.text((x + 46, y), ln, font=f, fill=(58, 58, 63))
            y += int(size * 1.5)
        y += gap - int(size * 0.5)
    return y

def screenshot(base, w, path, min_top, crop_h=None, x=None, radius=26, bleed=64, r_top=None,
               crop_box=None):
    img = rounded_image(os.path.join(SHOT, path), radius, w, crop_h=crop_h,
                        radius_btm=None if r_top is None else r_top, crop_box=crop_box)
    h = img.height
    avail = H - min_top
    if h < avail * 0.72:
        # short capture: float it, centred in the remaining space
        y = min_top + (avail - h) // 2
    else:
        y = max(min_top, H - h + bleed)
    y = min(y, H - 280)
    if y + h > H:
        img = img.crop((0, 0, img.width, H - y))
        m = Image.new("L", img.size, 0)
        ImageDraw.Draw(m).rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=radius, fill=255)
        img.putalpha(m)
    ImageDraw.Draw(img).rounded_rectangle([0, 0, img.width - 1, img.height - 1],
                                          radius=radius, outline=(0, 0, 0, 24), width=2)
    px = x if x is not None else M
    paste_shadow(base, img, (px, y), radius=radius)
    return img.height + y

# ---------------- layout ----------------
M = 88

def header(card, page, total=9):
    logo(card, (M, 96), 62, 18)
    d = ImageDraw.Draw(card)
    d.text((M + 82, 102), "ReadPI", font=font(38, True), fill=INK)
    d.text((M + 82, 150), "本地论文翻译阅读器", font=font(23), fill=MUTE)
    lb = f"{page:02d} / {total:02d}"
    d.text((W - M - d.textlength(lb, font=font(25, True)), 118), lb, font=font(25, True), fill=(203, 203, 210))

def kicker(base, xy, num, label):
    d = ImageDraw.Draw(base)
    x, y = xy
    if num:
        d.rounded_rectangle([x, y, x + 64, y + 64], radius=18, fill=ACCENT)
        tw = d.textlength(num, font=font(34, True))
        d.text((x + (64 - tw) / 2, y + 10), num, font=font(34, True), fill=WHITE)
        x += 84
    d.text((x, y + 9), label, font=font(36, True), fill=ACCENT)

def feature(page, num, kicker_label, headline, sub, items, shot, shot_crop=None,
            note=None, total=9, shot_box=None):
    card = bg()
    header(card, page, total)
    d = ImageDraw.Draw(card)
    y = 262
    kicker(card, (M, y), num, kicker_label)
    y += 116

    fh = font(94, True)
    y = draw_lines(card, wrap(d, headline, fh, W - M * 2), (M, y), fh, INK, lh=1.24) + 20

    fs = font(35)
    y = draw_lines(card, wrap(d, sub, fs, W - M * 2 - 6), (M, y), fs, SUB, lh=1.62) + 34

    y = bullets(card, (M, y + 6), items)

    if note:
        fn = font(27)
        nl = wrap(d, note, fn, W - M * 2 - 62)
        hh = int(len(nl) * 27 * 1.62 + 32)
        d.rounded_rectangle([M, y + 18, W - M, y + 18 + hh], radius=18, fill=(255, 238, 243))
        yy = y + 34
        for ln in nl:
            d.text((M + 31, yy), ln, font=fn, fill=(188, 38, 70))
            yy += int(27 * 1.62)
        y += hh + 36

    screenshot(card, W - M * 2, shot, min_top=y + 54, crop_h=shot_crop, crop_box=shot_box)
    card.convert("RGB").save(os.path.join(OUT, f"card-{page:02d}.png"), quality=95)


def cover():
    card = bg()
    d = ImageDraw.Draw(card)
    logo(card, (M, 92), 80, 22)
    d.text((M + 100, 96), "ReadPI", font=font(46, True), fill=INK)
    d.text((M + 100, 152), "PDF 论文翻译 · 保留原始排版", font=font(24), fill=MUTE)

    b = "v1.8.1 · Windows"
    tw = d.textlength(b, font=font(26, True))
    d.rounded_rectangle([W - M - tw - 48, 106, W - M, 162], radius=28, fill=(255, 255, 255, 242))
    d.text((W - M - tw - 24, 118), b, font=font(26, True), fill=(88, 88, 94))

    y = 306
    chip(card, (M, y), "ZOTERO 一键联动", WHITE, ACCENT, size=32, padx=30)
    y += 112

    fh = font(110, True)
    d.text((M, y), "把 Zotero 里的论文", font=fh, fill=INK); y += int(110 * 1.2)
    d.text((M, y), "一键变中英对照", font=fh, fill=ACCENT); y += int(110 * 1.22)

    y += 20
    fs = font(37)
    for ln in ["公式、图表、双栏排版照旧不动，", "译文、笔记、批注在同一个窗口。"]:
        d.text((M, y), ln, font=fs, fill=SUB); y += int(37 * 1.68)

    y += 22
    x = M
    for t in ["免安装", "本地运行", "免费模型"]:
        x = chip(card, (x, y), t, (70, 70, 76), (255, 255, 255, 236), size=28, padx=26)[0] + 14

    # flow line closes the gap before the hero screenshot
    y += 96
    fx = M
    ff = font(27, True)
    for i, seg in enumerate(["Zotero 文库", "一键翻译", "中英对照", "边读边问"]):
        tw = d.textlength(seg, font=ff)
        d.rounded_rectangle([fx, y - 8, fx + tw + 34, y + 42], radius=25, fill=(255, 255, 255, 210))
        d.text((fx + 17, y - 1), seg, font=ff, fill=(70, 70, 76))
        fx += tw + 34
        if i < 3:
            ar = "→"
            aw = d.textlength(ar, font=font(28, True))
            d.text((fx + 12, y - 2), ar, font=font(28, True), fill=ACCENT)
            fx += 24 + aw + 12

    screenshot(card, W, "reader-dual.png", min_top=1042, x=0, radius=30, bleed=0, r_top=0)
    card.convert("RGB").save(os.path.join(OUT, "card-01.png"), quality=95)


def closing():
    card = bg()
    header(card, 9)
    d = ImageDraw.Draw(card)
    y = 300
    d.text((M, y), "现在就试试", font=font(110, True), fill=INK); y += 158
    d.text((M, y), "Windows 10 / 11 x64 · 免安装 · 只在本机跑", font=font(33), fill=SUB); y += 78

    d.rounded_rectangle([M, y, W - M, y + 322], radius=30, fill=(255, 255, 255, 246))
    d.rounded_rectangle([M, y, W - M, y + 322], radius=30, outline=(0, 0, 0, 18), width=2)
    d.text((M + 46, y + 42), "GitHub · Releases", font=font(26, True), fill=MUTE)
    d.text((M + 46, y + 84), "github.com/PiDesign-314/ReadPI", font=font(38, True), fill=INK)
    d.line([M + 46, y + 158, W - M - 46, y + 158], fill=(0, 0, 0, 22), width=2)
    d.text((M + 46, y + 184), "① 下载 BabelDOC-Studio-Windows-x64.zip", font=font(29), fill=(58, 58, 63))
    d.text((M + 46, y + 238), "② 解压到有写权限的目录 → 双击 Start.bat", font=font(29), fill=(58, 58, 63))
    y += 372

    for txt, col, bgc in [
        ("别下 Source code ZIP，那是源码不是程序", (190, 40, 70), (255, 243, 246)),
        ("Win11 拦截时：右键 ZIP → 属性 → 解除锁定，再解压", (86, 86, 92), (246, 246, 249)),
    ]:
        d.rounded_rectangle([M, y, W - M, y + 82], radius=20, fill=bgc)
        d.text((M + 30, y + 24), txt, font=font(28), fill=col)
        y += 98

    y += 40
    d.rounded_rectangle([M, y, W - M, y + 262], radius=30, fill=ACCENT)
    d.text((M + 44, y + 46), "翻译、阅读、提问、记笔记，", font=font(46, True), fill=WHITE)
    d.text((M + 44, y + 112), "本来就是一件事。", font=font(46, True), fill=WHITE)
    d.text((M + 44, y + 190), "ReadPI 把它们放回了同一个窗口。", font=font(28), fill=(255, 238, 242))
    y += 306

    logo(card, (M, y), 74, 20)
    d.text((M + 96, y + 4), "ReadPI", font=font(42, True), fill=INK)
    d.text((M + 98, y + 56), "v1.8.1 · Windows 10 / 11 x64", font=font(24), fill=MUTE)
    card.convert("RGB").save(os.path.join(OUT, "card-09.png"), quality=95)


if __name__ == "__main__":
    cover()

    feature(2, "01", "ZOTERO 联动", "Zotero 里右键，\n直接开读",
            "文献列表右键「在 ReadPI 中阅读」，PDF 自动接进阅读器，还接着你上次读到的那一页。",
            ["文献列表 / PDF 阅读器按钮 / 页面右键，三处入口",
             "只复制一份副本，Zotero 原件一个字不动",
             "只对有本地 PDF 附件的文献显示，不会误触",
             "应用没开着，也会自动帮你拉起来"],
            "zotero-library-light.png", shot_box=(130, 0, 1330, 452))

    feature(3, "01", "ZOTERO 联动", "打开第二次，\n成果还在",
            "同一个附件只认一条记录：重复打开，都回到你上次停下的地方。",
            ["译文、双语版、笔记、批注、阅读位置全保留",
             "从阅读器进来定位当前页，从列表进来接着读",
             "「阅读」下拉可切原文 / 仅译文 / 左右对照",
             "结果库直读 Zotero 文库和嵌套文件夹"],
            "reader-margin.png", shot_crop=700)

    feature(4, "02", "AI 助读", "读不懂那句，\n就选中问它",
            "选中原文右键「引用提问…」，这句话作为引用卡片带进右侧面板，直接问。",
            ["回答里每个论断都带 p.N 出处，点一下跳回原文",
             "文末还有「依据」列表：页码 + 章节 + 原文片段",
             "默认调用本机已登录 Codex / Kimi / Claude CLI",
             "不用填 API Key，提问只发送检索到的片段"],
            "reader-ai.png")

    feature(5, "03", "AI 帮写", "笔记写完，\n让它帮你改",
            "划词、AI 回答、随手新建都能存成笔记，悬浮窗不挤占阅读区。",
            ["润色 / 学术化 / 精简 / 扩展 / 理结构 / 纠语病",
             "先给「建议 · 对比 · 原文」，确认后才写进正文",
             "写入后可一键撤销上次 AI 修改",
             "不点 AI 动作就不上传，笔记只存本机"],
            "reader-notes-ai.png", shot_crop=760)

    feature(6, "04", "免费翻译模型", "一分钱不花，\n也能先翻一遍",
            "不想先充钱？三条免费路线，装上就能看排版。",
            ["Google 翻译：内置免费接口，无需 Key",
             "Ollama：本机跑，完全免费，断网也能用",
             "OpenRouter：:free 结尾的模型同样免费",
             "想认真读再换 DeepSeek / GLM / Gemini / Kimi"],
            "work-inline.png", shot_crop=560,
            note="免费接口是非官方渠道，可能限流；公式与长难句的效果不如付费大模型。")

    feature(7, "05", "界面重做", "苹果风界面，\n重心回到论文",
            "按 Apple HIG 重做设置、结果库和阅读工具坞，参数收进「更多」，不再堆在首屏。",
            ["深色 / 浅色跟随系统，Win 深色下也能切回",
             "八色高亮 + 六种标记样式 + 页边距批注",
             "手绘下划线、便签、页面文字就地输入",
             "批注支持 Ctrl+Z 撤销"],
            "library.png", shot_crop=470)

    feature(8, "06", "解压即用", "解压就能用，\n不用配环境",
            "免安装 ZIP 里已内置 Python、BabelDOC、离线模型和字体，双击 Start.bat 即可。",
            ["不用装 Python，不用 pip，不用敲命令",
             "首次启动自动清掉「来自 Internet」标记",
             "API Key 用 Windows DPAPI 加密保存",
             "PDF、批注、笔记都不出本机"],
            "home-light.png", shot_crop=760)

    closing()
    print("done:", sorted(os.listdir(OUT)))

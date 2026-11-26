# -*- coding: utf-8 -*-
"""Export the ReadPI × Zotero story cards from real project screenshots."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import pymupdf

ROOT = Path(__file__).resolve().parent
SHOTS = ROOT.parent / "docs" / "screenshots"
OUT = ROOT / "readpi-zotero"
OUT.mkdir(exist_ok=True)
BRAND = ROOT / "brand-original"
W, H = 1080, 1440
BG = "#f7f7f4"
INK = "#1c2220"
MUTED = "#52605a"
LIME = "#d6f266"
FONT = Path("C:/Windows/Fonts/HarmonyOS_Sans_SC_Bold.ttf")
REG = Path("C:/Windows/Fonts/HarmonyOS_Sans_SC_Regular.ttf")

def f(size, bold=False):
    return ImageFont.truetype(str(FONT if bold else REG), size)

def svg_image(name, width):
    """Rasterize the unchanged source SVG only for the PNG export."""
    data = (BRAND / name).read_bytes()
    doc = pymupdf.open(stream=data, filetype="svg")
    scale = width / doc[0].rect.width
    pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=True)
    return Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)

MARK = svg_image("主体.svg", 68)
WORDMARK = svg_image("PI DESIGN.svg", 178)

def signature(im, cover=False, dark=False):
    d = ImageDraw.Draw(im)
    if cover:
        d.rounded_rectangle((742, 1332, 1022, 1405), radius=16, fill="white")
        im.paste(MARK, (754, 1340), MARK)
        im.paste(WORDMARK, (829, 1357), WORDMARK)
    else:
        if dark:
            d.rounded_rectangle((820, 1350, 1022, 1399), radius=12, fill="white")
        im.paste(WORDMARK, (835, 1360), WORDMARK)

def base(n, dark=False):
    im = Image.new("RGB", (W, H), INK if dark else BG)
    d = ImageDraw.Draw(im)
    d.text((58, 44), "READPI  ·  论文翻译与阅读", font=f(25, True), fill=LIME if dark else MUTED)
    d.text((987, 44), f"{n:02d}/05", font=f(24), fill="#a5b0a9" if dark else MUTED, anchor="ra")
    return im, d

def headline(d, lines, dark=False, y=132):
    for i, line in enumerate(lines):
        d.text((58, y + i*100), line, font=f(78, True), fill="white" if dark else INK)

def shot(im, name, crop, box, label=None):
    src = Image.open(SHOTS / name).convert("RGB").crop(crop)
    x0,y0,x1,y1=box
    tw,th=x1-x0,y1-y0
    scale=max(tw/src.width, th/src.height)
    src=src.resize((round(src.width*scale),round(src.height*scale)), Image.Resampling.LANCZOS)
    sx=(src.width-tw)//2; sy=(src.height-th)//2
    src=src.crop((sx,sy,sx+tw,sy+th))
    mask=Image.new("L",(tw,th),0)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,tw-1,th-1),radius=24,fill=255)
    im.paste(src,(x0,y0),mask)
    ImageDraw.Draw(im).rounded_rectangle(box,radius=24,outline="#d0d6d0",width=2)
    if label:
        d=ImageDraw.Draw(im)
        d.rounded_rectangle((x0+20,y0+20,x0+20+len(label)*28+38,y0+78),radius=16,fill=INK)
        d.text((x0+39,y0+32),label,font=f(28,True),fill="white")

def footer(d, text, dark=False):
    d.text((58, 1370), text, font=f(29), fill="#c9d1ca" if dark else MUTED)

cards=[]

im,d=base(1,True)
d.rounded_rectangle((58,126,422,178),radius=16,fill=LIME)
d.text((78,135),"ReadPI × Zotero",font=f(30,True),fill=INK)
for j,line in enumerate(["超好用的论文翻译工具", "还能连接 Zotero 文献库"]):
    d.text((58, 232+j*99), line, font=f(68, True), fill="white")
d.text((60,473),"从 Zotero 打开，翻译、阅读、记笔记。",font=f(35),fill="#d8e0d9")
shot(im,"reader-dual.png",(195,55,1575,899),(58,575,1022,1290),"真实阅读界面")
footer(d,"一篇论文的实际打开过程",True)
signature(im,cover=True)
cards.append(im)

im,d=base(2)
headline(d,["Zotero 里右键打开"])
d.text((60,273),"菜单名：在 ReadPI 中阅读",font=f(40,True),fill=INK)
d.rounded_rectangle((58,352,1022,447),radius=24,fill=LIME)
d.text((83,374),"前提：这篇文献有已下载的本地 PDF",font=f(35),fill=INK)
shot(im,"zotero-library-light.png",(195,60,1290,890),(58,500,1022,1240),"打开后 · ReadPI 结果库")
footer(d,"首次打开会接入 PDF 副本；Zotero 原件不改。")
signature(im)
cards.append(im)

im,d=base(3)
headline(d,["完成翻译，左右对照读"])
d.text((60,273),"左边原文，右边译文；同一页对着读。",font=f(37),fill=MUTED)
shot(im,"reader-dual.png",(285,80,1500,780),(58,360,1022,1115))
d.rounded_rectangle((58,1165,1022,1255),radius=22,fill=LIME)
d.text((84,1188),"需要翻译时，用已保存的设置开始单篇任务。",font=f(31),fill=INK)
signature(im)
cards.append(im)

im,d=base(4)
headline(d,["边读边记，笔记连原文"])
d.text((60,273),"笔记可以关联原文页，回看时找得到出处。",font=f(36),fill=MUTED)
shot(im,"reader-notes.png",(875,70,1565,660),(58,360,1022,1225),"笔记窗口 · 来源：第 2 页")
footer(d,"图中为演示论文与演示笔记。")
signature(im)
cards.append(im)

im,d=base(5,True)
headline(d,["再次打开，进度还在"],True)
d.text((60,273),"译文、笔记、批注和阅读位置都保留。",font=f(38),fill="#d8e0d9")
shot(im,"zotero-library-light.png",(400,65,1280,545),(58,390,1022,960),"同一篇 · 再点阅读")
d.rounded_rectangle((58,1020,1022,1215),radius=28,fill=LIME)
d.text((88,1050),"我做 ReadPI，最想省掉的就是",font=f(39,True),fill=INK)
d.text((88,1112),"每次重新找论文、译文和笔记。",font=f(39,True),fill=INK)
footer(d,"Windows 10/11 x64 · Zotero 7–10",True)
signature(im,dark=True)
cards.append(im)

for i, im in enumerate(cards, 1):
    im.save(OUT / f"{i:02d}.png", optimize=True)

thumb=300; gap=14
preview=Image.new("RGB",(thumb*5+gap*6,round(thumb*4/3)+gap*2),"#dfe3de")
for i,im in enumerate(cards):
    preview.paste(im.resize((thumb,round(thumb*4/3)),Image.Resampling.LANCZOS),(gap+(thumb+gap)*i,gap))
preview.save(OUT / "预览.png", optimize=True)
print(OUT)

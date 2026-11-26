# -*- coding: utf-8 -*-
"""Build a 3x3 contact sheet of the nine cards."""
import os
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
CARDS = os.path.join(ROOT, "cards")
w, gap, mg = 396, 18, 30
cols, rows = 3, 3
cw = mg * 2 + cols * w + (cols - 1) * gap
ch = mg * 2 + rows * int(w * 1656 / 1242) + (rows - 1) * gap
sheet = Image.new("RGB", (cw, ch), (240, 240, 243))
th = int(w * 1656 / 1242)
for i in range(9):
    p = os.path.join(CARDS, f"card-{i+1:02d}.png")
    im = Image.open(p).convert("RGB").resize((w, th), Image.LANCZOS)
    x = mg + (i % cols) * (w + gap)
    y = mg + (i // cols) * (th + gap)
    sheet.paste(im, (x, y))
sheet.save(os.path.join(ROOT, "九宫格预览.png"), quality=92)
print("sheet:", sheet.size)

# -*- coding: utf-8 -*-
"""由 assets/icon-source.png 生成透明背景的多尺寸 ico 与 png。

源图圆角方形之外是白色（无 alpha），先从四角 flood fill 精确识别外部白色
（内部雪茄烟灰被深色隔开、不受影响），转为透明并柔化边缘，再生成各尺寸。
"""
import os
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "assets", "icon-source.png")
MARK = (255, 0, 255)

src = Image.open(SRC).convert("RGB")
w, h = src.size

# 1. flood fill 标记圆角外的白色连通区域
work = src.copy()
for seed in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
    ImageDraw.floodfill(work, seed, MARK, thresh=60)

# 2. 生成 alpha：标记区透明，其余不透明
wp = work.load()
mask = Image.new("L", (w, h), 255)
mp = mask.load()
for y in range(h):
    for x in range(w):
        if wp[x, y] == MARK:
            mp[x, y] = 0
mask = mask.filter(ImageFilter.GaussianBlur(1.2))   # 柔化边缘，缩小后平滑

# 3. 合成透明 RGBA
rgba = src.copy()
rgba.putalpha(mask)
rgba.save(os.path.join(ROOT, "assets", "icon-rgba.png"))

# 4. 多尺寸 Windows 图标（exe / 窗口）
ico_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
rgba.save(os.path.join(ROOT, "assets", "cigar.ico"), format="ICO", sizes=ico_sizes)

# 5. 托盘 / 通知 / 窗口用 png
for px in (256, 128, 64, 48, 32):
    rgba.resize((px, px), Image.LANCZOS).save(
        os.path.join(ROOT, "assets", f"icon-{px}.png"))

print("透明图标生成完成 ->", os.path.join(ROOT, "assets"))
for f in sorted(os.listdir(os.path.join(ROOT, "assets"))):
    print(" ", f)

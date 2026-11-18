# -*- coding: utf-8 -*-
"""生成透明背景的多尺寸 ico / icns 与 png。

两条路径：
1. 若存在 assets/icon-source.png：从四角 flood fill 精确识别圆角外白色（内部雪茄
   烟灰被深色隔开、不受影响），转透明并柔化边缘；
2. 否则用 PIL 程序化绘制一个深色圆角底 + 金雪茄的默认图标，保证在没有任何
   二进制源图的情况下也能生成全套图标（仓库因此无需纳入二进制资产）。

Windows 用 .ico，macOS 用 .icns（经 iconutil 生成，无 iconutil 时回退 PIL）。
"""
import os
import shutil
import subprocess
import sys
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, "assets")
SRC = os.path.join(ASSETS, "icon-source.png")
MARK = (255, 0, 255)


def _from_source():
    """从用户源图 flood fill 去背景，返回 RGBA。"""
    src = Image.open(SRC).convert("RGB")
    w, h = src.size

    work = src.copy()
    for seed in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        ImageDraw.floodfill(work, seed, MARK, thresh=60)

    wp = work.load()
    mask = Image.new("L", (w, h), 255)
    mp = mask.load()
    for y in range(h):
        for x in range(w):
            if wp[x, y] == MARK:
                mp[x, y] = 0
    mask = mask.filter(ImageFilter.GaussianBlur(1.2))

    rgba = src.copy()
    rgba.putalpha(mask)
    return rgba


def _draw_default(size=1024):
    """程序化绘制深色圆角底 + 横放金雪茄（透明圆角外区域）。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 深色圆角方形底
    radius = int(size * 0.22)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius,
                        fill=(43, 39, 35, 255))

    cy = size // 2
    th = int(size * 0.082)          # 雪茄厚度
    x0, x1 = int(size * 0.225), int(size * 0.775)
    y0, y1 = cy - th // 2, cy + th // 2
    cap = th // 2                   # 雪茄圆头半径

    # 整条金色主体（圆头）
    d.rounded_rectangle([x0, y0, x1, y1], radius=cap, fill=(199, 159, 72, 255))
    # 左端灰白烟灰
    ash1 = x0 + int(size * 0.075)
    d.rounded_rectangle([x0, y0, ash1, y1], radius=cap, fill=(214, 214, 214, 255))
    # 右端烟帽（稍深，增加层次）
    cap0 = x1 - int(size * 0.028)
    d.rounded_rectangle([cap0, y0, x1, y1], radius=cap, fill=(168, 132, 58, 255))
    # 金色环（亮金细环）
    ring0 = x1 - int(size * 0.066)
    ring1 = ring0 + int(size * 0.022)
    d.rectangle([ring0, y0, ring1, y1], fill=(231, 203, 130, 255))
    return img


def main():
    os.makedirs(ASSETS, exist_ok=True)
    if os.path.exists(SRC):
        rgba = _from_source()
        print("使用源图生成：", os.path.basename(SRC))
    else:
        rgba = _draw_default()
        print("未发现源图，使用程序化默认图标")

    rgba.save(os.path.join(ASSETS, "icon-rgba.png"))

    ico_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    rgba.save(os.path.join(ASSETS, "cigar.ico"), format="ICO", sizes=ico_sizes)

    for px in (256, 128, 64, 48, 32):
        rgba.resize((px, px), Image.LANCZOS).save(
            os.path.join(ASSETS, f"icon-{px}.png"))

    # macOS：生成 .icns（优先 iconutil，回退 PIL 直存）
    if sys.platform == "darwin":
        _make_icns(rgba)

    print("图标生成完成 ->", ASSETS)
    for f in sorted(os.listdir(ASSETS)):
        print(" ", f)


def _make_icns(rgba):
    """由 RGBA 母图生成 cigar.icns。优先用系统 iconutil 保证各尺寸质量。"""
    iconset = os.path.join(ASSETS, "cigar.iconset")
    if os.path.isdir(iconset):
        shutil.rmtree(iconset)
    os.makedirs(iconset, exist_ok=True)
    # Apple 规定的 iconset 尺寸与命名
    for name, px in (("icon_16x16.png", 16), ("icon_16x16@2x.png", 32),
                     ("icon_32x32.png", 32), ("icon_32x32@2x.png", 64),
                     ("icon_128x128.png", 128), ("icon_128x128@2x.png", 256),
                     ("icon_256x256.png", 256), ("icon_256x256@2x.png", 512),
                     ("icon_512x512.png", 512), ("icon_512x512@2x.png", 1024)):
        rgba.resize((px, px), Image.LANCZOS).save(os.path.join(iconset, name))

    target = os.path.join(ASSETS, "cigar.icns")
    if shutil.which("iconutil"):
        try:
            subprocess.run(["iconutil", "-c", "icns", iconset, "-o", target],
                           check=True, capture_output=True)
            shutil.rmtree(iconset, ignore_errors=True)
            print("已用 iconutil 生成 cigar.icns")
            return
        except Exception as e:
            print("iconutil 失败，回退 PIL：", e)
    # 回退：PIL 直接写 icns
    rgba.resize((512, 512), Image.LANCZOS).save(
        target, format="ICNS",
        sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512)])
    shutil.rmtree(iconset, ignore_errors=True)
    print("已用 PIL 生成 cigar.icns")


if __name__ == "__main__":
    main()

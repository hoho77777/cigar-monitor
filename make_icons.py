# -*- coding: utf-8 -*-
"""生成透明背景的多尺寸 ico 与 png。

路径：
1. 若存在 assets/icon-source.png：从四角 flood fill 精确识别圆角外白色（内部雪茄
   烟灰被深色隔开、不受影响），转透明并柔化边缘；
2. 缺少源图时**默认直接报错退出**，绝不静默生成占位图标——assets/ 被 .gitignore
   排除，新克隆天然没有源图，静默兜底会悄悄把官方图标换成占位图；
3. 仅当显式设置环境变量 CIGAR_ALLOW_DEFAULT_ICON=1 时，才用 PIL 程序化绘制
   「深色圆角底 + 金雪茄」的占位图标（供没有源图的第三方构建者使用）。
"""
import os
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, "assets")
SRC = os.path.join(ASSETS, "icon-source.png")
MARK = (255, 0, 255)
ALLOW_DEFAULT_ENV = "CIGAR_ALLOW_DEFAULT_ICON"


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
    elif os.environ.get(ALLOW_DEFAULT_ENV) == "1":
        rgba = _draw_default()
        print("[警告] 未发现 assets/icon-source.png，已按 %s=1 生成占位图标。" % ALLOW_DEFAULT_ENV)
        print("[警告] 该占位图标与官方图标完全不同，请勿用于正式发布。")
    else:
        print("=" * 68)
        print("[错误] 未找到图标源图：assets/icon-source.png")
        print("       仓库通过 .gitignore 排除二进制资产，新克隆不会自带源图和 ico。")
        print("       请把官方源图 icon-source.png 放入 assets/ 后重新执行本脚本。")
        print("       若确实没有源图、只需一个能跑通构建的占位图标，可设置：")
        print("       set %s=1   （PowerShell：$env:%s=\"1\"）" % (ALLOW_DEFAULT_ENV, ALLOW_DEFAULT_ENV))
        print("=" * 68)
        raise SystemExit(2)

    rgba.save(os.path.join(ASSETS, "icon-rgba.png"))

    ico_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    rgba.save(os.path.join(ASSETS, "cigar.ico"), format="ICO", sizes=ico_sizes)

    for px in (256, 128, 64, 48, 32):
        rgba.resize((px, px), Image.LANCZOS).save(
            os.path.join(ASSETS, f"icon-{px}.png"))

    print("图标生成完成 ->", ASSETS)
    for f in sorted(os.listdir(ASSETS)):
        print(" ", f)


if __name__ == "__main__":
    main()

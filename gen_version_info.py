# -*- coding: utf-8 -*-
"""根据 config.APP_VERSION 生成 PyInstaller 的 Windows 版本信息文件 version_info.txt。
每次打包前运行，确保版本号单一来源、不出现不一致。"""
import os
from config import APP_VERSION

ROOT = os.path.dirname(os.path.abspath(__file__))


def _tuple(version):
    parts = [int(x) for x in version.split(".")]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


def build_text():
    vt = _tuple(APP_VERSION)
    strings_common = [
        ("CompanyName", "CigarMonitor"),
        ("FileDescription", "雪茄库存监控"),
        ("ProductName", "雪茄库存监控"),
        ("FileVersion", APP_VERSION),
        ("ProductVersion", APP_VERSION),
        ("LegalCopyright", "Local personal use"),
        ("OriginalFilename", "CigarMonitor.exe"),
    ]

    def string_block(codepage):
        lines = ",\n".join(
            "        StringStruct(%r, %r)" % (k, v) for k, v in strings_common
        )
        return "      StringTable(%r, [\n%s\n      ])" % (codepage, lines)

    block_zh = string_block("080404B0")
    block_en = string_block("040904B0")
    return f"""# UTF-8
# 由 gen_version_info.py 自动生成，请勿手动编辑
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={vt},
    prodvers={vt},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
    ),
  kids=[
    StringFileInfo([
{block_zh},
{block_en}
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200, 1033, 1200])])
  ]
)
"""


def main():
    out = os.path.join(ROOT, "version_info.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(build_text())
    print("written:", out, "version:", APP_VERSION)


if __name__ == "__main__":
    main()

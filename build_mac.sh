#!/bin/bash
# CigarMonitor macOS 打包脚本
# 产出 dist/CigarMonitor.app（原生 arm64 / 视 Python 架构而定）+ 可分发的 zip
set -e

cd "$(dirname "$0")"

# 优先使用项目 venv，其次系统 python3
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="python3"
fi

APP_NAME="CigarMonitor"
BUNDLE_ID="com.hoho77777.cigarmonitor"
VERSION=$($PY -c "import re; s=open('config.py',encoding='utf-8').read(); print(re.search(r'APP_VERSION\s*=\s*\"([^\"]+)\"',s).group(1))")

echo "[build] 版本 $VERSION"
echo "[build] 解释器 $PY"
echo "[build] 架构 $(uname -m)"

# 1) 图标（.icns 由 make_icons.py 经 iconutil 生成）
if [ ! -f "assets/cigar.icns" ]; then
  echo "[build] 图标缺失，生成中..."
  $PY make_icons.py
fi

# 2) 清理旧产物
rm -rf build dist

# 3) PyInstaller 打包（.app bundle）
$PY -m PyInstaller --noconfirm --windowed \
  --name "$APP_NAME" \
  --osx-bundle-identifier "$BUNDLE_ID" \
  --icon "assets/cigar.icns" \
  --collect-all curl_cffi \
  --collect-all webview \
  --collect-all pystray \
  --collect-all pyobjc \
  --hidden-import pystray._darwin \
  --hidden-import webview.platforms.cocoa \
  --add-data "templates:templates" \
  --add-data "static:static" \
  --add-data "seed:seed" \
  --add-data "assets:assets" \
  desktop.py

if [ ! -d "dist/$APP_NAME.app" ]; then
  echo "[error] 打包失败：未生成 dist/$APP_NAME.app"
  exit 1
fi

# 4) 写入版本号到 Info.plist
PLIST="dist/$APP_NAME.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string $VERSION" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VERSION" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $VERSION" "$PLIST"

# 5) ad-hoc 代码签名（避免 Gatekeeper 直接报"已损坏"，仍需右键打开）
echo "[build] ad-hoc 签名..."
codesign --force --deep --sign - "dist/$APP_NAME.app" 2>&1 | tail -3 || echo "[warn] 签名失败，不影响本机运行"

# 6) 打包为可分发 zip（保留 .app 结构与权限）
echo "[build] 生成分发 zip..."
cd dist
zip -qry "${APP_NAME}-mac-${VERSION}.zip" "${APP_NAME}.app"
cd ..

echo "[done] 产物："
ls -lh "dist/${APP_NAME}.app" >/dev/null
du -sh "dist/$APP_NAME.app"
ls -lh "dist/${APP_NAME}-mac-${VERSION}.zip"
echo "[done] 版本 $VERSION 打包完成"

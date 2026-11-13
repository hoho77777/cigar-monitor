@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Build CigarMonitor

echo [build] Generating version info...
python gen_version_info.py

if not exist "assets\cigar.ico" (
  echo [build] Assets missing, generating icons...
  python make_icons.py
  if errorlevel 1 (
    echo [error] Icon source assets\icon-source.png is missing, build stopped.
    echo [error] Put icon-source.png into assets\, or set CIGAR_ALLOW_DEFAULT_ICON=1 to use the placeholder icon.
    pause
    exit /b 1
  )
)

echo [build] PyInstaller packaging...
python -m PyInstaller --noconfirm --onedir --windowed --name CigarMonitor ^
  --icon "assets\cigar.ico" ^
  --version-file "version_info.txt" ^
  --collect-all curl_cffi ^
  --collect-all webview ^
  --collect-all clr_loader ^
  --collect-all pystray ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --add-data "seed;seed" ^
  --add-data "assets;assets" ^
  desktop.py

if errorlevel 1 (
  echo [error] Build failed.
  pause
  exit /b 1
)
echo [done] Output: dist\CigarMonitor\ (folder)
pause

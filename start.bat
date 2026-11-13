@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Cigar Stock Monitor

python -c "import flask, requests, bs4, apscheduler, curl_cffi" 2>nul
if errorlevel 1 (
  echo [setup] Installing dependencies, please wait...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [error] Dependency installation failed. Please check Python / network.
    pause
    exit /b 1
  )
)

echo [run] Starting monitor... http://127.0.0.1:5050
python app.py
pause

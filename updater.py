# -*- coding: utf-8 -*-
"""自动检测与自动更新。

- 检测：读取 GitHub 最新 Release（公开 API，无需认证），比较语义化版本；
- 更新：下载新 exe 到临时目录，启动独立批处理，等待当前进程退出后替换并重启。
所有网络操作均带超时与异常兜底，失败不影响监控主流程。
"""
import json
import os
import re
import sys
import tempfile
import urllib.request

from config import APP_VERSION, GITHUB_OWNER, GITHUB_REPO

API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
HTTP_TIMEOUT = 20
_EXE_NAME = "CigarMonitor.exe"


def _version_tuple(text):
    nums = [int(x) for x in re.findall(r"\d+", str(text or ""))]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])


def _http_get(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "CigarMonitor", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read()


def check_for_update():
    """返回更新信息 dict；无更新或出错时返回 None。
    dict 字段：latest / current / notes / download_url / html_url。"""
    try:
        data = json.loads(_http_get(API_URL).decode("utf-8"))
    except Exception:
        return None

    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        return None

    latest = tag.lstrip("vV").strip()
    download_url = None
    for asset in data.get("assets", []) or []:
        name = str(asset.get("name") or "").lower()
        if name.endswith(".exe"):
            download_url = asset.get("browser_download_url")
            break

    if _version_tuple(latest) <= _version_tuple(APP_VERSION):
        return None

    return {
        "latest": latest,
        "current": APP_VERSION,
        "notes": str(data.get("body") or "").strip(),
        "html_url": data.get("html_url"),
        "download_url": download_url,
    }


def _download(url, progress=None):
    """下载到临时文件，返回本地路径。progress(received, total) 可选。"""
    req = urllib.request.Request(url, headers={"User-Agent": "CigarMonitor"})
    tmp_path = os.path.join(tempfile.gettempdir(), "CigarMonitor_new.exe")
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        received = 0
        with open(tmp_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                received += len(chunk)
                if progress:
                    try:
                        progress(received, total)
                    except Exception:
                        pass
    return tmp_path


def _build_batch(target, new_exe):
    """生成等待退出→替换→重启的批处理，返回路径。"""
    batch = os.path.join(tempfile.gettempdir(), "cigar_update.bat")
    # 批处理内容（CRLF，延迟扩展，避免中文路径问题）
    lines = [
        "@echo off",
        "setlocal enabledelayedexpansion",
        "chcp 65001 >nul",
        f'set "TARGET={target}"',
        f'set "NEW={new_exe}"',
        "set /a n=0",
        ":waitloop",
        f'tasklist /fi "imagename eq {_EXE_NAME}" 2>nul | find /i "{_EXE_NAME}" >nul',
        "if %errorlevel%==0 (",
        "  set /a n+=1",
        "  if !n! geq 60 goto end",
        "  >nul ping -n 2 127.0.0.1",
        "  goto waitloop",
        ")",
        '>nul copy /y "%NEW%" "%TARGET%"',
        'if exist "%TARGET%" start "" "%TARGET%"',
        ":end",
        '(goto) 2>nul & del "%~f0"',
        "",
    ]
    with open(batch, "w", encoding="gbk", errors="replace", newline="\r\n") as f:
        f.write("\r\n".join(lines))
    return batch


def apply_update(download_url, quit_callback=None, progress=None):
    """下载并应用更新，随后通过批处理在退出后替换并重启。
    仅在打包（frozen）模式下可执行实际替换。"""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("开发模式下不执行自动更新，请使用打包后的程序")
    if not download_url:
        raise RuntimeError("该版本未提供可下载的 exe 更新文件")

    target = sys.executable
    new_exe = _download(download_url, progress=progress)
    batch = _build_batch(target, new_exe)

    # 独立启动批处理（detached，不随主进程退出而终止）
    os.startfile(batch)

    if quit_callback:
        quit_callback()
    else:
        os._exit(0)

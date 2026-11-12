# -*- coding: utf-8 -*-
"""自动检测与整包更新（onedir）。

- 检测：读取 GitHub 最新 Release（公开 API，无需认证），比较语义化版本；
- 更新：下载 onedir 的 zip 包到临时目录并解压，启动独立批处理，
  等待当前进程退出后用 robocopy 镜像替换整个安装目录（exe + _internal），再重启。
用户数据位于 %LOCALAPPDATA%\\CigarMonitor，与安装目录隔离，整包替换不会触碰。
所有网络操作均带超时与异常兜底，失败不影响监控主流程。
"""
import json
import os
import re
import sys
import tempfile
import urllib.request
import zipfile

from config import APP_VERSION, GITHUB_OWNER, GITHUB_REPO

API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
HTTP_TIMEOUT = 30
_EXE_NAME = "CigarMonitor.exe"
_PKG_NAME = "CigarMonitor_update.zip"
_EXTRACT_NAME = "CigarMonitor_extract"


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
    dict 字段：latest / current / notes / download_url / html_url。
    download_url 指向 onedir 的 zip 整包（兼容历史 .exe 资产）。"""
    try:
        data = json.loads(_http_get(API_URL).decode("utf-8"))
    except Exception:
        return None

    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        return None

    latest = tag.lstrip("vV").strip()
    assets = data.get("assets", []) or []
    download_url = None
    # 优先 zip 整包
    for asset in assets:
        if str(asset.get("name") or "").lower().endswith(".zip"):
            download_url = asset.get("browser_download_url")
            break
    # 兼容：历史单 exe 资产
    if not download_url:
        for asset in assets:
            if str(asset.get("name") or "").lower().endswith(".exe"):
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
    """下载 zip 到临时文件，返回本地路径。progress(received, total) 可选。"""
    req = urllib.request.Request(url, headers={"User-Agent": "CigarMonitor"})
    tmp_path = os.path.join(tempfile.gettempdir(), _PKG_NAME)
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


def _extract(zip_path):
    """解压 zip 到临时目录，返回解压根目录；并定位含 CigarMonitor.exe 的应用目录。"""
    extract_root = os.path.join(tempfile.gettempdir(), _EXTRACT_NAME)
    if os.path.exists(extract_root):
        import shutil
        shutil.rmtree(extract_root, ignore_errors=True)
    os.makedirs(extract_root, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_root)

    # 定位应用目录（兼容 zip 顶层是否带一层目录）
    if os.path.exists(os.path.join(extract_root, _EXE_NAME)):
        app_dir = extract_root
    else:
        app_dir = None
        for name in os.listdir(extract_root):
            sub = os.path.join(extract_root, name)
            if os.path.isdir(sub) and os.path.exists(os.path.join(sub, _EXE_NAME)):
                app_dir = sub
                break
        if app_dir is None:
            for root, _dirs, files in os.walk(extract_root):
                if _EXE_NAME in files:
                    app_dir = root
                    break
    if not app_dir:
        raise RuntimeError("更新包格式无效：解压后未找到 CigarMonitor.exe")
    return extract_root, app_dir


def _build_batch(install_dir, app_dir, extract_root, zip_path):
    """生成等待退出→robocopy 镜像整目录→重启→清理的批处理，返回路径。"""
    batch = os.path.join(tempfile.gettempdir(), "cigar_update.bat")
    exe_path = os.path.join(install_dir, _EXE_NAME)
    lines = [
        "@echo off",
        "setlocal enabledelayedexpansion",
        "chcp 65001 >nul",
        f'set "SRC={app_dir}"',
        f'set "DST={install_dir}"',
        f'set "EXE={exe_path}"',
        f'set "EXTRACT_ROOT={extract_root}"',
        f'set "ZIP={zip_path}"',
        "set /a n=0",
        ":waitloop",
        f'tasklist /fi "imagename eq {_EXE_NAME}" 2>nul | find /i "{_EXE_NAME}" >nul',
        "if %errorlevel%==0 (",
        "  set /a n+=1",
        "  if !n! geq 60 goto end",
        "  >nul ping -n 2 127.0.0.1",
        "  goto waitloop",
        ")",
        "rem 镜像同步：/MIR 删除目标多余文件，保证与新包完全一致",
        'robocopy "%SRC%" "%DST%" /MIR /NFL /NDL /NJH /NJS /NP /R:2 /W:2',
        "if %errorlevel% GEQ 8 goto cleanup",
        'if exist "%EXE%" start "" "%EXE%"',
        ":cleanup",
        'rmdir /s /q "%EXTRACT_ROOT%"',
        'del "%ZIP%"',
        ":end",
        '(goto) 2>nul & del "%~f0"',
        "",
    ]
    with open(batch, "w", encoding="gbk", errors="replace", newline="\r\n") as f:
        f.write("\r\n".join(lines))
    return batch


def apply_update(download_url, quit_callback=None, progress=None):
    """下载并整包应用更新，随后通过批处理在退出后镜像替换安装目录并重启。
    仅在打包（frozen）的 onedir 模式下执行实际替换。"""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("开发模式下不执行自动更新，请使用打包后的程序")
    if not download_url:
        raise RuntimeError("该版本未提供可下载的更新包（zip）")

    install_dir = os.path.dirname(os.path.abspath(sys.executable))
    zip_path = _download(download_url, progress=progress)
    extract_root, app_dir = _extract(zip_path)
    batch = _build_batch(install_dir, app_dir, extract_root, zip_path)

    # 独立启动批处理（detached，不随主进程退出而终止）
    os.startfile(batch)

    if quit_callback:
        quit_callback()
    else:
        os._exit(0)

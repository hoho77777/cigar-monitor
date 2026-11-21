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
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from config import APP_VERSION, GITHUB_OWNER, GITHUB_REPO, IS_MAC

API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
HTTP_TIMEOUT = 30
_EXE_NAME = "CigarMonitor.exe"
_PKG_NAME = "CigarMonitor_update.zip"
_EXTRACT_NAME = "CigarMonitor_extract"

# ---- macOS 专属常量 ----
_APP_NAME = "CigarMonitor.app"
_MAC_PKG_NAME = "CigarMonitor_mac_update.zip"
_MAC_EXTRACT_NAME = "CigarMonitor_mac_extract"


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


def _platform_keywords():
    if sys.platform.startswith("win"):
        return ("windows",)
    if sys.platform == "darwin":
        return ("macos", "mac", "osx", "darwin")
    return ("linux",)


def _pick_asset(assets):
    """按当前平台挑整包，返回 (下载地址, 是否需手动安装, 资产名)。

    Windows 只接受名字含 windows 的 zip（并兼容早期不带平台词的 onedir zip）；
    macOS 只接受名字含 macos/mac/osx 的包，dmg/pkg 视为需要手动安装。
    绝不把另一平台的包返回给当前平台。注意 1.3.1 及更早客户端没有这层过滤
    （取资产列表里第一个 zip），所以发布时仍要保证 Windows 包排在前面。
    """
    kws = _platform_keywords()
    lower = [(a, str(a.get("name") or "").lower()) for a in assets]

    # 1. 名字带平台标识的 zip：自动更新用
    for a, n in lower:
        if n.endswith(".zip") and any(k in n for k in kws):
            return a.get("browser_download_url"), False, n

    # 2. Windows 兼容旧命名（不带平台词，也不含其它平台词）
    if sys.platform.startswith("win"):
        others = ("macos", "mac", "darwin", "osx", "linux")
        for a, n in lower:
            if n.endswith(".zip") and not any(k in n for k in others):
                return a.get("browser_download_url"), False, n
        for a, n in lower:
            if n.endswith(".exe") and "setup" not in n:
                return a.get("browser_download_url"), False, n

    # 3. macOS：dmg / pkg 只能手动安装
    for a, n in lower:
        if n.endswith((".dmg", ".pkg")):
            return a.get("browser_download_url"), True, n

    return None, False, ""


def check_for_update():
    """返回更新信息 dict；无更新或出错时返回 None。
    dict 字段：latest / current / notes / download_url / html_url / asset / manual_install。
    download_url 指向当前平台的整包；manual_install=True 时表示只有 dmg/pkg
    这类需手动安装的包，不能走整包替换流程。"""
    try:
        data = json.loads(_http_get(API_URL).decode("utf-8"))
    except Exception:
        return None

    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        return None

    latest = tag.lstrip("vV").strip()
    assets = data.get("assets", []) or []
    download_url, manual, asset_name = _pick_asset(assets)

    if _version_tuple(latest) <= _version_tuple(APP_VERSION):
        return None

    return {
        "latest": latest,
        "current": APP_VERSION,
        "notes": str(data.get("body") or "").strip(),
        "html_url": data.get("html_url"),
        "download_url": download_url,
        "asset": asset_name,
        "manual_install": manual,
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


# ---------------- macOS 整包更新 ----------------
def _current_app_bundle():
    """从当前可执行文件定位 .app bundle 路径（.../CigarMonitor.app）。"""
    p = os.path.abspath(sys.executable)
    marker = _APP_NAME + os.sep
    idx = p.find(marker)
    if idx >= 0:
        return p[:idx + len(_APP_NAME)]
    return None


def _mac_download(url, progress=None):
    """下载 mac zip 到临时文件。"""
    req = urllib.request.Request(url, headers={"User-Agent": "CigarMonitor"})
    tmp_path = os.path.join(tempfile.gettempdir(), _MAC_PKG_NAME)
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


def _mac_extract(zip_path):
    """解压并定位 CigarMonitor.app，返回 (extract_root, app_bundle_path)。"""
    import shutil
    extract_root = os.path.join(tempfile.gettempdir(), _MAC_EXTRACT_NAME)
    if os.path.exists(extract_root):
        shutil.rmtree(extract_root, ignore_errors=True)
    os.makedirs(extract_root, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_root)

    # 定位 .app（兼容顶层是否带一层目录）
    direct = os.path.join(extract_root, _APP_NAME)
    if os.path.isdir(direct):
        return extract_root, direct
    for root, dirs, _files in os.walk(extract_root):
        for d in dirs:
            if d == _APP_NAME:
                return extract_root, os.path.join(root, d)
    raise RuntimeError("更新包格式无效：解压后未找到 CigarMonitor.app")


def _build_mac_script(target_app, new_app, extract_root, zip_path):
    """生成等待退出→替换 .app→重启→清理的 shell 脚本，返回路径。"""
    script = os.path.join(tempfile.gettempdir(), "cigar_update.sh")
    bin_path = os.path.join(target_app, "Contents", "MacOS", "CigarMonitor")
    lines = [
        "#!/bin/bash",
        "set -e",
        f'NEW_APP="{new_app}"',
        f'TARGET_APP="{target_app}"',
        f'EXTRACT_ROOT="{extract_root}"',
        f'ZIP="{zip_path}"',
        f'BIN="{bin_path}"',
        "n=0",
        "# 等待当前进程退出（最多约 2 分钟）",
        f'while pgrep -f "{bin_path}" >/dev/null 2>&1; do',
        "  n=$((n+1))",
        "  if [ $n -ge 120 ]; then exit 0; fi",
        "  sleep 1",
        "done",
        "# 替换整个 .app bundle",
        'rm -rf "$TARGET_APP"',
        'ditto "$NEW_APP" "$TARGET_APP"',
        "# 重启",
        'open "$TARGET_APP"',
        "# 清理",
        'rm -rf "$EXTRACT_ROOT" "$ZIP"',
        'rm -f "$0"',
        "",
    ]
    with open(script, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.chmod(script, 0o755)
    return script


def apply_update(download_url, quit_callback=None, progress=None):
    """下载并整包应用更新。

    Windows：批处理在退出后 robocopy 镜像替换安装目录并重启；
    macOS：shell 脚本在退出后替换 .app bundle 并 open 重启。
    仅在打包（frozen）模式下执行实际替换。"""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("开发模式下不执行自动更新，请使用打包后的程序")
    if not download_url:
        raise RuntimeError("该版本未提供当前平台的自动更新包，请到 Release 页面手动下载")

    if IS_MAC:
        target_app = _current_app_bundle()
        if not target_app:
            raise RuntimeError("无法定位当前应用，自动更新失败")
        zip_path = _mac_download(download_url, progress=progress)
        extract_root, new_app = _mac_extract(zip_path)
        script = _build_mac_script(target_app, new_app, extract_root, zip_path)
        # detached 启动，不随主进程退出而终止
        subprocess.Popen(["/bin/bash", script],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         start_new_session=True)
        if quit_callback:
            quit_callback()
        else:
            os._exit(0)
        return

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

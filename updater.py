# -*- coding: utf-8 -*-
"""
自动更新模块

机制：
1. 检查 GitHub 仓库最新 Release 的版本号与当前版本对比；
2. 有新版本时下载新的 exe 到临时文件；
3. 生成一个独立的 .bat 升级脚本：等待本进程退出 → 替换 exe → 重新启动；
4. 由前端确认后触发，应用退出时 bat 完成替换并重启。

仅在打包后的 exe 环境（sys.frozen）执行实际替换；源码运行时只做检查。
"""
import os
import sys
import json
import tempfile
import subprocess
import urllib.request


def _public_config():
    """从 config.py 读取仓库信息，避免硬编码分散。"""
    try:
        import config
        return {
            "owner": getattr(config, "GITHUB_OWNER", ""),
            "repo": getattr(config, "GITHUB_REPO", ""),
            "current": getattr(config, "APP_VERSION", "0.0.0"),
        }
    except Exception:
        return {"owner": "", "repo": "", "current": "0.0.0"}


def check_update(timeout=15):
    """
    查询最新 Release。

    返回 dict：
      {"update": bool, "current": str, "latest": str,
       "notes": str, "download_url": str}
    网络失败或未配置仓库时返回 update=False，不抛异常给调用方。
    """
    cfg = _public_config()
    result = {"update": False, "current": cfg["current"], "latest": cfg["current"],
              "notes": "", "download_url": ""}
    if not cfg["owner"] or not cfg["repo"]:
        return result
    url = f"https://api.github.com/repos/{cfg['owner']}/{cfg['repo']}/releases/latest"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CigarMonitor"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        # 离线 / 限流 / 无 Release 都视为“暂无更新”，不打断主程序
        return result

    latest = (data.get("tag_name") or "").lstrip("v")
    result["latest"] = latest or cfg["current"]
    result["notes"] = data.get("body", "") or ""
    for asset in data.get("assets", []):
        if asset.get("name", "").lower().endswith(".exe"):
            result["download_url"] = asset.get("browser_download_url", "")
            break

    if latest and _version_tuple(latest) > _version_tuple(cfg["current"]):
        result["update"] = bool(result["download_url"])
    return result


def _version_tuple(v):
    """把 '1.2.3' 转为可比较的整数元组，非法片段按 0 处理。"""
    parts = []
    for piece in str(v).split("."):
        num = ""
        for ch in piece:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    return tuple(parts)


def download_update(download_url, progress_cb=None):
    """
    下载新 exe 到临时目录，返回临时文件路径。
    progress_cb(received_bytes, total_bytes) 可选，用于前端展示进度。
    """
    fd, tmp_path = tempfile.mkstemp(suffix=".new.exe", prefix="cigar_update_")
    os.close(fd)
    req = urllib.request.Request(download_url, headers={"User-Agent": "CigarMonitor"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp_path, "wb") as out:
        total = int(resp.headers.get("Content-Length", 0)) or None
        received = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            out.write(chunk)
            received += len(chunk)
            if progress_cb:
                progress_cb(received, total)
    return tmp_path


def apply_update(new_exe_path):
    """
    生成升级 bat 并启动，随后退出当前应用。

    bat 逻辑：轮询等待本进程结束 → 复制新文件覆盖当前 exe → 重新启动。
    非 frozen 环境不允许调用（没有可替换的 exe）。
    """
    if not getattr(sys, "frozen", False):
        raise RuntimeError("源码运行环境不支持自动更新，请用 git pull 升级")

    target_exe = sys.executable
    target_dir = os.path.dirname(target_exe)
    bat_path = os.path.join(tempfile.gettempdir(), "cigar_upgrade.bat")

    # 等待当前进程退出后再替换，避免文件占用；用 PID 精确等待
    pid = os.getpid()
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        f'set "TARGET={target_exe}"',
        f'set "NEW={new_exe_path}"',
        "set /a n=0",
        f":waitloop",
        f"tasklist /FI \"PID eq {pid}\" 2>nul | find \"{pid}\" >nul",
        "if not errorlevel 1 (",
        "  set /a n+=1",
        "  if !n! geq 60 goto done",
        "  timeout /t 1 /nobreak >nul",
        "  goto waitloop",
        ")",
        "setlocal enabledelayedexpansion",
        ":copyloop",
        'copy /y "%NEW%" "%TARGET%" >nul',
        "if errorlevel 1 (",
        "  timeout /t 1 /nobreak >nul",
        "  goto copyloop",
        ")",
        ":done",
        'start "" "%TARGET%"',
        'del "%NEW%" >nul 2>nul',
        "(goto) 2>nul & del \"%~f0\"",
    ]
    # 开启延迟变量扩展需要在脚本顶部声明，这里统一重写
    bat_text = "@echo off\r\nsetlocal enabledelayedexpansion\r\n" + "\r\n".join(
        ln for ln in lines if ln not in ("@echo off", "setlocal enabledelayedexpansion"))
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_text)

    subprocess.Popen(["cmd", "/c", bat_path],
                     cwd=target_dir,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return bat_path

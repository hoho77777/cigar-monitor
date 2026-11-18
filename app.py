# -*- coding: utf-8 -*-
"""雪茄库存监控：本地 Web 管理 + 后台定时检查 + 邮件通知。"""
import json
import os
import re
import subprocess
import time
import threading
import ctypes
from ctypes import wintypes
import webbrowser
from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template, request
from apscheduler.schedulers.background import BackgroundScheduler

import database as db
from config import (WEB_HOST, WEB_PORT, SMTP_PRESETS, RESOURCE_DIR,
                    DB_PATH, SEED_JSON, APP_VERSION, SAME_DOMAIN_GAP,
                    BACKOFF_BASE, BACKOFF_MULTIPLIER, BACKOFF_MAX,
                    IS_MAC, IS_WINDOWS)
from monitor import check_product, fetch_page_title
from notifier import (send_email, back_in_stock_html, test_email_html,
                      stock_greeting, brand_label)
import tagger
import brands
import updater
import rates
import clawbot

app = Flask(
    __name__,
    template_folder=os.path.join(RESOURCE_DIR, "templates"),
    static_folder=os.path.join(RESOURCE_DIR, "static"),
)
JOB_ID = "scheduled_check"
scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

# 域名级 429 自适应退避状态（进程内）：domain -> {"level": int, "next_at": monotonic}
_domain_backoff = {}

# 桌面端系统通知回调（desktop.py 注册；开发模式为 None 时静默跳过）
system_notify = None

# 自动更新后用于彻底退出应用的回调（desktop.py 注册）
update_quit = None


# ---------------- 检查与通知核心 ----------------
def perform_check(pid):
    product = db.get_product(pid)
    if not product:
        return None
    old_status = product.get("status", "unknown")

    try:
        status, detail, code, info = check_product(product)
    except Exception as e:
        status, detail, code, info = "unknown", f"抓取失败: {e}", None, None

    # 本次无法确认真实状态（限流/超时/页面无标记）：保留上次已确认状态，不降级为未知
    if status == "unknown":
        db.add_log(pid, "unknown", code, detail)
        if old_status in ("in_stock", "out_of_stock"):
            keep_text = f"{detail}（本次无法确认，沿用上次状态）"
            db.update_status(pid, old_status, keep_text)
            return {"id": pid, "status": old_status, "detail": keep_text,
                    "notified": False, "degraded": True, "code": code}
        db.update_status(pid, "unknown", detail)
        return {"id": pid, "status": "unknown", "detail": detail, "notified": False, "code": code}

    # 是否需要发邮件
    should_notify = False
    if status == "in_stock":
        mode = db.get_settings().get("notify_mode", "change")
        should_notify = (mode == "always") or (old_status != "in_stock")

    db.update_status(pid, status, detail)
    db.add_log(pid, status, code, detail)
    # 保存本次抓取到的价格/货币/支数（供到手价估算）
    if info:
        db.update_product_info(pid, info.get("price"),
                               info.get("currency", ""), info.get("quantity", 1))

    result = {"id": pid, "status": status, "detail": detail, "notified": False, "code": code}
    if should_notify:
        fresh = with_tags(db.get_product(pid))
        # 右下角系统通知（独立于邮件，失败不影响邮件发送）
        if system_notify is not None:
            try:
                blabel = brand_label(fresh)
                title = f"{blabel}雪茄有货" if blabel else "雪茄有货提醒"
                system_notify(title, fresh["name"])
            except Exception:
                pass
        try:
            send_email(db.get_settings(), stock_greeting(fresh), back_in_stock_html(fresh))
            db.update_status(pid, status, detail, notified=True)
            result["notified"] = True
        except Exception as e:
            mail_err = f"邮件发送失败: {e}"
            db.add_log(pid, status, code, mail_err)
            result["mail_error"] = str(e)
        # 微信 ClawBot：扫码绑定后自动推送，未绑定静默跳过
        if clawbot.get_credential(db.get_settings()).get("bot_token"):
            try:
                ok, msg = clawbot.send_stock_alert(fresh)
                if ok:
                    result["notified"] = True
                else:
                    db.add_log(pid, status, code, f"微信通知失败: {msg}")
            except Exception as e:
                db.add_log(pid, status, code, f"微信通知失败: {e}")
    return result


def run_check_all():
    # 1. 按域名分组启用的商品
    grouped = {}
    for product in db.list_products():
        if product.get("enabled"):
            domain = urlparse(product["url"]).netloc.lower().replace("www.", "")
            grouped.setdefault(domain, []).append(product)

    for domain, products in grouped.items():
        state = _domain_backoff.get(domain)
        now = time.monotonic()

        # 2. 退避窗口未到：跳过该域名，不发请求，记录一次跳过日志
        if state is not None and now < state["next_at"]:
            wait_min = max(1, round((state["next_at"] - now) / 60))
            for p in products:
                db.add_log(p["id"], "unknown", None,
                           f"站点限流退避中，本轮跳过，约 {wait_min} 分钟后重试")
            continue

        # 3. 到点检查：同站商品错峰，逐个抓取
        got_429 = False
        for i, product in enumerate(products):
            if i > 0:
                time.sleep(SAME_DOMAIN_GAP)
            try:
                result = perform_check(product["id"]) or {}
            except Exception as e:
                db.add_log(product["id"], "unknown", None, f"检查异常: {e}")
                result = {}
            if result.get("code") == 429:
                got_429 = True

        # 4. 更新退避状态：出现 429 则升级，全部正常则重置
        if got_429:
            level = (state.get("level", 0) + 1) if state else 1
            gap = min(BACKOFF_BASE * (BACKOFF_MULTIPLIER ** (level - 1)), BACKOFF_MAX)
            _domain_backoff[domain] = {"level": level, "next_at": time.monotonic() + gap}
        elif state:
            _domain_backoff.pop(domain, None)


def reschedule():
    job = scheduler.get_job(JOB_ID)
    if job:
        job.remove()
    interval = max(30, int(db.get_settings().get("check_interval", 300)))
    scheduler.add_job(
        run_check_all, "interval", seconds=interval, id=JOB_ID,
        max_instances=1, coalesce=True,
        next_run_time=datetime.now() + timedelta(seconds=10),
    )


# ---------------- 启动辅助 ----------------
def ensure_database():
    """初始化数据库；首次运行（商品表为空）时从纯文本种子预置监控项。"""
    db.init_db()
    if db.list_products() or not os.path.exists(SEED_JSON):
        return
    try:
        with open(SEED_JSON, "r", encoding="utf-8") as f:
            seed = json.load(f)
    except Exception:
        return
    for item in seed.get("products", []):
        url = (item.get("url") or "").strip()
        if not url:
            continue
        try:
            db.create_product(
                item.get("name") or url,
                url,
                adapter=item.get("adapter") or "auto",
            )
        except Exception:
            continue


def start_scheduler():
    reschedule()
    if not scheduler.running:
        scheduler.start()
    # 微信 ClawBot 会话保活：后台长轮询维护 context_token（未绑定时空转）
    clawbot.start_keepalive()


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)


def run_flask():
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False, use_reloader=False)


# ---------------- 页面 ----------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/overview")
def overview():
    job = scheduler.get_job(JOB_ID)
    products = db.list_products()
    return jsonify({
        "total": len(products),
        "enabled": sum(1 for p in products if p.get("enabled")),
        "in_stock": sum(1 for p in products if p.get("status") == "in_stock"),
        "out_of_stock": sum(1 for p in products if p.get("status") == "out_of_stock"),
        "unknown": sum(1 for p in products if p.get("status") == "unknown"),
        "next_run": job.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if job and job.next_run_time else None,
    })


# ---------------- 监控项 ----------------
def with_tags(product):
    """给商品附加系统自动识别的标签（只读，不入库）。"""
    if product is None:
        return None
    product = dict(product)
    buckets = tagger.extract_tags(product["name"], product["url"])
    product["tag_buckets"] = buckets
    product["tags"] = tagger.flat_tags(buckets)
    return product


@app.route("/api/brands")
def brands_dict():
    """返回雪茄品牌中英文词库，供前端中文搜索与标签显示。"""
    return jsonify(brands.brand_table())


@app.route("/api/products")
def products():
    return jsonify([with_tags(p) for p in db.list_products()])


@app.route("/api/products", methods=["POST"])
def add_product():
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    name = (data.get("name") or "").strip()
    if not url or not url.startswith(("http://", "https://")):
        return jsonify({"error": "请输入有效的 http/https 网址"}), 400
    if db.get_product_by_url(url):
        return jsonify({"error": "该网址已在监控列表中"}), 400

    if not name:
        name = fetch_page_title(url) or urlparse(url).netloc
    name = re.sub(r"\s+", " ", name).strip()
    pid = db.create_product(name[:120], url)
    perform_check(pid)        # 添加后立即检查一次
    return jsonify(with_tags(db.get_product(pid)))


@app.route("/api/products/<int:pid>", methods=["PUT"])
def edit_product(pid):
    if not db.get_product(pid):
        return jsonify({"error": "监控项不存在"}), 404
    data = request.get_json(force=True)
    if "enabled" in data:
        data["enabled"] = 1 if data["enabled"] else 0
    db.update_product(pid, data)
    return jsonify(with_tags(db.get_product(pid)))


@app.route("/api/products/<int:pid>", methods=["DELETE"])
def remove_product(pid):
    if not db.get_product(pid):
        return jsonify({"error": "监控项不存在"}), 404
    db.delete_product(pid)
    return jsonify({"ok": True})


@app.route("/api/products/<int:pid>/check", methods=["POST"])
def check_one(pid):
    if not db.get_product(pid):
        return jsonify({"error": "监控项不存在"}), 404
    return jsonify(perform_check(pid))


@app.route("/api/check-all", methods=["POST"])
def check_all_now():
    results = []
    for product in db.list_products():
        if product.get("enabled"):
            results.append(perform_check(product["id"]))
    return jsonify(results)


# ---------------- 设置 ----------------
@app.route("/api/settings")
def get_settings():
    return jsonify({"settings": db.get_settings(), "presets": SMTP_PRESETS})


@app.route("/api/settings", methods=["POST"])
def save_settings():
    data = request.get_json(force=True)
    db.save_settings(data)
    reschedule()
    return jsonify(db.get_settings())


@app.route("/api/test-email", methods=["POST"])
def test_email():
    try:
        send_email(db.get_settings(), "【测试】雪茄库存监控发信测试", test_email_html())
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ---------------- AI 接入：本机 Host 扫描与配置写入 ----------------
import shutil

MCP_SERVER_NAME = "cigar-monitor"


def _multi_drive_paths(rel):
    """在各固定盘符与常见程序目录下生成候选路径（覆盖自定义盘安装）。"""
    out = []
    for drive in ("C:", "D:", "E:", "F:"):
        out.append(os.path.join(drive + "\\", rel))
    pf = os.environ.get("ProgramFiles", "")
    pf86 = os.environ.get("ProgramFiles(x86)", "")
    if pf:
        out.append(os.path.join(pf, rel))
    if pf86:
        out.append(os.path.join(pf86, rel))
    return out


def _doubao_marks():
    la = os.environ.get("LOCALAPPDATA", "")
    ap = os.environ.get("APPDATA", "")
    marks = [os.path.join(la, "DoubaoWork"), os.path.join(la, "Doubao"),
             os.path.join(ap, "Doubao")]
    marks += _multi_drive_paths(os.path.join("Doubao"))
    return [p for p in marks if p]


def _qianwen_marks():
    la = os.environ.get("LOCALAPPDATA", "")
    ap = os.environ.get("APPDATA", "")
    pf = os.environ.get("ProgramFiles", "")
    marks = [
        os.path.join(la, "Qianwen"),
        os.path.join(pf, "QianwenApp") if pf else "",
        # 兼容旧版/其他命名
        os.path.join(la, "QwenWork"),
        os.path.join(ap, "QwenWork")]
    marks += _multi_drive_paths("QianwenApp")
    marks += _multi_drive_paths("Qianwen")
    return [p for p in marks if p]


def _mac_hosts():
    """macOS 版 AI Host 定义：应用在 /Applications，配置在 ~/Library。"""
    home = os.path.expanduser("~")
    app_support = os.path.join(home, "Library", "Application Support")
    return [
        {"id": "claude", "name": "Claude Desktop", "marks": [
            os.path.join(app_support, "Claude"),
            os.path.join("/Applications", "Claude.app")],
         "config_path": os.path.join(app_support, "Claude",
                                     "claude_desktop_config.json"),
         "process_name": "Claude"},
        {"id": "doubao", "name": "豆包", "marks": [
            os.path.join(app_support, "Doubao"),
            os.path.join("/Applications", "豆包.app"),
            os.path.join("/Applications", "Doubao.app")],
         "config_path": None, "process_name": "Doubao"},
        {"id": "workbuddy", "name": "WorkBuddy", "marks": [
            os.path.join(home, ".workbuddy")],
         "config_path": os.path.join(home, ".workbuddy", "mcp.json"),
         "process_name": "WorkBuddy"},
        {"id": "winclaw", "name": "WinClaw", "marks": [
            os.path.join(home, ".openclaw")],
         "config_path": os.path.join(home, ".openclaw", "openclaw.json"),
         "process_name": "WinClaw"},
        {"id": "qwenwork", "name": "千问", "marks": [
            os.path.join(app_support, "Qianwen"),
            os.path.join(app_support, "Qwen"),
            os.path.join("/Applications", "千问.app")],
         "config_path": None, "process_name": "Qwen",
         "process_names": ["Qwen", "Qianwen", "QwenWork"]},
    ]


# id | 名称 | 安装标记路径 | 可自动写入的配置文件（None=暂不支持自动写入）
if IS_MAC:
    AI_HOSTS = _mac_hosts()
else:
    AI_HOSTS = [
        {"id": "claude", "name": "Claude Desktop", "marks": [
            os.path.join(os.environ.get("APPDATA", ""), "Claude"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Claude")],
         "config_path": os.path.join(os.environ.get("APPDATA", ""),
                                    "Claude", "claude_desktop_config.json"),
         "process_name": "Claude.exe"},
        {"id": "doubao", "name": "豆包", "marks": _doubao_marks(),
         "config_path": None, "process_name": "Doubao.exe"},
        {"id": "workbuddy", "name": "WorkBuddy", "marks": [
            os.path.join(os.path.expanduser("~"), ".workbuddy"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "WorkBuddy"),
            os.path.join(os.environ.get("APPDATA", ""), "WorkBuddy")],
         "config_path": os.path.join(os.path.expanduser("~"),
                                    ".workbuddy", "mcp.json"),
         "process_name": "WorkBuddy.exe"},
        {"id": "winclaw", "name": "WinClaw", "marks": [
            os.path.join(os.path.expanduser("~"), ".openclaw")],
         "config_path": os.path.join(os.path.expanduser("~"),
                                    ".openclaw", "openclaw.json"),
         "process_name": "WinClaw.exe"},
        {"id": "qwenwork", "name": "千问",
         "marks": _qianwen_marks(),
         "config_path": None, "process_name": "qianwen.exe",
         "process_names": ["qianwen.exe", "QwenWork.exe", "Qwen.exe"]},
    ]


def _mcp_entry():
    # HTTP 模式：指向本服务的 MCP 端点（端点在下一步开发）
    return {"url": f"http://127.0.0.1:{WEB_PORT}/mcp"}


def _is_connected(config_path):
    if not config_path or not os.path.exists(config_path):
        return False
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return MCP_SERVER_NAME in data.get("mcpServers", {})
    except Exception:
        return False


def _write_host_config(config_path, connect):
    data = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return False, "配置文件格式异常，已保留未动"
    data.setdefault("mcpServers", {})
    if connect:
        data["mcpServers"][MCP_SERVER_NAME] = _mcp_entry()
    else:
        data["mcpServers"].pop(MCP_SERVER_NAME, None)
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    if os.path.exists(config_path):
        shutil.copy2(config_path, config_path + ".bak")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return True, ""


def _mac_process_path(process_name):
    """macOS 下按可执行名返回首个匹配进程的完整路径，无则 None。用 ps，不引入新依赖。"""
    try:
        out = subprocess.run(["ps", "-axo", "pid=,comm="],
                             capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    target = os.path.basename(process_name).lower()
    for line in out.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            _pid, path = parts
            if os.path.basename(path).lower() == target:
                return path
    return None


def _process_path_by_name(process_name):
    """按进程名（不区分大小写）返回首个匹配进程的完整映像路径，无则 None。

    Windows 用 ctypes 调 Toolhelp API；macOS 走 ps，均不引入 psutil。
    """
    if IS_MAC:
        return _mac_process_path(process_name)
    TH32CS_SNAPPROCESS = 0x00000002
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260)]

    k32 = ctypes.windll.kernel32
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return None
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    target = process_name.lower()
    found_pid = None
    try:
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == target:
                found_pid = entry.th32ProcessID
                break
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    if not found_pid:
        return None
    hproc = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, found_pid)
    if not hproc:
        return None
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = wintypes.DWORD(260)
        if k32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size)):
            return buf.value
    finally:
        k32.CloseHandle(hproc)
    return None


def _proc_names(h):
    return h.get("process_names") or (
        [h["process_name"]] if h.get("process_name") else [])


def _uninstall_icon_by_name(display_name):
    """按显示名在卸载注册表中找 DisplayIcon 指向的可执行文件（不依赖运行状态）。"""
    if IS_MAC:
        # macOS 无注册表，安装实体改由 .app bundle / 应用目录判定
        return None
    try:
        import winreg
        roots = [
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall")]
        for root, sub in roots:
            try:
                k = winreg.OpenKey(root, sub)
            except OSError:
                continue
            i = 0
            while True:
                try:
                    sk = winreg.EnumKey(k, i); i += 1
                except OSError:
                    break
                try:
                    appk = winreg.OpenKey(k, sk)
                    dn = winreg.QueryValueEx(appk, "DisplayName")[0]
                    if display_name.lower() in dn.lower():
                        try:
                            icon = winreg.QueryValueEx(appk, "DisplayIcon")[0]
                        except OSError:
                            icon = ""
                        p = icon.split(",")[0].strip().strip('"')
                        if p and os.path.exists(p):
                            return p
                except OSError:
                    pass
    except Exception:
        pass
    return None


def _find_exe_under_dir(root, exe_names, max_depth=4, max_entries=500):
    """在目录下递归找指定可执行文件（限深度与扫描数量，避免大目录拖慢）。"""
    targets = {n.lower() for n in exe_names}
    root = os.path.abspath(root)
    seen = 0

    def walk(d, depth):
        nonlocal seen
        if depth > max_depth or seen > max_entries:
            return None
        try:
            entries = os.listdir(d)
        except OSError:
            return None
        for name in entries:
            full = os.path.join(d, name)
            seen += 1
            if os.path.isfile(full) and name.lower() in targets:
                return full
        for name in entries:
            full = os.path.join(d, name)
            if os.path.isdir(full):
                r = walk(full, depth + 1)
                if r:
                    return r
        return None

    return walk(root, 0)


def _detect_host_install_mac(h):
    """macOS 安装判定：运行进程优先，其次 .app bundle 或应用/配置目录存在。"""
    # 1. 运行进程（覆盖任意自定义路径）
    for pn in _proc_names(h):
        p = _mac_process_path(pn)
        if p:
            return p
    # 2. marks：.app bundle 或已存在的目录即算安装实体
    for m in h.get("marks", []):
        if m and os.path.exists(m):
            if m.endswith(".app") or os.path.isdir(m):
                return m
    return ""


def _detect_host_install(h):
    """按强证据优先判定是否安装，避免把卸载后残留的配置目录误判为已安装。

    Windows 证据优先级：运行进程 → 注册表卸载条目 → mark 指向的 exe → 目录内递归找到的 exe。
    macOS 走 _detect_host_install_mac。
    """
    if IS_MAC:
        return _detect_host_install_mac(h)
    # 1. 运行进程（覆盖任意自定义安装路径）
    for pn in _proc_names(h):
        p = _process_path_by_name(pn)
        if p:
            return p
    # 2. 注册表卸载条目（系统登记的安装实体）
    p = _uninstall_icon_by_name(h["name"])
    if p:
        return p
    exe_names = _proc_names(h)
    for m in h["marks"]:
        if not m:
            continue
        # 3. mark 直接指向可执行文件
        if os.path.isfile(m) and m.lower().endswith(".exe"):
            return m
        # 4. 目录类 mark：里面能找到对应 exe 才算；纯配置/日志残留不会误判
        if os.path.isdir(m) and exe_names:
            p = _find_exe_under_dir(m, exe_names)
            if p:
                return p
    return ""


@app.route("/api/ai/scan")
def ai_scan():
    hosts = []
    for h in AI_HOSTS:
        found = _detect_host_install(h)
        hosts.append({"id": h["id"], "name": h["name"],
                      "installed": bool(found), "path": found,
                      "auto_writable": bool(h["config_path"]),
                      "connected": _is_connected(h["config_path"])})
    return jsonify({"hosts": hosts, "mcp_url": _mcp_entry()["url"],
                    "scanned_at": datetime.now().strftime("%H:%M:%S")})


def _ai_config_action(connect):
    payload = request.get_json(silent=True) or {}
    host = next((h for h in AI_HOSTS if h["id"] == payload.get("host")), None)
    if not host or not _detect_host_install(host):
        return jsonify({"error": "Host 不可用"}), 400
    if not host["config_path"]:
        return jsonify({"error": "该 Host 暂不支持自动写入，请用手动接入"}), 400
    ok, err = _write_host_config(host["config_path"], connect)
    if not ok:
        return jsonify({"error": err}), 400
    # 允许多个 AI 同时接入：只写入/移除当前目标，不影响其他 Host
    return jsonify({"ok": True, "config_path": host["config_path"]})


@app.route("/api/ai/connect", methods=["POST"])
def ai_connect():
    return _ai_config_action(True)


@app.route("/api/ai/disconnect", methods=["POST"])
def ai_disconnect():
    return _ai_config_action(False)


# ---------------- 手动接入状态（后端持久化，不依赖 WebView2/localStorage） ----------------
def _load_manual_flow():
    try:
        data = json.loads(db.get_settings().get("manual_ai_flow", "{}") or "{}")
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


@app.route("/api/ai/manual-flow")
def ai_manual_flow_get():
    return jsonify({"flow": _load_manual_flow()})


@app.route("/api/ai/manual-flow", methods=["POST"])
def ai_manual_flow_save():
    payload = request.get_json(silent=True) or {}
    flow = payload.get("flow")
    if not isinstance(flow, dict):
        return jsonify({"error": "flow 必须是对象"}), 400
    # 只保留合法阶段，避免写入脏数据
    allowed = ("", "connecting", "connected", "disconnecting")
    clean = {str(k): str(v) for k, v in flow.items() if str(v) in allowed}
    db.save_settings({"manual_ai_flow": json.dumps(clean, ensure_ascii=False)})
    return jsonify({"flow": clean})


def _find_host_exe_mac(h):
    """macOS 定位应用：先取运行进程路径，再从 marks 找 .app bundle。"""
    for pn in _proc_names(h):
        p = _mac_process_path(pn)
        if p:
            return p
    for m in h.get("marks", []):
        if m and m.endswith(".app") and os.path.exists(m):
            return m
    return None


def _restart_host_mac(h):
    """macOS 一键重启：pkill 结束实例后用 open 重启 .app。"""
    target = _find_host_exe_mac(h)
    if not target:
        return False, "未找到程序路径，请手动重启"
    for pn in _proc_names(h):
        subprocess.run(["pkill", "-x", os.path.basename(pn)],
                       capture_output=True)
    time.sleep(2)
    if target.endswith(".app"):
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen([target], close_fds=True)
    return True, target


def _find_host_exe(h):
    if IS_MAC:
        return _find_host_exe_mac(h)
    name = h["process_name"]
    # 1. 从运行中进程取可执行路径
    ps = ("(Get-Process -Name '%s' -ErrorAction SilentlyContinue | "
          "Select-Object -First 1).Path" % name)
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True,
                             timeout=20).stdout.strip()
        if out and os.path.exists(out):
            return out
    except Exception:
        pass
    # 2. 注册表卸载条目 DisplayIcon 兜底
    try:
        import winreg
        roots = [
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall")]
        for root, sub in roots:
            try:
                k = winreg.OpenKey(root, sub)
            except OSError:
                continue
            i = 0
            while True:
                try:
                    sk = winreg.EnumKey(k, i); i += 1
                except OSError:
                    break
                try:
                    appk = winreg.OpenKey(k, sk)
                    dn = winreg.QueryValueEx(appk, "DisplayName")[0]
                    if h["name"].lower() in dn.lower():
                        icon = winreg.QueryValueEx(appk, "DisplayIcon")[0]
                        p = icon.split(",")[0].strip().strip('"')
                        if os.path.exists(p):
                            return p
                except OSError:
                    pass
    except Exception:
        pass
    return None


def _restart_host(h):
    if IS_MAC:
        return _restart_host_mac(h)
    exe = _find_host_exe(h)
    if not exe:
        return False, "未找到程序路径，请手动重启"
    subprocess.run(["taskkill", "/IM", h["process_name"], "/F"],
                   capture_output=True)
    time.sleep(2)
    subprocess.Popen([exe], close_fds=True)
    return True, exe


@app.route("/api/ai/restart", methods=["POST"])
def ai_restart():
    payload = request.get_json(silent=True) or {}
    h = next((x for x in AI_HOSTS if x["id"] == payload.get("host")), None)
    if not h or not h.get("process_name"):
        return jsonify({"error": "该 Host 暂不支持一键重启"}), 400
    ok, info = _restart_host(h)
    if not ok:
        return jsonify({"error": info}), 400
    return jsonify({"ok": True, "exe": info})


# ---------------- 微信 ClawBot ----------------
@app.route("/api/clawbot/status")
def clawbot_status():
    """绑定与保活状态（只读，不发起网络请求）。"""
    return jsonify(clawbot.status())


@app.route("/api/clawbot/qr/start", methods=["POST"])
def clawbot_qr_start():
    try:
        return jsonify(clawbot.start_login())
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/clawbot/qr/status")
def clawbot_qr_status():
    return jsonify(clawbot.login_status(request.args.get("session", "")))


@app.route("/api/clawbot/qr/verify", methods=["POST"])
def clawbot_qr_verify():
    data = request.get_json(force=True)
    ok = clawbot.submit_verify_code(data.get("session", ""), data.get("code", ""))
    return jsonify({"ok": ok})


@app.route("/api/clawbot/unbind", methods=["POST"])
def clawbot_unbind():
    clawbot.clear_binding()
    return jsonify({"ok": True})


@app.route("/api/clawbot/test", methods=["POST"])
def clawbot_test():
    # 还没拿到 context_token 时，微信侧不允许 bot 主动下发，直接给出可执行的下一步
    try:
        ready = clawbot.refresh_tokens_once() > 0
    except Exception:
        ready = False
    if not ready:
        return jsonify({
            "error": "还差一步：请在微信里给 ClawBot 发任意一条消息，界面会自动变为「通道就绪」，然后再点「发送测试微信」",
            "need_activation": True,
        }), 400
    ok, msg = clawbot.send_text(clawbot.test_message())
    if ok:
        return jsonify({"ok": True, "message": msg})
    return jsonify({"error": msg}), 400


# ---------------- 版本与自动更新 ----------------
@app.route("/api/version")
def version():
    return jsonify({"version": APP_VERSION})


@app.route("/api/check-update", methods=["POST"])
def check_update_route():
    info = updater.check_for_update()
    return jsonify({"current": APP_VERSION, "update": info})


@app.route("/api/apply-update", methods=["POST"])
def apply_update_route():
    info = updater.check_for_update()
    if not info or not info.get("download_url"):
        return jsonify({"error": "暂无可应用的更新"}), 400
    try:
        updater.apply_update(info["download_url"], quit_callback=update_quit)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


# ---------------- 英文收货地址 ----------------
DEFAULT_ADDRESS = {
    "line1": "", "line2": "",
    "country": "China", "state": "Guangdong Sheng",
    "city": "", "zip": "",
}


@app.route("/api/address")
def get_address():
    addr = dict(DEFAULT_ADDRESS)
    raw = db.get_settings().get("en_address")
    if raw:
        try:
            addr.update(json.loads(raw))
        except (ValueError, TypeError):
            pass
    return jsonify(addr)


@app.route("/api/address", methods=["POST"])
def save_address():
    data = request.get_json(force=True)
    addr = {k: str(data.get(k, "")).strip() for k in DEFAULT_ADDRESS}
    db.save_settings({"en_address": json.dumps(addr, ensure_ascii=False)})
    return jsonify(addr)


# ---------------- 雪茄到手计算器 ----------------
@app.route("/api/calculator/rates")
def calculator_rates():
    return jsonify(rates.get_all())


@app.route("/api/calculator/calculate", methods=["POST"])
def calculator_calculate():
    data = request.get_json(force=True)
    code = str(data.get("currency", "EUR")).upper()
    if code not in rates.CURRENCY_CODES:
        return jsonify({"error": "不支持的货币"}), 400
    try:
        price = float(data.get("price", 0) or 0)
        count = int(float(data.get("count", 1) or 1))
        shipping = float(data.get("shipping", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "请输入有效数字"}), 400
    if price < 0 or shipping < 0 or count < 1:
        return jsonify({"error": "数值不合法"}), 400

    live = rates.get_live_rates()
    customs = rates.get_customs_rates()
    live_rate = live["rates"][code]
    customs_rate = customs["rates"][code]

    goods_cny = round(price * live_rate, 2)                 # 商品人民币价（市场汇率）
    shipping_cny = round(shipping * live_rate, 2)          # 人民币运费（市场汇率，不入税基）
    taxable_raw = price * customs_rate                     # 海关计税价格（海关汇率）
    taxable_base = round(taxable_raw, 2)
    pre_tax = round(taxable_raw * 0.5, 2)                  # 免征前完整税额（烟草 50%）

    # 应征税额 ≤50 元可能免征：给 0～全额区间；否则按完整税额单值
    maybe_exempt = pre_tax <= 50
    if maybe_exempt:
        tax_low, tax_high = 0.0, pre_tax
    else:
        tax_low = tax_high = pre_tax

    total_low = round(goods_cny + shipping_cny + tax_low, 2)
    total_high = round(goods_cny + shipping_cny + tax_high, 2)
    over_limit = taxable_base > 2000                       # 超寄递限值（退运/货物办理风险）

    return jsonify({
        "currency": code,
        "inputs": {"price": price, "count": count, "shipping": shipping},
        "rates": {"live": live_rate, "customs": customs_rate,
                  "live_source": live.get("source"),
                  "customs_source": customs.get("source"),
                  "customs_period": customs.get("period"),
                  "customs_date": customs.get("actual_date"),
                  "stale": bool(live.get("stale") or customs.get("stale"))},
        "goods_cny": goods_cny,
        "shipping_cny": shipping_cny,
        "taxable_base": taxable_base,
        "pre_tax": pre_tax,
        "maybe_exempt": maybe_exempt,
        "tax_low": tax_low,
        "tax_high": tax_high,
        "total_low": total_low,
        "total_high": total_high,
        "unit_low": round(total_low / count, 2),
        "unit_high": round(total_high / count, 2),
        "over_limit": over_limit,
    })


# ---------------- 日志 ----------------
@app.route("/api/logs")
def logs():
    limit = min(int(request.args.get("limit", 50)), 200)
    product_id = request.args.get("product_id")
    return jsonify(db.list_logs(limit=limit, product_id=product_id))


# ---------------- AI 工具执行器 ----------------
import tools_def


def _find_product_by_url(url):
    url = (url or "").strip()
    p = db.get_product_by_url(url)
    if p:
        return p
    for x in db.list_products():
        if x["url"] == url:
            return x
    return None


def execute_ai_tool(name, args):
    if name == "get_app_status":
        job = scheduler.get_job(JOB_ID)
        products = db.list_products()
        return {
            "running": True, "version": APP_VERSION, "total": len(products),
            "enabled": sum(1 for p in products if p.get("enabled")),
            "in_stock": sum(1 for p in products if p.get("status") == "in_stock"),
            "out_of_stock": sum(1 for p in products if p.get("status") == "out_of_stock"),
            "next_check": job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
            if job and job.next_run_time else None}

    if name == "list_inventory":
        status = (args.get("status") or "").strip()
        kw = (args.get("keyword") or "").strip().lower()
        out = []
        for p in db.list_products():
            if status and p.get("status") != status:
                continue
            if kw and kw not in p["name"].lower() and kw not in p["url"].lower():
                continue
            out.append({"name": p["name"], "url": p["url"],
                        "status": p.get("status"), "enabled": bool(p.get("enabled"))})
        return {"count": len(out), "items": out}

    if name == "add_monitor_url":
        url = (args.get("url") or "").strip()
        pname = (args.get("name") or "").strip()
        if not url.startswith(("http://", "https://")):
            return {"error": "网址无效，需要 http/https 开头"}
        if db.get_product_by_url(url):
            return {"error": "该网址已在监控列表", "url": url}
        if not pname:
            pname = fetch_page_title(url) or urlparse(url).netloc
        pid = db.create_product(pname[:120], url)
        res = perform_check(pid)
        p = db.get_product(pid)
        return {"ok": True, "name": p["name"], "url": p["url"],
                "status": p.get("status"), "detail": (res or {}).get("detail")}

    if name == "run_check":
        url = (args.get("url") or "").strip()
        if url:
            p = _find_product_by_url(url)
            if not p:
                return {"error": "找不到该监控项", "url": url}
            res = perform_check(p["id"]) or {}
            return {"url": url, "status": res.get("status"), "detail": res.get("detail")}
        items = []
        for p in db.list_products():
            if p.get("enabled"):
                r = perform_check(p["id"]) or {}
                items.append({"name": p["name"], "status": r.get("status")})
        return {"checked": len(items), "items": items}

    if name == "set_enabled":
        url = (args.get("url") or "").strip()
        enabled = bool(args.get("enabled"))
        p = _find_product_by_url(url)
        if not p:
            return {"error": "找不到该监控项", "url": url}
        db.update_product(p["id"], {"enabled": 1 if enabled else 0})
        return {"ok": True, "name": p["name"], "enabled": enabled}

    if name == "delete_monitor":
        url = (args.get("url") or "").strip()
        p = _find_product_by_url(url)
        if not p:
            return {"error": "找不到该监控项", "url": url}
        db.delete_product(p["id"])
        return {"ok": True, "deleted": p["name"], "url": url}

    if name == "calculate_landed_cost":
        code = str(args.get("currency", "EUR")).upper()
        if code not in rates.CURRENCY_CODES:
            return {"error": "不支持的货币", "supported": rates.CURRENCY_CODES}
        try:
            price = float(args.get("price", 0) or 0)
            count = int(float(args.get("count", 1) or 1))
            shipping = float(args.get("shipping", 0) or 0)
        except (TypeError, ValueError):
            return {"error": "数字无效"}
        live = rates.get_live_rates()
        customs = rates.get_customs_rates()
        lr, cr = live["rates"][code], customs["rates"][code]
        goods = round(price * lr, 2)
        ship_cny = round(shipping * lr, 2)
        pre_tax = round(price * cr * 0.5, 2)
        exempt = pre_tax <= 50
        tax_low, tax_high = (0, pre_tax) if exempt else (pre_tax, pre_tax)
        total_low = round(goods + ship_cny + tax_low, 2)
        total_high = round(goods + ship_cny + tax_high, 2)
        return {"currency": code, "goods_cny": goods, "shipping_cny": ship_cny,
                "tax_rate": "50%", "maybe_exempt": exempt,
                "tax_low": tax_low, "tax_high": tax_high,
                "total_low": total_low, "total_high": total_high,
                "unit_low": round(total_low / count, 2),
                "unit_high": round(total_high / count, 2),
                "over_limit": round(price * cr, 2) > 2000}

    if name == "manage_address":
        action = args.get("action")
        if action == "get":
            addr = dict(DEFAULT_ADDRESS)
            raw = db.get_settings().get("en_address")
            if raw:
                try:
                    addr.update(json.loads(raw))
                except ValueError:
                    pass
            return addr
        if action == "save":
            addr = {k: str(args.get(k, "")).strip() for k in DEFAULT_ADDRESS}
            db.save_settings({"en_address": json.dumps(addr, ensure_ascii=False)})
            return {"ok": True, "address": addr}
        return {"error": "action 需为 get 或 save"}

    return {"error": "未知工具 %s" % name}


# ---------------- MCP 服务端点（Streamable HTTP，JSON-RPC 2.0） ----------------
MCP_PROTOCOL_VERSION = "2025-06-18"
_MCP_KNOWN_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")


def _mcp_tools():
    # 工具定义已是 MCP 原生格式，直接返回
    return tools_def.TOOL_DEFS


def _mcp_handle(message):
    """处理单条 JSON-RPC 消息。返回 (响应dict 或 None, 协商协议版本 或 None)。"""
    method = message.get("method")
    msg_id = message.get("id")
    params = message.get("params") or {}

    # 通知（无 id，如 notifications/initialized）：不回响应
    if msg_id is None:
        return None, None

    if method == "initialize":
        client_ver = params.get("protocolVersion")
        ver = client_ver if client_ver in _MCP_KNOWN_VERSIONS else MCP_PROTOCOL_VERSION
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": ver,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": MCP_SERVER_NAME, "version": APP_VERSION}}}, ver

    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}, None

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id,
                "result": {"tools": _mcp_tools()}}, None

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            result = execute_ai_tool(name, args)
        except Exception as e:
            result = {"error": str(e)}
        is_error = isinstance(result, dict) and "error" in result
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "content": [{"type": "text",
                         "text": json.dumps(result, ensure_ascii=False)}],
            "isError": is_error}}, None

    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": "Method not found: %s" % method}}, None


@app.route("/mcp", methods=["POST", "GET"])
def mcp_endpoint():
    # GET 用于建立 SSE 接收服务器主动推送；本服务无推送，明确拒绝
    if request.method == "GET":
        return "", 405
    data = request.get_json(force=True, silent=True)
    if data is None:
        return jsonify({"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": "Parse error"}}), 400

    negotiated = None
    if isinstance(data, list):
        responses = []
        for msg in data:
            resp, ver = _mcp_handle(msg)
            if ver:
                negotiated = ver
            if resp:
                responses.append(resp)
        if not responses:
            return "", 202          # 批量里全是通知
        body = jsonify(responses)
    else:
        resp, negotiated = _mcp_handle(data)
        if resp is None:
            return "", 202          # 单条通知
        body = jsonify(resp)

    if negotiated:
        body.headers["MCP-Protocol-Version"] = negotiated
    return body


def main():
    """浏览器模式入口（python app.py / start.bat）。"""
    ensure_database()
    start_scheduler()
    threading.Timer(1.5, lambda: webbrowser.open(f"http://{WEB_HOST}:{WEB_PORT}/")).start()
    run_flask()


if __name__ == "__main__":
    main()

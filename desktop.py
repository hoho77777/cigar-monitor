# -*- coding: utf-8 -*-
"""桌面端入口：后台监控（Flask + APScheduler）与窗口生命周期解耦。

- 点 × 关闭：窗口隐藏、最小化到系统托盘，后台继续监控；
- 窗口消息循环意外终止（如显示子系统异常导致 WebView2 失效）：自动重建窗口，
  后台监控与托盘始终存活、不中断；
- 只有托盘“退出”才真正结束进程。
"""
import ctypes
import os
import sys
import time
import threading
import traceback
from datetime import datetime

import requests
import webview
import pystray
from PIL import Image

from config import WEB_HOST, WEB_PORT, DATA_DIR, RESOURCE_DIR
import app as app_module
from app import ensure_database, start_scheduler, stop_scheduler, run_flask

# 崩溃与静默退出日志，放在应用数据根目录
CRASH_LOG = os.path.join(os.path.dirname(DATA_DIR), "crash.log")

state = {
    "allow_close": False,
    "hide_notified": False,
    "current_window": None,   # 当前有效窗口（自管，不依赖 webview.windows）
}


# ---------------- 异常落盘 ----------------
def _write_crash(where, exc):
    try:
        with open(CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] {where}\n")
            if exc is not None:
                f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    except Exception:
        pass


def _global_excepthook(etype, value, tb):
    try:
        with open(CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] 主线程未捕获异常\n")
            f.write("".join(traceback.format_exception(etype, value, tb)))
    except Exception:
        pass


def _thread_excepthook(args):
    try:
        with open(CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] 线程未捕获异常：{args.thread.name}\n")
            f.write("".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
    except Exception:
        pass


sys.excepthook = _global_excepthook
threading.excepthook = _thread_excepthook


# ---------------- 托盘 ----------------
def make_tray_image():
    # 直接使用雪茄图标（assets 已随打包资源一起发布）
    path = os.path.join(RESOURCE_DIR, "assets", "icon-64.png")
    return Image.open(path).convert("RGBA")


def on_show(icon, item):
    w = state["current_window"]
    if w is None:
        return
    try:
        w.restore()
        w.show()
    except Exception as e:
        try:
            w.show()
        except Exception:
            _write_crash("托盘恢复窗口", e)


def quit_app():
    """彻底停止调度、托盘、窗口并退出；托盘退出与自动更新共用。"""
    state["allow_close"] = True
    try:
        stop_scheduler()
    except Exception:
        pass
    try:
        tray_icon.stop()
    except Exception:
        pass
    try:
        w = state["current_window"]
        if w is not None:
            w.destroy()
    except Exception:
        pass
    time.sleep(0.5)
    os._exit(0)


def on_quit(icon, item):
    quit_app()


tray_icon = pystray.Icon(
    "CigarMonitor",
    make_tray_image(),
    "雪茄库存监控",
    menu=pystray.Menu(
        pystray.MenuItem("显示主窗口", on_show, default=True),
        pystray.MenuItem("退出", on_quit),
    ),
)


def wait_for_server(url, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=1).status_code == 200:
                return True
        except Exception:
            time.sleep(0.4)
    return False


def on_closing():
    # 真正退出时放行；否则隐藏窗口、后台托管
    if state["allow_close"]:
        return True
    w = state["current_window"]
    if w is not None:
        w.hide()
        if not state["hide_notified"]:
            tray_icon.notify("已转入后台继续监控，点击托盘图标可恢复窗口。", "雪茄库存监控")
            state["hide_notified"] = True
    return False


def push_stock_notification(title, message):
    # 有货时右下角 Windows 系统通知（复用托盘通知通道）
    try:
        tray_icon.notify(message, title)
    except Exception:
        pass


def auto_check_update():
    # 启动后后台检测一次，发现新版本通过系统通知提示（不强制更新）
    import updater
    time.sleep(8)
    try:
        info = updater.check_for_update()
        if info:
            tray_icon.notify(
                f"发现新版本 v{info['latest']}（当前 v{info['current']}），"
                "可在监控列表点击「检查更新」升级。",
                "软件更新")
    except Exception:
        pass


# ---------------- 后台服务监督 ----------------
def flask_supervisor():
    # 本地 Web 服务若异常退出则自动重启，窗口重建期间也持续可用
    while not state["allow_close"]:
        try:
            run_flask()
        except Exception as e:
            _write_crash("本地 Web 服务异常，将重启", e)
            time.sleep(2)


def main():
    app_module.system_notify = push_stock_notification
    app_module.update_quit = quit_app
    ensure_database()
    start_scheduler()

    server_thread = threading.Thread(target=flask_supervisor, daemon=True)
    server_thread.start()
    threading.Thread(target=auto_check_update, daemon=True).start()

    url = f"http://{WEB_HOST}:{WEB_PORT}/"
    if not wait_for_server(url):
        stop_scheduler()
        ctypes.windll.user32.MessageBoxW(
            0, "本地服务启动失败，请检查安全软件是否拦截。", "雪茄库存监控", 0x10)
        sys.exit(1)

    tray_icon.run_detached()

    # 窗口监督循环：意外终止即重建，只有托盘“退出”才结束
    while not state["allow_close"]:
        window = webview.create_window(
            "雪茄库存监控", url,
            width=1280, height=860, min_size=(960, 640),
            text_select=True,
        )
        window.events.closing += on_closing
        state["current_window"] = window

        try:
            webview.start(gui="edgechromium")
        except Exception as e:
            _write_crash("桌面窗口启动异常", e)

        if state["allow_close"]:
            break

        # 走到这里说明窗口消息循环意外结束（非主动退出），记录后重建
        _write_crash("窗口消息循环意外结束，3 秒后自动重建窗口", None)
        state["current_window"] = None
        time.sleep(3)


if __name__ == "__main__":
    main()

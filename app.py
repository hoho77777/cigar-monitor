# -*- coding: utf-8 -*-
"""雪茄库存监控：本地 Web 管理 + 后台定时检查 + 邮件通知。"""
import json
import os
import re
import threading
import webbrowser
from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template, request
from apscheduler.schedulers.background import BackgroundScheduler

import database as db
from config import (WEB_HOST, WEB_PORT, SMTP_PRESETS, RESOURCE_DIR,
                    DB_PATH, SEED_JSON, APP_VERSION)
from monitor import check_product, fetch_page_title
from notifier import send_email, back_in_stock_html, test_email_html, stock_greeting
import tagger
import updater

app = Flask(
    __name__,
    template_folder=os.path.join(RESOURCE_DIR, "templates"),
    static_folder=os.path.join(RESOURCE_DIR, "static"),
)
JOB_ID = "scheduled_check"
scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

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
        status, detail, code = check_product(product)
    except Exception as e:
        status, detail, code = "unknown", f"抓取失败: {e}", None

    # 本次无法确认真实状态（限流/超时/页面无标记）：保留上次已确认状态，不降级为未知
    if status == "unknown":
        db.add_log(pid, "unknown", code, detail)
        if old_status in ("in_stock", "out_of_stock"):
            keep_text = f"{detail}（本次无法确认，沿用上次状态）"
            db.update_status(pid, old_status, keep_text)
            return {"id": pid, "status": old_status, "detail": keep_text,
                    "notified": False, "degraded": True}
        db.update_status(pid, "unknown", detail)
        return {"id": pid, "status": "unknown", "detail": detail, "notified": False}

    # 是否需要发邮件
    should_notify = False
    if status == "in_stock":
        mode = db.get_settings().get("notify_mode", "change")
        should_notify = (mode == "always") or (old_status != "in_stock")

    db.update_status(pid, status, detail)
    db.add_log(pid, status, code, detail)

    result = {"id": pid, "status": status, "detail": detail, "notified": False}
    if should_notify:
        fresh = with_tags(db.get_product(pid))
        # 右下角系统通知（独立于邮件，失败不影响邮件发送）
        if system_notify is not None:
            try:
                system_notify(f"有货提醒：{fresh['name']}", "监控的雪茄已到货，点击查看商品页")
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
    return result


def run_check_all():
    for product in db.list_products():
        if product.get("enabled"):
            try:
                perform_check(product["id"])
            except Exception as e:
                db.add_log(product["id"], "unknown", None, f"检查异常: {e}")


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


# ---------------- 日志 ----------------
@app.route("/api/logs")
def logs():
    limit = min(int(request.args.get("limit", 50)), 200)
    product_id = request.args.get("product_id")
    return jsonify(db.list_logs(limit=limit, product_id=product_id))


def main():
    """浏览器模式入口（python app.py / start.bat）。"""
    ensure_database()
    start_scheduler()
    threading.Timer(1.5, lambda: webbrowser.open(f"http://{WEB_HOST}:{WEB_PORT}/")).start()
    run_flask()


if __name__ == "__main__":
    main()

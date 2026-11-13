# -*- coding: utf-8 -*-
"""雪茄库存监控：本地 Web 管理 + 后台定时检查 + 邮件 / 系统 / 微信通知。"""
import json
import os
import re
import time
import threading
import webbrowser
from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template, request
from apscheduler.schedulers.background import BackgroundScheduler

import database as db
from config import (WEB_HOST, WEB_PORT, SMTP_PRESETS, RESOURCE_DIR,
                    DB_PATH, SEED_JSON, APP_VERSION, SAME_DOMAIN_GAP,
                    BACKOFF_BASE, BACKOFF_MULTIPLIER, BACKOFF_MAX)
from monitor import check_product, fetch_page_title
from notifier import send_email, back_in_stock_html, test_email_html, stock_greeting
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
def _mail_configured(s):
    """SMTP 与收件人填齐即视为已启用邮件通知，无需额外开关。"""
    return all(str(s.get(k) or "").strip()
               for k in ("smtp_host", "smtp_port", "smtp_user", "smtp_pass", "mail_to"))


def dispatch_notifications(product, pid, status, code):
    """三路通知互不阻塞：系统托盘（常开）/ 邮件 / 微信 ClawBot。

    渠道没有开关：系统托盘始终发；SMTP 填齐就发邮件；微信绑定后就推送。
    未配置的一路静默跳过，不写失败日志。
    返回 (任一渠道成功, 各渠道结果)，任一成功即视为已提醒。
    """
    settings = db.get_settings()
    results = []

    # 系统托盘默认常开，不读取开关，避免误关后到货完全无感
    if system_notify is not None:
        try:
            system_notify(f"有货提醒：{product['name']}", "监控的雪茄已到货，点击查看商品页")
            results.append({"channel": "系统通知", "ok": True, "message": "已弹出"})
        except Exception as e:
            results.append({"channel": "系统通知", "ok": False, "message": str(e)})

    # 邮件：填齐 SMTP 即自动启用；未配置时静默跳过
    if _mail_configured(settings):
        try:
            send_email(settings, stock_greeting(product), back_in_stock_html(product))
            results.append({"channel": "邮件", "ok": True, "message": "已发送"})
        except Exception as e:
            results.append({"channel": "邮件", "ok": False, "message": str(e)})

    # 微信：扫码绑定后自动启用；未绑定时静默跳过，避免每次到货都刷日志
    if clawbot.get_credential(settings).get("bot_token"):
        try:
            ok, msg = clawbot.send_stock_alert(product)
            results.append({"channel": "微信 ClawBot", "ok": ok, "message": msg})
        except Exception as e:
            results.append({"channel": "微信 ClawBot", "ok": False, "message": str(e)})

    for r in results:
        if not r["ok"]:
            db.add_log(pid, status, code, "%s通知失败: %s" % (r["channel"], r["message"]))
    return any(r["ok"] for r in results), results


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
                    "notified": False, "degraded": True, "code": code}
        db.update_status(pid, "unknown", detail)
        return {"id": pid, "status": "unknown", "detail": detail, "notified": False, "code": code}

    # 是否触发提醒（沿用原有策略：仅缺货转有货，或每次有货）
    should_notify = False
    if status == "in_stock":
        mode = db.get_settings().get("notify_mode", "change")
        should_notify = (mode == "always") or (old_status != "in_stock")

    db.update_status(pid, status, detail)
    db.add_log(pid, status, code, detail)

    result = {"id": pid, "status": status, "detail": detail, "notified": False, "code": code}
    if should_notify:
        fresh = with_tags(db.get_product(pid))
        any_ok, channels = dispatch_notifications(fresh, pid, status, code)
        result["channels"] = channels
        if any_ok:
            db.update_status(pid, status, detail, notified=True)
            result["notified"] = True
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
    try:
        interval = int(db.get_settings().get("check_interval", 300))
    except (TypeError, ValueError):
        interval = 300
    interval = max(30, interval)
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
    # 还没拿到 context_token 时，微信侧不允许 bot 主动下发（会返回 -2 prepare
    # failed）。此时不再发注定失败的请求，直接给出可执行的下一步。
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


def main():
    """浏览器模式入口（python app.py / start.bat）。"""
    ensure_database()
    start_scheduler()
    threading.Timer(1.5, lambda: webbrowser.open(f"http://{WEB_HOST}:{WEB_PORT}/")).start()
    run_flask()


if __name__ == "__main__":
    main()

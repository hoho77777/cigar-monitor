# -*- coding: utf-8 -*-
"""邮件发送：支持 SSL(465) / STARTTLS(587) / 不加密，QQ 邮箱等通用。"""
import smtplib
import re
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from html import escape

import brands
import rates


def parse_recipients(raw):
    return [x.strip() for x in re.split(r"[;,，；\s]+", raw or "") if x.strip()]


def send_email(settings, subject, html_body, recipients=None):
    """发送邮件。recipients 为空时使用 settings 中的 mail_to。返回收件人列表。"""
    host = settings["smtp_host"].strip()
    port = int(settings["smtp_port"])
    user = settings["smtp_user"].strip()
    password = settings["smtp_pass"]
    security = settings.get("smtp_security", "ssl")
    to_addrs = recipients or parse_recipients(settings.get("mail_to", ""))
    if not host or not user or not password:
        raise ValueError("发件邮箱主机、账号或授权码未配置完整")
    if not to_addrs:
        raise ValueError("收件人邮箱未配置")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((settings.get("mail_from_name") or "雪茄库存监控", user))
    msg["To"] = ", ".join(to_addrs)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if security == "ssl":
        client = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        client = smtplib.SMTP(host, port, timeout=30)
        if security == "tls":
            client.starttls()
    try:
        client.login(user, password)
        client.sendmail(user, to_addrs, msg.as_string())
    finally:
        client.quit()
    return to_addrs


def greeting_word(h):
    if 5 <= h < 11:
        return "早上好"
    if 11 <= h < 14:
        return "中午好"
    if 14 <= h < 18:
        return "下午好"
    if 18 <= h < 22:
        return "晚上好"
    return "夜深了"


def _money_range(low, high):
    """人民币区间格式化：相等给单值，否则给区间。"""
    if low == high:
        return f"¥{low:,.2f}"
    return f"¥{low:,.2f} ~ ¥{high:,.2f}"


def landed_cost_summary(product):
    """按雪茄到手计算器公式估算到手总价/单价（运费按 0）。数据不足返回 None。"""
    price = product.get("price")
    code = (product.get("currency") or "").upper()
    count = product.get("quantity") or 1
    if price is None or not code or code not in rates.CURRENCY_CODES:
        return None
    try:
        price = float(price)
        count = int(count)
    except (TypeError, ValueError):
        return None
    live = rates.get_live_rates()
    customs = rates.get_customs_rates()
    live_rate = live["rates"][code]
    customs_rate = customs["rates"][code]

    goods_cny = round(price * live_rate, 2)
    taxable_base = round(price * customs_rate, 2)
    pre_tax = round(price * customs_rate * 0.5, 2)
    maybe_exempt = pre_tax <= 50
    if maybe_exempt:
        tax_low, tax_high = 0.0, pre_tax
    else:
        tax_low = tax_high = pre_tax
    total_low = round(goods_cny + tax_low, 2)
    total_high = round(goods_cny + tax_high, 2)
    return {
        "currency": code, "price": price, "count": count,
        "goods_cny": goods_cny, "taxable_base": taxable_base,
        "tax_low": tax_low, "tax_high": tax_high,
        "total_low": total_low, "total_high": total_high,
        "unit_low": round(total_low / count, 2),
        "unit_high": round(total_high / count, 2),
        "maybe_exempt": maybe_exempt,
        "over_limit": taxable_base > 2000,
    }


def brand_label(product):
    """品牌标签：英文（中文简称），无中文时只给英文，无品牌给空串。"""
    b = (product.get("tag_buckets") or {}).get("brand") or []
    en = b[0] if b else ""
    if not en:
        return ""
    zh = brands.short_zh(en)
    return f"{en}（{zh}）" if zh else en


def brand_zh(product):
    """中文品牌简称（用于问候语/标题）：有译名只给译名，没有才回退英文。"""
    b = (product.get("tag_buckets") or {}).get("brand") or []
    en = b[0] if b else ""
    if not en:
        return ""
    return brands.short_zh(en) or en


def stock_greeting(product, now=None):
    """针对单个有货商品生成问候语（与前端文案一致），用于邮件标题/正文/微信首行。

    品牌只保留中文简称（如 Quintero → 金特罗），英文名不再出现在标题里；
    正文里的「商品」字段仍是完整英文名，便于核对。
    """
    now = now or datetime.now()
    h = now.hour
    night = h < 5 or h >= 22
    brand = brand_zh(product)
    if night:
        return (f"夜深了，{brand}雪茄有货，抢完再睡！" if brand
                else "夜深了，有一款雪茄有货，抢完再睡！")
    word = greeting_word(h)
    return (f"{word}，{brand}雪茄有货，抓紧抢购！" if brand
            else f"{word}，有一款雪茄有货，抓紧抢购！")


def back_in_stock_html(product):
    name = escape(product.get("name") or product["url"])
    url = escape(product["url"])
    checked = escape(product.get("last_checked") or "")
    greet = escape(stock_greeting(product))
    landed = landed_cost_summary(product)
    landed_rows = ""
    if landed:
        note = ""
        if landed["over_limit"]:
            note = ('<p style="margin:6px 0 0;color:#b00020;font-size:12px">'
                    "计税价超 ¥2,000 寄递限值，可能需退运或按货物办理。</p>")
        elif landed["maybe_exempt"]:
            note = ('<p style="margin:6px 0 0;color:#86868b;font-size:12px">'
                    "应征税额 ≤¥50 可能免征，按 0～全额区间估算。</p>")
        landed_rows = f"""\
      <tr><td style="padding:8px 0;color:#86868b;vertical-align:top">商品原价</td><td style="padding:8px 0">{landed['price']:,.2f} {landed['currency']} · 共 {landed['count']} 支</td></tr>
      <tr><td style="padding:8px 0;color:#86868b">商品人民币价</td><td style="padding:8px 0">¥{landed['goods_cny']:,.2f}</td></tr>
      <tr><td style="padding:8px 0;color:#86868b">预估税费</td><td style="padding:8px 0">{escape(_money_range(landed['tax_low'], landed['tax_high']))}{note}</td></tr>
      <tr><td style="padding:8px 0;color:#86868b;font-weight:bold">到手总价</td><td style="padding:8px 0;font-weight:bold">{escape(_money_range(landed['total_low'], landed['total_high']))}</td></tr>
      <tr><td style="padding:8px 0;color:#86868b;font-weight:bold">到手单价</td><td style="padding:8px 0;font-weight:bold">{escape(_money_range(landed['unit_low'], landed['unit_high']))}</td></tr>
"""
    return f"""\
<div style="max-width:600px;margin:0 auto;font-family:-apple-system,'Segoe UI','Microsoft YaHei',Arial,sans-serif;
            border:1px solid #e5e5e7;border-radius:12px;overflow:hidden;background:#ffffff">
  <div style="background:#1d1d1f;color:#ffffff;padding:22px 28px;font-size:20px;font-weight:bold">
    雪茄库存提醒
  </div>
  <div style="padding:28px;color:#1d1d1f;line-height:1.8">
    <p style="font-size:17px;font-weight:bold;margin:0 0 16px">{greet}</p>
    <table style="width:100%;border-collapse:collapse;margin-bottom:20px;font-size:14px">
      <tr><td style="padding:8px 0;color:#86868b;width:80px;vertical-align:top">商品全称</td><td style="padding:8px 0">{name}</td></tr>
      <tr><td style="padding:8px 0;color:#86868b;vertical-align:top">商品链接</td><td style="padding:8px 0;word-break:break-all"><a href="{url}">{url}</a></td></tr>
      <tr><td style="padding:8px 0;color:#86868b">检查时间</td><td style="padding:8px 0">{checked}</td></tr>
      <tr><td style="padding:8px 0;color:#86868b">状态</td><td style="padding:8px 0;font-weight:bold">有货 In Stock</td></tr>
{landed_rows}    </table>
    <a href="{url}" style="display:inline-block;background:#1d1d1f;color:#ffffff;text-decoration:none;
        padding:12px 34px;border-radius:8px;font-size:15px">前往商品页</a>
    <p style="margin-top:22px;font-size:12px;color:#86868b">此邮件由本地雪茄库存监控工具自动发送，链接：{url}</p>
  </div>
</div>"""


def test_email_html():
    return """\
<div style="font-family:-apple-system,'Segoe UI','Microsoft YaHei',Arial,sans-serif;padding:24px;color:#1d1d1f">
  <h2 style="margin-top:0">测试邮件</h2>
  <p>如果您收到这封邮件，说明雪茄库存监控工具的发信配置已经生效。</p>
  <p style="color:#86868b;font-size:13px">本地部署 · 库存变化时将自动通知</p>
</div>"""

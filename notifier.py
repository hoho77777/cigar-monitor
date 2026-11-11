# -*- coding: utf-8 -*-
"""邮件发送：支持 SSL(465) / STARTTLS(587) / 不加密，QQ 邮箱等通用。"""
import smtplib
import re
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from html import escape


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


def stock_greeting(product, now=None):
    """针对单个有货商品生成问候语（与前端文案一致），用于邮件标题/正文。"""
    now = now or datetime.now()
    h = now.hour
    night = h < 5 or h >= 22
    brands = (product.get("tag_buckets") or {}).get("brand") or []
    brand = brands[0] if brands else ""
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
    </table>
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

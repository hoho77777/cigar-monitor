# -*- coding: utf-8 -*-
"""全局配置：路径、SMTP 预设、默认参数。同时支持开发模式与 PyInstaller 打包模式。"""
import os
import sys
import socket

# 软件版本（语义化版本：主.次.修订）
APP_VERSION = "1.1.0"

# GitHub 仓库（用于检测与下载更新）
GITHUB_OWNER = "hoho77777"
GITHUB_REPO = "cigar-monitor"

# 运行模式：PyInstaller 打包后 sys.frozen=True
IS_FROZEN = getattr(sys, "frozen", False)

# 只读资源目录（templates / static / 种子）
RESOURCE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))

# 可写数据目录：打包后放 %LOCALAPPDATA%\CigarMonitor，开发模式放项目内
if IS_FROZEN:
    _app_root = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "CigarMonitor")
    DATA_DIR = os.path.join(_app_root, "data")
else:
    DATA_DIR = os.path.join(RESOURCE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "monitor.db")
# 纯文本种子（首次启动预置监控项，无任何个人/二进制数据）
SEED_JSON = os.path.join(RESOURCE_DIR, "seed", "products.json")

# 本地服务
WEB_HOST = "127.0.0.1"


def find_free_port(start=5050):
    """从 start 起找一个可用端口，避免本机端口冲突。"""
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("未找到可用端口")


WEB_PORT = find_free_port()

# 常见邮箱 SMTP 预设
SMTP_PRESETS = {
    "qq":      {"label": "QQ 邮箱",   "host": "smtp.qq.com",       "port": 465, "security": "ssl"},
    "163":     {"label": "163 邮箱",  "host": "smtp.163.com",      "port": 465, "security": "ssl"},
    "126":     {"label": "126 邮箱",  "host": "smtp.126.com",      "port": 465, "security": "ssl"},
    "gmail":   {"label": "Gmail",     "host": "smtp.gmail.com",    "port": 465, "security": "ssl"},
    "outlook": {"label": "Outlook",   "host": "smtp.office365.com","port": 587, "security": "tls"},
    "custom":  {"label": "自定义",    "host": "",                  "port": 465, "security": "ssl"},
}

DEFAULT_SETTINGS = {
    "smtp_preset": "qq",
    "smtp_host": "smtp.qq.com",
    "smtp_port": "465",
    "smtp_security": "ssl",       # ssl=465 直连 | tls=587 STARTTLS | none=不加密
    "smtp_user": "",
    "smtp_pass": "",
    "mail_to": "",
    "mail_from_name": "雪茄库存监控",
    "check_interval": "300",      # 轮询间隔（秒），默认 5 分钟
    "notify_mode": "change",      # change=仅缺货转有货时通知 | always=每次检查有货都通知
}

# 抓取参数
REQUEST_TIMEOUT = 30
CF_RETRIES = 6                  # Cloudflare 挑战最大重试次数
CF_RETRY_WAIT = 2.5             # 重试间隔（秒）
MAX_LOGS_KEPT = 1000            # 日志保留条数
SAME_DOMAIN_GAP = 1.5           # 同一域名相邻请求最小间隔（秒），错峰避免触发限流
# 站点级 429 自适应退避：连续限流时按 5→10→20 分钟拉长该站检查间隔
BACKOFF_BASE = 300              # 退避基准（秒），首次 429 后按基准间隔再探测
BACKOFF_MULTIPLIER = 2          # 每多连续一轮 429，间隔翻倍
BACKOFF_MAX = 1200              # 退避封顶（秒），20 分钟
NETWORK_RETRIES = 2             # 仅针对网络异常（非 429）的重试次数

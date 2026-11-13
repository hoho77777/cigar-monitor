# -*- coding: utf-8 -*-
"""雪茄到手计算器汇率模块。

两套汇率：
- 海关计征汇率（税费用）：中国货币网官方人民币汇率中间价，取上月第三个周三，
  非银行间交易日自动顺延（以官方 JSON 是否存在判断），每月只需取一次。
- 实时市场汇率（商品总价、运费折算用）：open.er-api 主源，Frankfurter 备用。

全部本地缓存，网络不可用时回退缓存/内置参考值，保证离线可用。
"""
import os
import re
import json
from datetime import date, datetime, timedelta

import requests

from config import DATA_DIR, REQUEST_TIMEOUT

# 支持的 8 种货币（与参考计算器一致）
CURRENCIES = [
    {"code": "EUR", "cname": "欧元",     "symbol": "€",   "flag": "🇪🇺"},
    {"code": "USD", "cname": "美元",     "symbol": "$",   "flag": "🇺🇸"},
    {"code": "GBP", "cname": "英镑",     "symbol": "£",   "flag": "🇬🇧"},
    {"code": "CHF", "cname": "瑞郎",     "symbol": "Fr",  "flag": "🇨🇭"},
    {"code": "HKD", "cname": "港币",     "symbol": "HK$", "flag": "🇭🇰"},
    {"code": "CNY", "cname": "人民币",   "symbol": "¥",   "flag": "🇨🇳"},
    {"code": "SGD", "cname": "新加坡元", "symbol": "S$",  "flag": "🇸🇬"},
    {"code": "DKK", "cname": "丹麦克朗", "symbol": "kr",  "flag": "🇩🇰"},
]
CURRENCY_CODES = [c["code"] for c in CURRENCIES]

RATE_CACHE = os.path.join(DATA_DIR, "fx_rates.json")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}

# 内置离线兜底参考值（2026-11 实测，仅在无网络且无缓存时使用）
_FALLBACK_CUSTOMS = {
    "EUR": 7.5197, "USD": 6.7192, "GBP": 8.9562, "CHF": 8.1167,
    "HKD": 0.85619, "CNY": 1.0, "SGD": 5.2431, "DKK": 1.00604,
}
_FALLBACK_LIVE = {
    "EUR": 7.3984, "USD": 6.6844, "GBP": 8.8552, "CHF": 8.0135,
    "HKD": 0.8525, "CNY": 1.0, "SGD": 5.1983, "DKK": 0.9897,
}

# 官方中间价静态 JSON（URL 含日期规律）
_CHINAMONEY_TPL = ("https://www.chinamoney.com.cn/r/cms/www/chinamoney/data/"
                   "fx/ccpr-notice{day}.json")
# 中间价公告里的币种中文名
_CN_NAME = {
    "USD": "美元", "EUR": "欧元", "GBP": "英镑", "CHF": "瑞士法郎",
    "HKD": "港元", "SGD": "新加坡元",
}


# ---------------- 日期计算 ----------------
def third_wednesday(year, month):
    """指定年月的第三个星期三。"""
    first = date(year, month, 1)
    gap = (2 - first.weekday()) % 7          # weekday(): Mon=0, Wed=2
    first_wed = first + timedelta(days=gap)
    return first_wed + timedelta(days=14)


def customs_base_date(today=None):
    """本月计征汇率对应的基准日 = 上月第三个周三。"""
    today = today or date.today()
    if today.month == 1:
        return third_wednesday(today.year - 1, 12)
    return third_wednesday(today.year, today.month - 1)


def current_period(today=None):
    today = today or date.today()
    return "%04d-%02d" % (today.year, today.month)


# ---------------- 缓存读写 ----------------
def _load_cache():
    try:
        with open(RATE_CACHE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_cache(cache):
    try:
        tmp = RATE_CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp, RATE_CACHE)
    except Exception:
        pass


# ---------------- 海关计征汇率（官方中间价）----------------
def _fetch_chinamoney(day):
    """取某交易日官方中间价公告文字；非交易日/无数据返回 None。"""
    url = _CHINAMONEY_TPL.format(day=day.isoformat())
    r = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    text = r.json().get("data", {}).get("vo", {}).get("price", "")
    return text or None


def _parse_customs_text(text):
    """从公告文字解析 8 种货币对人民币的中间价。"""
    rates = {}
    for code in ("USD", "EUR", "GBP", "CHF", "HKD", "SGD"):
        m = re.search(r"1" + _CN_NAME[code] + r"对人民币([\d.]+)元", text)
        if m:
            rates[code] = float(m.group(1))
    # 丹麦克朗为反向报价：人民币 1 元对 N 丹麦克朗，需取倒数
    m = re.search(r"人民币1元对([\d.]+)丹麦克朗", text)
    if m:
        rates["DKK"] = round(1.0 / float(m.group(1)), 6)
    rates["CNY"] = 1.0
    return rates


def get_customs_rates(force=False):
    """本月海关计征汇率（缓存优先，其次网络，最后兜底）。"""
    cache = _load_cache()
    period = current_period()
    cached = cache.get("customs")

    if not force and cached and cached.get("period") == period and cached.get("rates"):
        return dict(cached, from_cache=True, stale=False)

    base = customs_base_date()
    try:
        actual, text = None, None
        probe = base
        for _ in range(15):               # 非交易日逐日顺延
            text = _fetch_chinamoney(probe)
            if text:
                actual = probe
                break
            probe += timedelta(days=1)
        if text:
            rec = {
                "rates": _parse_customs_text(text),
                "period": period,
                "base_date": base.isoformat(),
                "actual_date": actual.isoformat(),
                "source": "中国货币网官方中间价",
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
            }
            cache["customs"] = rec
            _save_cache(cache)
            return dict(rec, from_cache=False, stale=False)
    except Exception:
        pass

    if cached and cached.get("rates"):    # 网络失败：沿用上次缓存
        return dict(cached, from_cache=True, stale=True)
    return {
        "rates": dict(_FALLBACK_CUSTOMS),
        "period": period,
        "base_date": base.isoformat(),
        "actual_date": None,
        "source": "内置参考值",
        "fetched_at": None,
        "from_cache": False,
        "stale": True,
        "fallback": True,
    }


# ---------------- 实时市场汇率 ----------------
def _from_eur_base(raw):
    """以 EUR 为基准的汇率表 -> 各币种 1 单位折合人民币。"""
    cny_per_eur = raw["CNY"]
    out = {}
    for code in CURRENCY_CODES:
        if code in raw and raw[code]:
            out[code] = round(cny_per_eur / raw[code], 6)
    out["CNY"] = 1.0
    return out


def _live_erapi():
    r = requests.get("https://open.er-api.com/v6/latest/EUR",
                     headers=_HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    j = r.json()
    return _from_eur_base(j["rates"]), j.get("time_last_update_utc", "")


def _live_frankfurter():
    syms = ",".join(c for c in CURRENCY_CODES if c != "CNY")
    url = ("https://api.frankfurter.dev/v1/latest?base=EUR&symbols=" + syms)
    r = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    j = r.json()
    rates = j["rates"]
    rates["EUR"] = 1.0
    return _from_eur_base(rates), j.get("date", "")


def get_live_rates(force=False):
    """实时市场汇率（主源失败走备用，再走缓存/兜底）。"""
    cache = _load_cache()
    cached = cache.get("live")

    if not force:
        try:
            rates, updated = _live_erapi()
            rec = {"rates": rates, "date": updated,
                   "source": "open.er-api.com",
                   "fetched_at": datetime.now().isoformat(timespec="seconds")}
            cache["live"] = rec
            _save_cache(cache)
            return dict(rec, from_cache=False, stale=False)
        except Exception:
            pass
        try:
            rates, updated = _live_frankfurter()
            rec = {"rates": rates, "date": updated,
                   "source": "Frankfurter (ECB)",
                   "fetched_at": datetime.now().isoformat(timespec="seconds")}
            cache["live"] = rec
            _save_cache(cache)
            return dict(rec, from_cache=False, stale=False)
        except Exception:
            pass

    if cached and cached.get("rates"):
        return dict(cached, from_cache=True, stale=True)
    return {
        "rates": dict(_FALLBACK_LIVE),
        "date": None,
        "source": "内置参考值",
        "fetched_at": None,
        "from_cache": False,
        "stale": True,
        "fallback": True,
    }


def get_all():
    """供前端一次性获取两套汇率。"""
    return {"customs": get_customs_rates(), "live": get_live_rates(),
            "currencies": CURRENCIES}

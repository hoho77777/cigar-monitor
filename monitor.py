# -*- coding: utf-8 -*-
"""库存监控引擎：抓取层 + 站点适配器 + 通用兜底判断。"""
import re
import json
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT, CF_RETRIES, CF_RETRY_WAIT, NETWORK_RETRIES

try:
    from curl_cffi import requests as cffi_requests
except Exception:  # pragma: no cover
    cffi_requests = None

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,de;q=0.8,fr;q=0.7,zh-CN;q=0.6",
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
}

# 通用兜底关键词（仅用于未知站点，且在页面可见文本上匹配）
OUT_KEYWORDS = [
    "out of stock", "sold out", "out-of-stock", "notify me", "back in stock soon",
    "ausverkauft", "demnächst verfügbar", "nicht vorrätig",
    "rupture de stock", "agotado", "sin stock", "esaurito",
]
IN_KEYWORDS = [
    "add to cart", "in stock", "in-stock", "buy now",
    "in den warenkorb", "ajouter au panier", "en stock", "añadir al carrito", "disponibile",
]

# 已知域名 -> 适配器
DOMAIN_ADAPTERS = {
    "cigars-of-cuba.com": "coc",
    "cigarone.com": "cigarone",
    "c-cigars.de": "shopify",
    "alpscigar.com": "woocommerce",
    "thecigar.com": "prestashop",
}


# ---------------- 抓取层 ----------------
def _fetch_normal(url):
    r = requests.get(url, headers=BROWSER_HEADERS, timeout=REQUEST_TIMEOUT)
    return r.text, r.status_code


def _is_cloudflare_block(status, text):
    low = (text or "").lower()
    if "just a moment" in low or "cf-challenge" in low or "challenge-platform" in low:
        return True
    # Cloudflare 速率限制（429，正文 local_rate_limited）：浏览器指纹可绕过，需降级
    if "local_rate_limited" in low:
        return True
    if status in (403, 503) and "cloudflare" in low:
        return True
    return False


def _fetch_cloudflare(url):
    if cffi_requests is None:
        raise RuntimeError("curl_cffi 未安装，无法访问带 Cloudflare 防护的站点")
    session = cffi_requests.Session(impersonate="safari17_0")
    last_status = None
    for i in range(CF_RETRIES):
        r = session.get(url, timeout=REQUEST_TIMEOUT)
        last_status = r.status_code
        if r.status_code == 200 and "just a moment" not in r.text.lower():
            return r.text, r.status_code
        time.sleep(CF_RETRY_WAIT)
    raise RuntimeError(f"Cloudflare 挑战未通过（最后 HTTP {last_status}）")


# 已知稳定拦截/指纹限流的站点，直接走浏览器指纹，省去一次失败请求
CF_DIRECT_DOMAINS = ("alpscigar.com", "c-cigars.de")

# 网络异常退避（429 不在此重试：单轮零重试，由 app 层站点级退避统一处理）
TRANSIENT_BACKOFF = 4


def _fetch_normal_retry(url):
    """普通抓取。任何 HTTP 响应（含 429）立即返回、单轮只发一次；仅对网络异常少量重试。"""
    last_err = None
    for attempt in range(NETWORK_RETRIES):
        try:
            r = requests.get(url, headers=BROWSER_HEADERS, timeout=REQUEST_TIMEOUT)
            return r.text, r.status_code
        except requests.RequestException as e:
            last_err = e
            if attempt < NETWORK_RETRIES - 1:
                time.sleep(TRANSIENT_BACKOFF)
    raise last_err


def fetch(url):
    domain = urlparse(url).netloc.lower()
    if any(d in domain for d in CF_DIRECT_DOMAINS):
        return _fetch_cloudflare(url)
    try:
        text, code = _fetch_normal_retry(url)
        if not _is_cloudflare_block(code, text):
            return text, code
    except requests.RequestException:
        pass
    # 普通抓取被 Cloudflare 拦截或网络异常，自动降级浏览器指纹
    return _fetch_cloudflare(url)


def fetch_page_title(url):
    """添加监控项时用于自动获取商品名称。"""
    try:
        text, _ = fetch(url)
        soup = BeautifulSoup(text, "html.parser")
        og = soup.find("meta", attrs={"property": "og:title"})
        if og and og.get("content"):
            return re.sub(r"\s+", " ", og["content"]).strip()
        if soup.title and soup.title.get_text(strip=True):
            return re.sub(r"\s+", " ", soup.title.get_text(strip=True)).strip()
    except Exception:
        pass
    return ""


# ---------------- 结构化数据 ----------------
def _map_schema(value):
    v = str(value).lower()
    if "outofstock" in v or "soldout" in v:
        return "out_of_stock"
    if "instock" in v:
        return "in_stock"
    if "preorder" in v or "presale" in v:
        return "out_of_stock"
    return None


def _walk_for_availability(node):
    """递归遍历 JSON-LD，返回第一个 availability 映射结果。"""
    if isinstance(node, dict):
        if "availability" in node:
            mapped = _map_schema(node["availability"])
            if mapped:
                return mapped
        for v in node.values():
            found = _walk_for_availability(v)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _walk_for_availability(item)
            if found:
                return found
    return None


def _loads_lenient(raw):
    """宽松解析 JSON-LD：允许字符串内控制字符；仍失败则转义控制字符兜底。"""
    try:
        return json.loads(raw, strict=False)
    except Exception:
        cleaned = re.sub(r"[\x00-\x1f]", lambda m: "\\u%04x" % ord(m.group()), raw)
        return json.loads(cleaned, strict=False)


def check_jsonld(soup):
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = _loads_lenient(tag.string or "")
        except Exception:
            continue
        mapped = _walk_for_availability(data)
        if mapped:
            return mapped
    return None


# ---------------- 站点适配器 ----------------
def _check_coc(soup):
    block = soup.select_one("li.stock-availability")
    if block:
        text = re.sub(r"\s+", " ", block.get_text(" ", strip=True))
        low = text.lower()
        if "out of stock" in low:
            return "out_of_stock", text
        if "in stock" in low:
            return "in_stock", text
    meta = soup.select_one('meta[itemprop="availability"]')
    if meta and meta.get("content"):
        mapped = _map_schema(meta["content"])
        if mapped:
            return mapped, meta["content"].strip()
    return None, "未找到库存标记"


def _check_cigarone(soup):
    btns = soup.select("button.add-to-cart")
    if not btns:
        return None, "未找到加购按钮"
    if all(b.has_attr("disabled") for b in btns):
        return "out_of_stock", f"{len(btns)} 个加购按钮均为禁用状态"
    return "in_stock", "加购按钮可点击"


def _check_woocommerce(soup):
    stock = soup.select_one("p.stock")
    if stock:
        classes = stock.get("class", [])
        text = re.sub(r"\s+", " ", stock.get_text(" ", strip=True))
        if "out-of-stock" in classes:
            return "out_of_stock", text
        if "in-stock" in classes:
            return "in_stock", text
    mapped = check_jsonld(soup)
    if mapped:
        return mapped, "JSON-LD 结构化数据"
    return None, "未找到库存标记"


def _check_prestashop(soup):
    # 该类站点 JSON-LD 可能不准，以缺货元素和加购按钮为准
    if soup.select_one(".product-out-of-stock"):
        return "out_of_stock", "商品缺货标记（product-out-of-stock）"
    btn = soup.select_one("button.add-to-cart")
    if btn:
        btn_text = re.sub(r"\s+", " ", btn.get_text(" ", strip=True)).lower()
        if btn.has_attr("disabled") or "out of stock" in btn_text:
            return "out_of_stock", "加购按钮禁用 / 显示 Out of stock"
        return "in_stock", "加购按钮可点击"
    if soup.select_one(".product-add-to-cart"):
        return "in_stock", "商品可加购"
    return None, "未找到库存标记"


def _check_shopify(soup):
    """Shopify 站点（如 c-cigars.de）：JSON-LD 优先，加购按钮兜底。"""
    # 1. JSON-LD 结构化数据
    mapped = check_jsonld(soup)
    if mapped:
        return mapped, "JSON-LD 结构化数据"

    # 2. 产品表单的加购按钮：disabled / Ausverkauft 即缺货
    form = soup.select_one('form[action*="/cart/add"]')
    if form:
        btn = form.select_one("button, input[type=submit]")
        if btn is not None:
            btxt = re.sub(r"\s+", " ", btn.get_text(" ", strip=True)).lower()
            if btn.has_attr("disabled") or "ausverkauft" in btxt or "sold out" in btxt:
                label = btxt.strip() or "禁用"
                return "out_of_stock", f"加购按钮禁用/缺货（{label}）"
            return "in_stock", "加购按钮可点击"

    # 3. 可见文本兜底（多语言缺货词）
    visible = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).lower()
    for kw in ("ausverkauft", "nicht vorrätig", "sold out", "out of stock"):
        if kw in visible:
            return "out_of_stock", f"关键词“{kw}”"
    return None, "未找到库存标记"


def _split_keywords(raw):
    return [x.strip().lower() for x in re.split(r"[;,，；\n]+", raw or "") if x.strip()]


def _check_generic(soup, product):
    # 1. 优先 JSON-LD
    mapped = check_jsonld(soup)
    if mapped:
        return mapped, "JSON-LD 结构化数据"

    visible = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).lower()

    # 2. 自定义关键词
    for kw in _split_keywords(product.get("out_keywords")):
        if kw in visible:
            return "out_of_stock", f"自定义缺货词“{kw}”"
    for kw in _split_keywords(product.get("in_keywords")):
        if kw in visible:
            return "in_stock", f"自定义有货词“{kw}”"

    # 3. 内置多语言关键词（缺货词优先）
    for kw in OUT_KEYWORDS:
        if kw in visible:
            return "out_of_stock", f"关键词“{kw}”"
    for kw in IN_KEYWORDS:
        if kw in visible:
            return "in_stock", f"关键词“{kw}”"
    return None, "页面无可用库存标记，建议配置自定义关键词"


def pick_adapter(product):
    adapter = product.get("adapter") or "auto"
    if adapter != "auto":
        return adapter
    domain = urlparse(product["url"]).netloc.lower().replace("www.", "")
    for d, a in DOMAIN_ADAPTERS.items():
        if domain.endswith(d):
            return a
    return "generic"


def check_product(product):
    """返回 (status, detail, http_code)；status: in_stock/out_of_stock/unknown。"""
    text, code = fetch(product["url"])
    soup = BeautifulSoup(text, "html.parser")
    adapter = pick_adapter(product)

    if adapter == "coc":
        status, detail = _check_coc(soup)
    elif adapter == "cigarone":
        status, detail = _check_cigarone(soup)
    elif adapter == "woocommerce":
        status, detail = _check_woocommerce(soup)
    elif adapter == "prestashop":
        status, detail = _check_prestashop(soup)
    elif adapter == "shopify":
        status, detail = _check_shopify(soup)
    elif adapter == "jsonld":
        status = check_jsonld(soup)
        detail = "JSON-LD 结构化数据" if status else "JSON-LD 中无库存信息"
    else:
        status, detail = _check_generic(soup, product)

    return status or "unknown", detail, code

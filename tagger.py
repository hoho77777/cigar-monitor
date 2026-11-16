# -*- coding: utf-8 -*-
"""自动识别商品标签：从名称+网址提取品牌、型号。

标签由系统自动识别、只读，用于前端筛选；不改变任何监控数据。
规格/产地/数量等词汇仅用于过滤，不产生标签。
"""
import re

import brands

# 品牌（按需扩充；多词品牌如 Sancho Panza 由 brands.EN_CANONICAL 归一）
BRANDS = {
    "punch", "sancho", "panza", "cohiba", "montecristo", "romeo", "julieta",
    "bolivar", "partagas", "trinidad", "hoyo", "monterrey", "quintero",
    "vegas", "robaina", "cuaba", "diplomaticos", "juan", "lopez", "rafael",
    "gonzalez", "cristobal", "rey", "davidoff", "camacho",
    "padron", "arturo", "fuente", "macanudo", "upmann", "larranaga",
    "veguero",
}
# 产地（仅过滤，不产生标签）
ORIGINS = {
    "cuba", "cuban", "cubain", "cubains", "cubano", "cubanos",
    "habano", "habanos",
}
# 规格 / 包装 / 尺寸（仅过滤，不产生标签）
SPECS = {
    "tube", "tubes", "tubo", "tubos", "box", "stick", "sticks", "pack",
    "packs", "case", "cabinet", "petit", "corona", "robusto", "torpedo",
    "churchill", "mareva", "gordito", "regio", "regios", "natural", "maduro",
    "grande", "doble", "at",
}
# 停用：电商/站点/连接词
STOPWORDS = {
    "cigar", "cigars", "cig", "buy", "shop", "store", "online", "of", "the",
    "a", "t", "p", "regular", "production", "productions", "product",
    "products", "www", "com", "net", "org", "html", "http", "https", "and",
    "for", "with", "to", "in", "on", "item", "del", "de", "la", "el", "le",
    "les", "des", "du", "un", "une", "et", "en", "das", "der", "die", "und",
    "cigares", "cubaines", "cigarone", "ccigars", "alps", "alpscigar", "lcdh",
    "kitts", "world", "cigarsworld", "thecigar", "cigarshopworld", "casa",
    "st", "saint",
}


def _stem(word):
    if len(word) > 3 and word.endswith("s"):
        return word[:-1]
    return word


def _tokens(text):
    text = re.sub(r"a\s*/\s*t|a\s*-\s*t", " at ", text, flags=re.IGNORECASE)
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


def extract_tags(name, url):
    """返回分类标签 dict：brand/line（去重有序列表）。"""
    buckets = {"brand": [], "line": []}
    seen = set()

    def add(cat, val):
        if val and val not in seen:
            seen.add(val)
            buckets[cat].append(val)

    for raw in _tokens(f"{name} {url}"):
        if any(c.isdigit() for c in raw):
            continue  # 数量/编号/年份一律不产生标签
        if len(raw) < 2:
            continue
        stem = _stem(raw)
        if raw in STOPWORDS or stem in STOPWORDS:
            continue
        if stem in ORIGINS or stem in SPECS or raw in SPECS:
            continue  # 产地/规格仅过滤
        if stem in BRANDS:
            add("brand", brands.canonical_brand(stem))
        else:
            add("line", stem.capitalize())

    return buckets


def flat_tags(tag_buckets):
    """扁平标签（用于筛选展示），按 品牌/型号 顺序。"""
    return [t for k in ("brand", "line") for t in tag_buckets[k]]

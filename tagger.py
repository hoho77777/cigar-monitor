# -*- coding: utf-8 -*-
"""自动识别商品标签：从名称+网址提取品牌、型号。

标签由系统自动识别、只读，用于前端筛选；不改变任何监控数据。
规格/产地/数量等词汇仅用于过滤，不产生标签。

识别规则：
- 先做 Unicode 重音规范化（ñ→n、ü→u、é→e 等），再分词；
- 品牌匹配同时尝试原词与复数剥 s 词干，原词优先；
- 网址（URL）的词只贡献品牌，不产生型号标签，避免域名/店铺碎片污染型号；
- 多语言电商通用词、营销词在 STOPWORDS 中统一过滤。
"""
import re
import unicodedata

import brands

# 品牌词干由 brands.BRAND_ZH / EN_CANONICAL 自动派生，单一数据源。
# 想支持新品牌，只需在 brands.py 的 BRAND_ZH 里加一行中文对照。
BRANDS = brands.brand_stems()
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
# 停用：电商/站点/连接词 + 多语言营销词与店铺碎片
STOPWORDS = {
    # 英文电商/连接词
    "cigar", "cigars", "cig", "buy", "shop", "store", "online", "of", "the",
    "a", "t", "p", "regular", "production", "productions", "product",
    "products", "www", "com", "net", "org", "html", "http", "https", "and",
    "for", "with", "to", "in", "on", "item", "del", "de", "la", "el", "le",
    "les", "des", "du", "un", "une", "et", "en", "das", "der", "die", "und",
    "cigares", "cubaines", "cigarone", "ccigars", "alps", "alpscigar", "lcdh",
    "kitts", "world", "cigarsworld", "thecigar", "cigarshopworld", "st",
    # 英文营销/通用词
    "brand", "certified", "made", "top", "house", "luxury", "premium",
    "note", "boutique", "passion", "request", "many", "too", "vip", "or",
    "casa",
    # 德语电商通用词
    "zigarre", "zigarren", "kaufen", "tabak", "kontor", "hier",
    # 法语电商通用词
    "haut", "gamme", "medaille", "couronne",
    # 常见店铺/域名碎片
    "vipcigar", "falkum", "cigarpassion", "cigarpassio", "topcuban",
    "sa", "ch",
}


def _normalize(text):
    """Unicode 重音规范化：NFD 分解后去掉组合重音符号。

    Mañanitas -> mananitas；Zigarren/Défaut 等多语言词也能统一到基础字母。
    """
    return "".join(ch for ch in unicodedata.normalize("NFD", str(text))
                   if not unicodedata.combining(ch))


def _stem(word):
    if len(word) > 3 and word.endswith("s"):
        return word[:-1]
    return word


def _tokens(text):
    # 规格 "A/T" 归一为 at；加单词边界，避免把 "cubana-turquinos" 里的
    # "a-t" 误当成 A/T 拆开（会造出 Urquino 这类垃圾型号词）
    text = _normalize(text)
    text = re.sub(r"(?<![a-z])a\s*(?:/|-)\s*t(?![a-z])", " at ", text, flags=re.IGNORECASE)
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


def _classify(raw):
    """把一个词分类：('brand', 规范名) | ('line', 型号词) | None(过滤)。"""
    if len(raw) < 2:
        return None
    if any(c.isdigit() for c in raw):
        return None  # 数量/编号/年份一律不产生标签
    stem = _stem(raw)
    if raw in STOPWORDS or stem in STOPWORDS:
        return None
    if stem in ORIGINS or raw in ORIGINS or stem in SPECS or raw in SPECS:
        return None  # 产地/规格仅过滤
    if raw in brands.AMBIGUOUS_STEMS or stem in brands.AMBIGUOUS_STEMS:
        return None  # 多品牌共用的词（如 flor）无法判定，不产生标签
    # 品牌：原词优先（brands 同时保留原词与剥 s 词干），再试剥 s 词干
    if raw in BRANDS:
        return ("brand", brands.canonical_brand(raw))
    if stem in BRANDS:
        return ("brand", brands.canonical_brand(stem))
    return ("line", stem.capitalize())


def extract_tags(name, url):
    """返回分类标签 dict：brand/line（去重有序列表）。"""
    buckets = {"brand": [], "line": []}
    seen = set()

    def add(cat, val):
        if val and val not in seen:
            seen.add(val)
            buckets[cat].append(val)

    # URL 的词只贡献品牌：域名/店铺碎片不进型号标签
    for raw in _tokens(url):
        r = _classify(raw)
        if r and r[0] == "brand":
            add("brand", r[1])

    # 商品名的词贡献品牌 + 型号
    for raw in _tokens(name):
        r = _classify(raw)
        if r:
            add(r[0], r[1])

    # 冲突消解：同时命中 Saint Luis Rey 与 El Rey del Mundo 时，
    # luis/saint 是 Saint Luis Rey 的专属强特征，rey 仅为弱特征，归前者。
    if "Saint Luis Rey" in buckets["brand"] and "El Rey del Mundo" in buckets["brand"]:
        buckets["brand"].remove("El Rey del Mundo")
        seen.discard("El Rey del Mundo")

    return buckets


def flat_tags(tag_buckets):
    """扁平标签（用于筛选展示），按 品牌/型号 顺序。"""
    return [t for k in ("brand", "line") for t in tag_buckets[k]]

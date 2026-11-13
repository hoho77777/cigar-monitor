# -*- coding: utf-8 -*-
"""雪茄品牌中英文对照词库（单一数据源）。

规则：
- 规范英文名（EN）对应中文简称与中文全称；
- 搜索时，英文规范名、中文简称、中文全称都能命中同一品牌；
- 筛选标签上英文后只附「中文简称」。

数据来源：Habanos S.A. 官方品牌体系（古巴 Habanos 全部品牌）
与主要非古（非古巴）品牌。规范英文名统一采用无重音拼写，
便于自动识别与中英文匹配。

新增品牌只需在 BRAND_ZH 里加一行；识别用的英文词干会自动派生，
不必再维护第二份清单。
"""
import re

# 规范英文名 -> (中文简称, 中文全称)
BRAND_ZH = {
    # ---- 古巴 · 全球品牌 ----
    "Cohiba": ("高希霸", "高希霸"),
    "Partagas": ("帕特加斯", "帕特加斯"),
    "Romeo y Julieta": ("罗密欧", "罗密欧与朱丽叶"),
    "Montecristo": ("蒙特", "蒙特克里斯托"),
    "Hoyo de Monterrey": ("好友", "好友蒙特利"),
    "H. Upmann": ("乌普曼", "乌普曼"),
    "Jose L. Piedra": ("比亚达", "比雅达"),
    # ---- 古巴 · 多地区品牌 ----
    "Bolivar": ("玻利瓦尔", "玻利瓦尔"),
    "Punch": ("潘趣", "潘趣"),
    "Vegas Robaina": ("罗宾纳", "维加斯罗宾纳"),
    "Quintero": ("金特罗", "君特欧"),
    "Fonseca": ("丰塞卡", "丰塞卡"),
    # ---- 古巴 · 利基品牌 ----
    "Cuaba": ("库阿巴", "库阿巴"),
    "Trinidad": ("千里达", "特立尼达"),
    "San Cristobal de La Habana": ("圣克里斯托", "圣克里斯托瓦尔"),
    # ---- 古巴 · 本地品牌 ----
    "Diplomaticos": ("外交官", "外交官"),
    "Sancho Panza": ("桑丘", "桑丘潘沙"),
    "Flor de Rafael Gonzalez": ("冈萨雷斯", "拉斐尔冈萨雷斯"),
    "La Gloria Cubana": ("古巴荣耀", "古巴荣耀"),
    "El Rey del Mundo": ("世界之王", "世界之王"),
    "Flor de Cano": ("卡诺", "卡诺之花"),
    "Los Statos de Luxe": ("斯塔托斯", "斯塔托斯"),
    "Troya": ("特罗亚", "特罗亚"),
    "Vegueros": ("威古洛", "威古洛"),
    "Por Larranaga": ("拉尼加拉", "波拉尼加拉"),
    "Quai d'Orsay": ("多尔赛", "多塞尔码头"),
    "Juan Lopez": ("洛佩斯", "胡安洛佩斯"),
    "Ramon Allones": ("阿隆斯", "雷蒙阿隆斯"),
    "Saint Luis Rey": ("圣路易斯", "圣路易斯雷"),
    # ---- 非古巴品牌 ----
    "Davidoff": ("大卫杜夫", "大卫杜夫"),
    "Camacho": ("卡马乔", "卡马乔"),
    "Padron": ("帕德龙", "帕德龙"),
    "Arturo Fuente": ("富恩特", "阿图罗富恩特"),
    "Macanudo": ("马卡努多", "马卡努多"),
}

# 英文词干（小写）-> 规范英文名，用于把自动识别结果归一到词库。
# 多词品牌的各个组成词干都指向同一规范名，由标签去重逻辑合并。
EN_CANONICAL = {
    # 单词品牌
    "cohiba": "Cohiba",
    "partagas": "Partagas",
    "montecristo": "Montecristo",
    "bolivar": "Bolivar",
    "trinidad": "Trinidad",
    "punch": "Punch",
    "quintero": "Quintero",
    "fonseca": "Fonseca",
    "cuaba": "Cuaba",
    "diplomaticos": "Diplomaticos",
    "davidoff": "Davidoff",
    "camacho": "Camacho",
    "padron": "Padron",
    "macanudo": "Macanudo",
    "veguero": "Vegueros",
    "troya": "Troya",
    # 多词品牌
    "sancho": "Sancho Panza",
    "panza": "Sancho Panza",
    "romeo": "Romeo y Julieta",
    "julieta": "Romeo y Julieta",
    "hoyo": "Hoyo de Monterrey",
    "monterrey": "Hoyo de Monterrey",
    "vegas": "Vegas Robaina",
    "robaina": "Vegas Robaina",
    "arturo": "Arturo Fuente",
    "fuente": "Arturo Fuente",
    "upmann": "H. Upmann",
    "larranaga": "Por Larranaga",
    "cristobal": "San Cristobal de La Habana",
    "juan": "Juan Lopez",
    "lopez": "Juan Lopez",
    "rafael": "Flor de Rafael Gonzalez",
    "gonzalez": "Flor de Rafael Gonzalez",
    "rey": "El Rey del Mundo",
}


# 品牌名里的虚词/连接词，不参与自动派生（避免 "de / la / del" 变成品牌词干）
_STEM_STOP = {
    "del", "los", "las", "por", "and", "the", "for", "with",
    "von", "van", "sur", "des", "les", "une", "una", "con",
}


def _stems_of(en):
    """把规范英文名拆成可匹配的词干；顺带兼容复数词尾 s。"""
    out = set()
    for w in re.split(r"[^a-z0-9]+", str(en).lower()):
        if not w or len(w) < 3 or w in _STEM_STOP:
            continue
        out.add(w)
        if len(w) > 4 and w.endswith("s"):
            out.add(w[:-1])
    return out


def _derive_stems():
    """由 BRAND_ZH + EN_CANONICAL 生成词干表（单一数据源）。

    被多个品牌共用的词（如 flor 同时属于 Flor de Cano 和
    Flor de Rafael Gonzalez）无法判定归属，标记为歧义词干并忽略，
    避免误把型号词当成品牌。人工映射始终优先。
    """
    owner = {}
    for en in BRAND_ZH:
        for w in _stems_of(en):
            owner.setdefault(w, set()).add(en)
    ambiguous = {w for w, ens in owner.items() if len(ens) > 1} - set(EN_CANONICAL)
    table = dict(EN_CANONICAL)
    for w, ens in owner.items():
        if w not in ambiguous:
            table.setdefault(w, next(iter(ens)))
    return table, ambiguous


STEM_TO_BRAND, AMBIGUOUS_STEMS = _derive_stems()


def brand_stems():
    """所有可识别的品牌词干，供 tagger.extract_tags 使用。"""
    return set(STEM_TO_BRAND)


def canonical_brand(name):
    """把自动识别出的品牌词干/名称归一到规范英文名。

    词库中无明确映射时，回退为首字母大写，保证输出始终是可读品牌名。
    """
    key = str(name or "").strip().lower()
    return STEM_TO_BRAND.get(key, str(name or "").capitalize())


def zh_of(en):
    """返回规范英文名对应的 (中文简称, 中文全称)；词库外为 (None, None)。"""
    return BRAND_ZH.get(str(en), (None, None))


def short_zh(en):
    """仅返回中文简称（标签显示用）；词库外返回 None。"""
    pair = BRAND_ZH.get(str(en))
    return pair[0] if pair else None


def brand_table():
    """供 /api/brands 输出：[{en, short, full}, ...]，按规范英文名排序。"""
    return [
        {"en": en, "short": short, "full": full}
        for en, (short, full) in sorted(BRAND_ZH.items())
    ]

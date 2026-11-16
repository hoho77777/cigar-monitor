# -*- coding: utf-8 -*-
"""雪茄品牌中英文对照词库（单一数据源）。

规则：
- 规范英文名（EN）对应中文简称与中文全称；
- 搜索时，英文规范名、中文简称、中文全称都能命中同一品牌；
- 筛选标签上英文后只附「中文简称」。

数据来源：Habanos S.A. 官方品牌体系（古巴 Habanos 全部品牌）
与主要非古（非古巴）品牌。规范英文名统一采用无重音拼写，
便于自动识别与中英文匹配。
"""

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


def canonical_brand(name):
    """把自动识别出的品牌词干/名称归一到规范英文名。

    词库中无明确映射时，回退为首字母大写，保证输出始终是可读品牌名。
    """
    key = str(name or "").strip().lower()
    return EN_CANONICAL.get(key, str(name).capitalize())


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

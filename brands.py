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
    "Guantanamera": ("关塔那摩", "关塔那摩"),
    # ---- 非古巴 · 多米尼加 ----
    "Davidoff": ("大卫杜夫", "大卫杜夫"),
    "Arturo Fuente": ("富恩特", "阿图罗富恩特"),
    "Ashton": ("阿什顿", "阿什顿"),
    "La Aurora": ("拉奥罗拉", "拉奥罗拉"),
    "Avo": ("阿沃", "阿沃"),
    # ---- 非古巴 · 尼加拉瓜 ----
    "Padron": ("帕德龙", "帕德龙"),
    "Oliva": ("奥利瓦", "奥利瓦"),
    "Drew Estate": ("德鲁庄园", "德鲁庄园"),
    "AJ Fernandez": ("AJ费尔南德斯", "AJ费尔南德斯"),
    "My Father": ("我的父亲", "我的父亲"),
    "Tatuaje": ("塔图阿赫", "塔图阿赫"),
    "Illusione": ("幻觉", "幻觉"),
    "Joya de Nicaragua": ("尼加拉瓜珍宝", "尼加拉瓜珍宝"),
    "Perdomo": ("佩尔多莫", "佩尔多莫"),
    "Foundation": ("基石", "基石"),
    "Dunbarton": ("邓巴顿", "邓巴顿"),
    "HVC": ("HVC", "HVC"),
    "Caldwell": ("考德威尔", "考德威尔"),
    "Crowned Heads": ("皇冠之首", "皇冠之首"),
    "Aging Room": ("陈年之室", "陈年之室"),
    # ---- 非古巴 · 洪都拉斯 / 其他产区 ----
    "Camacho": ("卡马乔", "卡马乔"),
    "Rocky Patel": ("洛基帕特尔", "洛基·帕特尔"),
    "Macanudo": ("马卡努多", "马卡努多"),
    "VegaFina": ("维加菲纳", "维加菲纳"),
    "Quorum": ("阔罗姆", "阔罗姆"),
    "Don Tomas": ("唐托马斯", "唐托马斯"),
    "Gurkha": ("廓尔喀", "廓尔喀"),
    "Villiger": ("维利格", "维利格"),
    "Bering": ("白令", "白令"),
    "Bahia": ("巴伊亚", "巴伊亚"),
    "CAO": ("CAO", "CAO"),
    "Nub": ("努布", "努布"),
    "Alec Bradley": ("亚历克布拉德利", "亚历克·布拉德利"),
    "Carlos Torano": ("卡洛斯托拉诺", "卡洛斯·托拉诺"),
    "Nat Sherman": ("纳特谢尔曼", "纳特·谢尔曼"),
    "La Perla Habana": ("哈瓦那珍珠", "哈瓦那珍珠"),
    "E.P. Carrillo": ("E.P.卡里略", "E.P.卡里略"),
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
    "mundo": "El Rey del Mundo",
    # 古巴新增
    "guantanamera": "Guantanamera",
    "ramon": "Ramon Allones",
    "allones": "Ramon Allones",
    "cano": "Flor de Cano",
    "gloria": "La Gloria Cubana",
    "cubana": "La Gloria Cubana",
    "quai": "Quai d'Orsay",
    "orsay": "Quai d'Orsay",
    "lui": "Saint Luis Rey",
    "luis": "Saint Luis Rey",
    "stato": "Los Statos de Luxe",
    "statos": "Los Statos de Luxe",
    "piedra": "Jose L. Piedra",
    # 非古巴（单/多词）
    "ashton": "Ashton",
    "aurora": "La Aurora",
    "avo": "Avo",
    "oliva": "Oliva",
    "drew": "Drew Estate",
    "fernandez": "AJ Fernandez",
    "father": "My Father",
    "pepin": "My Father",
    "tatuaje": "Tatuaje",
    "illusione": "Illusione",
    "joya": "Joya de Nicaragua",
    "perdomo": "Perdomo",
    "foundation": "Foundation",
    "dunbarton": "Dunbarton",
    "hvc": "HVC",
    "caldwell": "Caldwell",
    "crowned": "Crowned Heads",
    "heads": "Crowned Heads",
    "aging": "Aging Room",
    "room": "Aging Room",
    "patel": "Rocky Patel",
    "rocky": "Rocky Patel",
    "vegafina": "VegaFina",
    "quorum": "Quorum",
    "tomas": "Don Tomas",
    "gurkha": "Gurkha",
    "villiger": "Villiger",
    "bering": "Bering",
    "bahia": "Bahia",
    "cao": "CAO",
    "nub": "Nub",
    "alec": "Alec Bradley",
    "bradley": "Alec Bradley",
    "torano": "Carlos Torano",
    "carlos": "Carlos Torano",
    "sherman": "Nat Sherman",
    "perla": "La Perla Habana",
    "carrillo": "E.P. Carrillo",
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

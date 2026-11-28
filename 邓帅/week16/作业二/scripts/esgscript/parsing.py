"""确定性的字段解析：金额、公告类型、主题与范围、来源分级、采购人类型、地区。

同样的输入必得同样的输出。模型只负责把原文里的写法找出来（如「190万元」），
数字怎么换算、公告算哪一类，由这里的规则决定。
"""

import re
from typing import Any
from urllib.parse import urlparse

TOPICS: tuple[str, ...] = (
    "咨询规划",
    "碳排放核算与核查",
    "报告编制与鉴证",
    "碳资产管理与交易",
    "双碳平台与监测系统",
    "培训认证",
)
"""ESG/双碳专业服务的六类主题，也是范围内招标的主题标签取值。"""

PROVINCES: tuple[str, ...] = (
    "北京",
    "天津",
    "上海",
    "重庆",
    "河北",
    "山西",
    "辽宁",
    "吉林",
    "黑龙江",
    "江苏",
    "浙江",
    "安徽",
    "福建",
    "江西",
    "山东",
    "河南",
    "湖北",
    "湖南",
    "广东",
    "海南",
    "四川",
    "贵州",
    "云南",
    "陕西",
    "甘肃",
    "青海",
    "台湾",
    "内蒙古",
    "广西",
    "西藏",
    "宁夏",
    "新疆",
    "香港",
    "澳门",
)
"""省级行政区的不带后缀写法。"""

PURCHASER_TYPES: tuple[str, ...] = (
    "政府部门",
    "事业单位",
    "国有企业",
    "企业（未区分所有制）",
    "开发区/园区管委会",
    "行业协会与社会组织",
    "其它",
)
"""采购人类型的口径。只凭名称判断，分不清所有制的归到「企业（未区分所有制）」。"""

# ---- 金额 ----

_NUMBER = r"\d+(?:\.\d+)?"
_UNIT_MULTIPLIER = {"亿元": 10**8, "亿": 10**8, "万元": 10**4, "万": 10**4, "元": 1}
_WITH_UNIT = re.compile(rf"({_NUMBER})(亿元|万元|亿|万|元)")
_RANGE = re.compile(rf"{_NUMBER}\s*(?:亿元|万元|亿|万|元)?\s*(?:至|到|~|～|—|--|－|-)\s*{_NUMBER}")
_NOT_AWARD_AMOUNT = re.compile(r"预算|限价|控制价|单价|每人|每家|每份|每单位|以内|以下|费率|折扣")
_UPPER_AMOUNT = re.compile(r"[零壹贰叁肆伍陆柒捌玖拾佰仟萬億万亿]{2,}元[整正]?")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?:\D|$))")

_CN_DIGIT = {"零": 0, "壹": 1, "贰": 2, "叁": 3, "肆": 4, "伍": 5, "陆": 6, "柒": 7, "捌": 8, "玖": 9}
_CN_SMALL = {"拾": 10, "十": 10, "佰": 100, "百": 100, "仟": 1000, "千": 1000}
_CN_BIG = {"万": 10**4, "萬": 10**4, "亿": 10**8, "億": 10**8}


def _halfwidth(text: str) -> str:
    """全角的数字与标点换成半角。"""
    chars = []
    for char in text:
        code = ord(char)
        if 0xFF01 <= code <= 0xFF5E:
            chars.append(chr(code - 0xFEE0))
        elif char == "．":
            chars.append(".")
        else:
            chars.append(char)
    return "".join(chars)


def _chinese_number(text: str) -> float:
    """把大写金额的数字部分换成数值，如「壹佰玖拾万」→ 1900000。"""
    total = 0.0
    section = 0.0
    number = 0.0
    for char in text:
        if char in _CN_DIGIT:
            number = float(_CN_DIGIT[char])
        elif char in _CN_SMALL:
            section += (number or 1) * _CN_SMALL[char]
            number = 0.0
        elif char in _CN_BIG:
            unit = _CN_BIG[char]
            if total >= 10**8:  # 「亿」后面再出现「万」是加，不是再乘
                total += (section + number) * unit
            else:
                total = (total + section + number) * unit
            section = 0.0
            number = 0.0
    return total + section + number


def parse_amount(text: object) -> float | None:
    """把中标金额的原文写法换算成元；换算不出一个确定金额的返回 None。

    认：190万元、1.2亿元、86.5万、1900000元、人民币壹佰玖拾万元整。
    不认：区间（80万元至100万元）、折扣率（按收费标准下浮20%）、预算与限价、单价、两个不同金额并列。
    """
    if not isinstance(text, str):
        return None
    text = _THOUSANDS.sub("", _halfwidth(text))
    for noise in ("人民币", "¥", "￥", "约", "（", "）", "(", ")", "，", ",", "。", " "):
        text = text.replace(noise, "")
    text = re.sub(r"\s+", "", text)
    if not text or _RANGE.search(text) or _NOT_AWARD_AMOUNT.search(text):
        return None
    if upper := _UPPER_AMOUNT.search(text):
        return _chinese_number(upper[0]) or None
    values = [float(number) * _UNIT_MULTIPLIER[unit] for number, unit in _WITH_UNIT.findall(text)]
    if not values and re.search(r"[:：]", text):  # 「中标金额（元）：1900000」：单位写在标签里
        return parse_amount(re.split(r"[:：]", text)[-1])
    if not values:
        return float(text) if re.fullmatch(_NUMBER, text) else None
    return values[0] if len(set(values)) == 1 else None


# ---- 公告类型 ----

_OTHER_MARKERS = ("更正", "变更", "答疑", "澄清", "废标", "终止", "流标", "撤销", "延期")
_AWARD_MARKERS = ("中标", "成交", "中选", "结果")
_TENDER_MARKERS = (
    "招标公告",
    "采购公告",
    "磋商",
    "谈判",
    "询价",
    "单一来源",
    "竞价",
    "反拍",
    "公开招标",
    "邀请招标",
)


def notice_type_of(title: object) -> str:
    """按标题判断公告类型：other（更正、废标等）/ award（中标、成交）/ tender（招标、采购）。"""
    text = title if isinstance(title, str) else ""
    if any(marker in text for marker in _OTHER_MARKERS):
        return "other"
    if any(marker in text for marker in _AWARD_MARKERS):
        return "award"
    if any(marker in text for marker in _TENDER_MARKERS):
        return "tender"
    return "other"


# ---- 主题与范围 ----

_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "咨询规划": (
        "碳达峰",
        "碳中和规划",
        "碳中和路径",
        "路径研究",
        "双碳规划",
        "双碳咨询",
        "低碳规划",
        "应对气候变化",
        "ESG战略",
        "ESG 战略",
        "排放清单编制",
        "温室气体排放清单",
        "碳中和发展规划",
        "气候风险",
    ),
    "碳排放核算与核查": (
        "碳排放核算",
        "碳核查",
        "碳盘查",
        "温室气体",
        "碳核算",
        "碳排放报告",
        "核查服务",
        "碳足迹",
        "排放因子",
    ),
    "报告编制与鉴证": (
        "ESG报告",
        "ESG 报告",
        "可持续发展报告",
        "社会责任报告",
        "ESG披露",
        "ESG信息披露",
        "鉴证",
        "可持续报告",
        "TCFD",
        "ISSB",
        "ESG相关报告",
    ),
    "碳资产管理与交易": ("碳资产", "CCER", "碳交易", "碳配额", "碳汇", "碳金融", "自愿减排"),
    "双碳平台与监测系统": (
        "双碳平台",
        "能碳",
        "碳管理平台",
        "双碳管理",
        "碳排放监测",
        "碳排放智能",
        "智慧双碳",
        "碳云",
        "双碳数字化",
    ),
    "培训认证": ("培训", "认证", "碳排放管理员", "能力建设"),
}
_OUT_KEYWORDS = (
    "工程",
    "施工",
    "设备",
    "仪器",
    "装备",
    "改造",
    "EPC",
    "总承包",
    "光伏",
    "风电",
    "安装",
    "车辆",
    "家具",
    "办公",
    "维修",
    "养护",
    "种植",
    "林木",
)
"""边界外的信号词：工程、货物、设备。出现在标题里时范围要交给模型或人复核。"""


def classify_topic(text: object) -> tuple[str | None, int]:
    """按关键词给一个标题（或标题加摘要）归到六类主题之一；返回 (主题, 命中强度)，都不命中返回 (None, 0)。"""
    source = text if isinstance(text, str) else ""
    best: tuple[str | None, int] = (None, 0)
    for topic, keywords in _TOPIC_KEYWORDS.items():
        hits = [keyword for keyword in keywords if keyword in source]
        if hits and (score := max(len(keyword) for keyword in hits) + len(hits)) > best[1]:
            best = (topic, score)
    return best


def rule_scope(title: object, snippet: object = None) -> dict[str, Any]:
    """按规则判断一条候选公告的主题与范围。

    返回 topic、in_scope 与 needs_review：标题里同时出现专业服务与工程、设备类词的，从保守先算边界外，
    并标记需要复核。
    """
    text = f"{title or ''} {snippet or ''}"
    topic, score = classify_topic(text)
    if topic is None or score == 0:
        return {"topic": None, "in_scope": False, "needs_review": True}
    out_hit = next((keyword for keyword in _OUT_KEYWORDS if keyword in str(title or "")), None)
    if out_hit is not None:
        return {"topic": topic, "in_scope": False, "needs_review": True}
    return {"topic": topic, "in_scope": True, "needs_review": False}


def normalize_topic(topic: object) -> str | None:
    """把模型给的主题标签归到六类之一；归不进去返回 None。"""
    text = str(topic or "").strip()
    if text in TOPICS:
        return text
    guessed, score = classify_topic(text)
    return guessed if score else None


# ---- 来源分级、站点、采购人类型、地区 ----

_TIER1_HOSTS = (
    ".gov.cn",
    ".gov",
    ".edu.cn",
    ".int",
    ".org.cn",
    "sse.com.cn",
    "szse.cn",
    "cninfo.com.cn",
    "hkexnews.hk",
    "ggzy.gov.cn",
    "ccgp.gov.cn",
    "cebpubservice.com",
)
_TIER3_HOSTS = (
    "blog.sina",
    "weibo.com",
    "zhihu.com",
    "toutiao.com",
    "baijiahao.baidu.com",
    "douban.com",
    "csdn.net",
    "163.com/dy/article",
    "sohu.com/a",
    "gzh.",
)
_SITE_NAMES = {
    "ccgp.gov.cn": "中国政府采购网",
    "cebpubservice.com": "中国招标投标公共服务平台",
    "ggzy.gov.cn": "全国公共资源交易平台",
    "chengezhao.com": "诚格招标网",
    "bidchance.com": "中国拟在建项目网",
    "zhaobiao.cn": "招标网",
    "bidcenter.com.cn": "采购与招标网",
}


def _host_of(url: object) -> str:
    try:
        return (urlparse(url if isinstance(url, str) else "").hostname or "").lower()
    except ValueError:
        return ""


def tier_of(url: object) -> int | None:
    """按域名给来源定可信度分级：一级、三级由域名决定；二级与一级分不清的返回 None，交给模型判断。"""
    text = url if isinstance(url, str) else ""
    host = _host_of(text)
    if any(host.endswith(suffix) for suffix in _TIER1_HOSTS):
        return 1
    if any(marker in text for marker in _TIER3_HOSTS):
        return 3
    return None


def source_site_of(url: object) -> str:
    """来源站点的名称：认识的站点用中文名，不认识的用域名。"""
    host = _host_of(url)
    for domain, name in _SITE_NAMES.items():
        if host == domain or host.endswith("." + domain):
            return name
    if "ggzy" in host or "ggzyjy" in host or "zfcg" in host:
        return "公共资源交易平台"
    parts = host.removeprefix("www.").split(".")
    if len(parts) >= 3 and parts[-2] in ("com", "gov", "org", "net", "edu") and parts[-1] == "cn":
        return ".".join(parts[-3:])  # com.cn、gov.cn 这类两级后缀
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def purchaser_type_of(name: object) -> str:
    """按采购人名称归类。只凭名称判断，分不清所有制的记为「企业（未区分所有制）」。"""
    text = name if isinstance(name, str) else ""
    if not text.strip():
        return "其它"
    zones = ("管委会", "开发区", "园区", "新区", "高新区", "经开区", "产业园", "示范区", "自贸区")
    societies = ("协会", "学会", "商会", "基金会", "联合会", "促进会", "联盟", "商会")
    companies = ("公司", "集团", "厂", "银行", "合作社", "事务所")
    state_cues = (
        "国资",
        "国投",
        "城投",
        "交投",
        "产投",
        "水投",
        "建投",
        "文旅",
        "交通",
        "公交",
        "地铁",
        "水务",
        "能源",
        "电力",
        "石化",
        "石油",
        "港口",
        "机场",
        "铁路",
        "建设",
        "投资",
    )
    if any(word in text for word in zones):
        return "开发区/园区管委会"
    if any(word in text for word in societies):
        return "行业协会与社会组织"
    if any(word in text for word in companies):
        return "国有企业" if any(cue in text for cue in state_cues) else "企业（未区分所有制）"
    if any(
        word in text
        for word in (
            "局",
            "委员会",
            "政府",
            "办公厅",
            "办公室",
            "厅",
            "部",
            "街道",
            "乡镇",
            "监察",
            "总队",
            "支队",
        )
    ):
        return "政府部门"
    if any(
        word in text
        for word in ("中心", "站", "馆", "院", "学校", "大学", "学院", "医院", "研究所", "图书馆", "气象")
    ):
        return "事业单位"
    return "其它"


def region_of(*texts: object) -> str | None:
    """从采购人名称与正文里找省级行政区；找不到返回 None。"""
    for text in texts:
        source = text if isinstance(text, str) else ""
        if found := next((name for name in PROVINCES if name in source), None):
            return found
    return None

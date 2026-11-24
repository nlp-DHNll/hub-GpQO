"""归一化与字段抽取。

这里的每个函数都必须是确定性的：同样的输入永远得到同样的输出。
凡是需要语义判断的部分（赛道归类、摘要）都不放在本文件。

关键约定
--------
- 金额统一用 ``Decimal`` 表示「元」，字符串化后写 JSON，避免浮点误差。
- 每个字段都返回 ``Field(value, quote, confidence)``：value 是抽取值，
  quote 是原文片段，confidence ∈ {high, mid, low, none}。这是 README
  §11.2「字段双列」的实现基础——报告里两者并排展示。
- 抽不到就返回 ``None``，由上层统一写成 ``N/A``。**绝不用估算值填充。**
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

# ------------------------------------------------------------------ 字符归一化
_FULLWIDTH_OFFSET = 0xFEE0

_TRAD2SIMP = str.maketrans(
    {
        "項": "项", "標": "标", "價": "价", "額": "额", "預": "预", "報": "报",
        "購": "购", "單": "单", "資": "资", "產": "产", "與": "与", "電": "电",
        "業": "业", "務": "务", "環": "环", "評": "评", "級": "级", "證": "证",
        "鑑": "鉴", "編": "编", "諮": "咨", "詢": "询", "計": "计", "劃": "划",
        "機": "机", "構": "构", "團": "团", "國": "国", "際": "际", "綠": "绿",
        "節": "节", "溫": "温", "氣": "气", "體": "体", "減": "减", "縣": "县",
        "區": "区", "廳": "厅", "辦": "办", "處": "处", "網": "网", "徵": "征",
        "費": "费", "採": "采", "開": "开", "關": "关", "為": "为", "時": "时",
        "間": "间", "長": "长", "問": "问", "題": "题", "醫": "医", "農": "农",
        "財": "财", "稅": "税", "銀": "银", "險": "险", "債": "债", "貸": "贷",
        "審": "审", "認": "认", "檢": "检", "測": "测", "試": "试", "驗": "验",
        "萬": "万", "億": "亿", "壹": "壹", "貳": "贰", "參": "叁", "肆": "肆",
    }
)

# 标题里的噪声前后缀：转载/转发标记、公告类型后缀。不归一化会导致同一项目
# 在不同平台被判成两条（README §11.1）。后缀按长度从长到短排列，循环剥离。
_NOISE_PREFIXES = ("转载", "转发", "重新招标", "变更公告", "招标公告", "中标公告", "结果公告", "公告")
_NOISE_SUFFIXES = (
    "竞争性磋商", "竞争性谈判",
    "招标公告", "中标公告", "结果公告", "变更公告", "成交公告",
    "成交结果", "中标结果",
    "竞争性", "结果", "成交", "中标",
    "磋商", "询价", "比选", "遴选", "谈判", "采购", "招标", "公告", "公示",
)


def to_halfwidth(text: str) -> str:
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - _FULLWIDTH_OFFSET))
        else:
            out.append(ch)
    return "".join(out)


def norm_title(title: str) -> str:
    """标题归一化：去 HTML 实体、全半角、繁简、噪声前后缀、标点与空白。"""
    text = html.unescape(title or "")
    text = to_halfwidth(text).translate(_TRAD2SIMP)
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", text)

    for _ in range(4):  # 防止「【转载】【招标】XX…招标公告」这类多重前后缀
        before = text
        for prefix in _NOISE_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix) :]
        for suffix in _NOISE_SUFFIXES:
            if text.endswith(suffix):
                text = text[: -len(suffix)]
        if text == before:
            break
    return text.lower()


# ------------------------------------------------------------------ 标题清洗
# 检索结果的标题几乎都带站点尾巴（「-宁夏招标网」「_凤凰网」「| 镇江市住建局」）
# 和公告类型前缀（「【招标公告】」）。这些直接进报告会显得很不专业，更重要的是
# 它们会污染去重指纹：同一份内容被三个站点转载，标题各不相同，指纹就各不相同。
_BRACKET_NOISE = re.compile(r"【[^】]{1,14}】|\[[^\]\n]{1,14}\]")
# 标题尾部粘的项目编号（「…碳资产管理服务项目编号:DH-2026-CG-210」），
# 编号本身已由 parse_project_no 抽到 fields 里，不该重复出现在项目名中
_INLINE_NOISE = re.compile(r"(?:项目|采购|招标|标段|包)?编号\s*[:：]\s*[^\s，,。；;]{2,40}$")

# 只用于判断「分隔符右边是不是站点名」，因此可以比关键词表宽松
_SITE_TOKENS = (
    "招标网", "采购网", "标讯", "招投标", "公共服务平台", "公共资源", "官网",
    "网站", "平台", "门户", "协会", "交易所", "资讯", "频道", "首页", "公示",
    "日报", "网",
    # 发布机关名：真实标题常见「…的公示 | 镇江市住房和城乡建设局」，
    # 这类尾巴是站点/发布方，不是项目名的一部分。
    "局", "委员会", "政府", "中心", "厅",
)
_SEP_CHARS = "-_|｜—–"


def clean_title(title: str) -> str:
    """去掉标题里的站点尾巴与类型前缀，得到可展示、可做指纹的干净标题。

    只在「分隔符右侧像站点名」（含 ``_SITE_TOKENS`` 且不超过 24 字）时才截断，
    避免把「关于XX-YY项目的公告」这种正常连字符串切坏。
    """
    text = re.sub(r"\s+", " ", html.unescape(title or "")).strip()
    previous = None
    while previous != text:  # 「-四川招投标网-官网-…」这类多重尾巴
        previous = text
        text = _BRACKET_NOISE.sub("", text).strip()
        text = _INLINE_NOISE.sub("", text).strip(" -_|｜—–·,，.。")
        cut = -1
        for index in range(len(text) - 1, -1, -1):
            if text[index] not in _SEP_CHARS:
                continue
            tail = text[index + 1 :].strip()
            if tail and len(tail) <= 24 and any(token in tail for token in _SITE_TOKENS):
                cut = index
                break
        if cut > 0:
            text = text[:cut].strip()
    return text.strip(" -_|｜—–·,，.。")


def norm_buyer(name: str) -> str:
    """采购方归一化：去括号注记、去公司后缀。"""
    text = to_halfwidth(name or "").translate(_TRAD2SIMP)
    text = re.sub(r"[（(][^）)]{0,20}[）)]", "", text)
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", text)
    # 后缀按「长优先」排列：股份有限公司 必须先于 有限公司 匹配，
    # 否则「…集团有限公司」会被 集团有限公司 整段吃掉、丢掉「集团」二字。
    text = re.sub(r"(股份有限公司|有限责任公司|有限公司|公司)$", "", text)
    return text


def norm_project_no(no: str) -> str:
    """项目编号归一化：去空格与各类连字符，统一大写。"""
    text = to_halfwidth(no or "").upper()
    return re.sub(r"[\s\-—－_/·]", "", text)


# ------------------------------------------------------------------ 公告阶段
# 阶段判断用**原始标题**，不先 clean_title：清洗会剥掉「【中标公告】」这类
# 括号前缀，而那恰恰是唯一的阶段信号。但原始标题里同时混着站点打的体裁标签
# （「【招标结果】」）和站点尾巴（「-山西招标网」），必须先单独处理这两层，
# 否则「【招标结果】…成交候选人公示-山西招标网」会因为标签里的「招标」二字
# 被判成「招标」——已经成交的项目看起来还能投，这是商机清单里最贵的错。
STAGE_LABELS = {
    "tender": "招标",
    "award": "中标成交",
    "change": "变更/澄清",
    "other": "其他",
}

_STAGE_LABEL_RE = re.compile(r"[【\[]([^】\]]{1,12})[】\]]")

# 站点自己打的体裁标签。顺序 change → award → tender：「【招标结果更正】」是
# 变更而不是结果。标签里只出现「招标」二字的分类（招标信用 / 招标问答）不是
# 公告体裁，所以这里只认「招标公告」这类完整词，不认裸「招标」。
_STAGE_LABEL_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("change", ("变更", "更正", "澄清", "答疑", "延期", "废标", "流标", "终止", "取消")),
    ("award", ("中标", "成交", "结果", "中选", "合同")),
    (
        "tender",
        ("招标公告", "采购公告", "磋商", "谈判", "询价", "询比", "比选", "遴选", "资格预审"),
    ),
)

# 站点名里的「招标网」「标讯」不是阶段信号。先把它们摘掉再匹配，
# 否则「…-中国招标网」这种尾巴会把中标公告判成招标公告。
_STAGE_SITE_TOKENS = (
    "招标投标网", "招投标网", "招标采购网", "招标网", "采购网", "标讯", "公共服务平台",
)

# 顺序即优先级：先认「中标候选人公示」（同时含「公示」和「候选人」），
# 再认变更，最后才是招标。否则「中标公告」会被「公告」所在的招标组先吃掉。
_STAGE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "award",
        (
            "中标结果", "中标公告", "中标公示", "中标候选人", "成交结果", "成交公告",
            "成交公示", "成交候选人", "中选结果", "中选公告", "中选候选人",
            "结果公告", "结果公示", "合同公告",
        ),
    ),
    (
        "change",
        ("变更公告", "更正公告", "澄清", "答疑", "延期", "废标", "流标", "终止公告", "取消公告"),
    ),
    (
        "tender",
        (
            "招标公告", "采购公告", "竞争性磋商", "竞争性谈判", "磋商公告", "谈判公告",
            "询价公告", "询比", "比选", "遴选", "资格预审", "公开招标", "邀请招标",
            # 裸「采购 / 询价 / 招标」放最后：真实标题里大量是「…咨询服务采购」，
            # 不带「公告」二字，不认就会全落到「其他」，阶段统计失去意义。
            # 「征集」同理：「公开征集…核查机构」是实打实的采购动作。
            "采购", "询价", "比价", "招标", "征集",
        ),
    ),
)


def parse_stage(title: str) -> dict[str, str]:
    """判断公告处于哪个阶段：招标 / 中标成交 / 变更 / 其他。

    做「商机」时这个字段比金额还关键：中标公告意味着这条机会已经结束，
    招标公告才是可投的。没有阶段标注时，读者会把 747 条历史清单当成 747 个
    在招项目。
    """
    text = html.unescape(title or "")

    # 1) 括号标签优先。真实标题形如：
    #    「【招标结果】山西天脊潞安…成交候选人公示-山西招标网」
    #    标签说「招标结果」（已结束），正文说「成交候选人公示」，两者都指向
    #    award；只有把标签里的「招标」当阶段才会误判成 tender。
    labels = _STAGE_LABEL_RE.findall(text)
    for code, keywords in _STAGE_LABEL_RULES:
        for keyword in keywords:
            if any(keyword in label for label in labels):
                return {"code": code, "label": STAGE_LABELS[code], "rule": f"标签:{keyword}"}

    # 2) 正文判定：剥掉所有括号标签（「【招标信用】」这类不是体裁信号）
    #    与站点名，再按 award → change → tender 匹配。
    text = _STAGE_LABEL_RE.sub(" ", text)
    for token in _STAGE_SITE_TOKENS:
        text = text.replace(token, "")
    for code, keywords in _STAGE_RULES:
        for keyword in keywords:
            if keyword in text:
                return {"code": code, "label": STAGE_LABELS[code], "rule": keyword}
    return {"code": "other", "label": STAGE_LABELS["other"], "rule": ""}


# ------------------------------------------------------------------ 中文数字
_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "壹": 1, "二": 2, "贰": 2, "貳": 2, "两": 2,
    "三": 3, "叁": 3, "參": 3, "四": 4, "肆": 4, "五": 5, "伍": 5, "六": 6,
    "陆": 6, "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9,
}
_CN_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
_CN_BIG = {"万": 10000, "萬": 10000, "亿": 100000000, "億": 100000000}


def cn_to_int(text: str) -> int | None:
    """解析中文数字，如「壹佰贰拾万」→ 1200000。无法解析返回 None。"""
    if not text:
        return None
    total = 0
    section = 0
    number = 0
    for ch in text:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            section += (number or 1) * _CN_UNITS[ch]
            number = 0
        elif ch in _CN_BIG:
            section += number
            total += (section or 1) * _CN_BIG[ch]
            section = 0
            number = 0
        else:
            return None
    return total + section + number


# ------------------------------------------------------------------ 字段容器
@dataclass(slots=True)
class Field:
    value: str | None
    quote: str = ""
    confidence: str = "none"

    def as_dict(self) -> dict[str, str | None]:
        return {"value": self.value, "quote": self.quote, "confidence": self.confidence}

    def __bool__(self) -> bool:
        return self.value is not None


_QUOTE_BOUNDARY = " 。；;|｜\n　"


def _quote(text: str, start: int, end: int, pad: int = 30) -> str:
    """截取原文片段，并对齐到分句边界。

    直接按字符数前后各取 N 个会从词中间切开（「026-1102。采购人…」），看起来
    像数据损坏。这里向左缩到匹配区间之前最近的分句符之后、向右扩到匹配区间
    之后最近的分句符之前。**匹配区间本身永远不会被裁掉**。
    """
    left = max(0, start - pad)
    right = min(len(text), end + pad)
    snippet = text[left:right]
    match_start = start - left
    match_end = end - left

    if left > 0:
        positions = [
            i for i, ch in enumerate(snippet)
            if ch in _QUOTE_BOUNDARY and i < match_start
        ]
        if positions:
            cut = max(positions) + 1
            snippet = snippet[cut:]
            match_start -= cut
            match_end -= cut

    if right < len(text):
        positions = [
            i for i, ch in enumerate(snippet)
            if ch in _QUOTE_BOUNDARY and i >= match_end
        ]
        if positions:
            snippet = snippet[: min(positions) + 1]

    return re.sub(r"\s+", " ", snippet).strip()


# ------------------------------------------------------------------ 金额
_UNIT_FACTOR = {
    "亿元": Decimal(10**8),
    "亿": Decimal(10**8),
    "万元": Decimal(10**4),
    "万": Decimal(10**4),
    "元": Decimal(1),
}

_AMOUNT_ANCHOR = re.compile(
    r"(?P<kw>预算金额|采购预算|项目预算|最高限价|拦标价|控制价|中标金额|成交金额|合同金额|金额)"
    r"\s*(?:为|是)?\s*[：:]?\s*(?:人民币)?\s*"
    r"(?P<num>\d[\d,，]*(?:\.\d+)?)\s*(?P<unit>亿元|亿|万元|万|元)"
)

# 裸「金额」前面的这些词说明它属于融资行为，不是项目预算。
# 两年窗口实测：三峡绿色中期票据的「合规申购金额 684,000 万元」被当成中标金额，
# 直接把「金额合计」推到 68 亿。锚点里必须排除这类前缀。
_NON_BUDGET_PREFIX = (
    "申购",
    "发行",
    "注册",
    "募集",
    "投资",
    "授信",
    "兑付",
    "担保",
    "交易",
    "充值",
    "结算",
    "授信额度",
    "持仓",
)

_CN_AMOUNT_ANCHOR = re.compile(
    r"(?P<kw>预算金额|采购预算|项目预算|最高限价|成交金额|金额)"
    r"\s*(?:为|是)?\s*[：:]?\s*(?:人民币)?\s*"
    r"(?P<cn>[零〇一二三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟萬億]{2,12})\s*元"
)

_AMOUNT_GENERIC = re.compile(r"(?P<num>\d[\d,，]*(?:\.\d+)?)\s*(?P<unit>亿元|亿|万元|万|元)")

_MONEY_HINT = ("预算", "限价", "控制价", "拦标价", "金额", "报价", "中标", "成交")

# 单价 / 费率语境：碳配额「¥118万元/吨」、电价「0.45元/度」都不是项目预算。
# 实测踩过：某条中标公告标题写「碳配额¥118万元/吨」，被当成了 118 万元预算。
_UNIT_PRICE = re.compile(
    r"(?:/|每)\s*(?:吨|年|月|季|天|日|小时|平方米|平米|立方米|方|度|千瓦时|kwh|mwh|"
    r"台|套|人|次|件|户|亩|公顷|万人|户)",
    re.I,
)

# 单条采购金额上限。早期取 1000 亿，只挡得住「行业总额」「债券规模」这种量级，
# 挡不住「84.92 亿累计成交额」「60 亿绿色债券发行」「279 亿平台建设」——两年窗口
# 里这 5 条就把「金额合计」推到 432 亿，而中位数只有 35.5 万。ESG / 双碳的
# 咨询与服务类采购极少超过 2 亿，绿色园区基建这类工程包能到 3 亿，取 20 亿兜住。
_AMOUNT_CEILING = Decimal("2e9")


def _to_decimal(num_text: str, unit: str) -> Decimal | None:
    try:
        value = Decimal(num_text.replace(",", "").replace("，", ""))
    except (InvalidOperation, ValueError):
        return None
    return value * _UNIT_FACTOR[unit]


def _context(norm: str, start: int, end: int, pad: int = 10) -> str:
    """匹配点附近的上下文，用来判断「这个数字是不是预算」。"""
    return norm[max(0, start - pad) : min(len(norm), end + pad)]


def parse_amount(text: str) -> Field | None:
    """抽取金额，统一折算为「元」。**只认能确认是金额的数字。**

    真实检索暴露的问题：早期版本对所有「数字+单位」兜底，于是研报里的债券规模
    （163.48 亿）、碳配额单价（118 万元/吨）、行业总额（1273.7 亿）全被当成项目
    预算，报告里出现一堆量级离谱的金额。改动如下：

    - 锚点命中（预算金额／最高限价／中标金额…）→ ``high``
    - 无锚点但上下文含预算类提示词、且不是单价 → ``mid``
    - 其余一律返回 ``None``（宁缺勿错）。低于此版本的 ``low`` 已取消。
    """
    raw = text or ""
    # 繁体公告（港台 / 部分行业站）同样要能抽：只做 to_halfwidth 时
    # 「採購預算金額為 1200 萬元」一个锚点都匹配不上。translate 是逐字映射，
    # 长度不变，所以后面用 match 的偏移回原文取 quote 仍然对得上。
    norm = to_halfwidth(raw).translate(_TRAD2SIMP)

    for match in _AMOUNT_ANCHOR.finditer(norm):
        # 「申购金额」「发行金额」这类前缀下的裸「金额」不算预算，跳到下一个候选
        if match.group("kw") == "金额" and any(
            norm[: match.start()].rstrip().endswith(prefix)
            for prefix in _NON_BUDGET_PREFIX
        ):
            continue
        amount = _to_decimal(match.group("num"), match.group("unit"))
        if amount is not None and 0 < amount < _AMOUNT_CEILING:
            return Field(
                value=str(amount.quantize(Decimal("0.01"))),
                quote=_quote(raw, match.start(), match.end()),
                confidence="high",
            )

    match = _CN_AMOUNT_ANCHOR.search(norm)
    if match:
        number = cn_to_int(match.group("cn"))
        if number and 0 < number < _AMOUNT_CEILING:
            return Field(
                value=str(Decimal(number).quantize(Decimal("0.01"))),
                quote=_quote(raw, match.start(), match.end()),
                confidence="high",
            )

    for match in _AMOUNT_GENERIC.finditer(norm):
        amount = _to_decimal(match.group("num"), match.group("unit"))
        if amount is None or not 0 < amount < _AMOUNT_CEILING:
            continue
        # 数字紧跟「申购金额」「发行总额」这类融资口径时同样不算预算：
        # 锚点循环已跳过，但兜底路径还会把它捡回来。
        head = norm[max(0, match.start() - 10) : match.start()]
        if any(f"{prefix}{suffix}" in head for prefix in _NON_BUDGET_PREFIX for suffix in ("金额", "总额", "规模")):
            continue
        context = _context(norm, match.start(), match.end())
        if _UNIT_PRICE.search(context):
            continue
        if not any(hint in context for hint in _MONEY_HINT):
            continue
        return Field(
            value=str(amount.quantize(Decimal("0.01"))),
            quote=_quote(raw, match.start(), match.end()),
            confidence="mid",
        )
    return None


# ------------------------------------------------------------------ 日期
_DATE_ANCHOR = re.compile(
    r"(?P<kw>投标截止时间|投标文件递交截止时间|响应文件提交截止时间|递交投标文件截止时间|"
    r"报价截止时间|报名截止时间|开标时间|截止日期|截止时间|递交截止)"
    r"\s*(?:为|是)?\s*[：:]?\s*"
    r"(?P<date>\d{4}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2}\s*日?)"
)
_ANY_DATE = re.compile(r"(?P<date>\d{4}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2}\s*日?)")


def _to_iso(raw: str) -> str | None:
    parts = re.findall(r"\d+", raw or "")
    if len(parts) < 3:
        return None
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2])).isoformat()
    except ValueError:
        return None


def parse_deadline(text: str) -> Field | None:
    """抽取投标/报价截止日期。**只认带锚点的日期。**

    早期版本对裸日期兜底（标记 low），结果真实数据里 24/25 条都有「截止日期」，
    而且清一色等于发布日期——兜底命中的是正文里随手一个日期。错误的截止日期比
    没有更糟：用户会照着它准备投标。因此取消兜底，抽不到就是 ``N/A``。
    """
    raw = text or ""
    norm = to_halfwidth(raw)

    match = _DATE_ANCHOR.search(norm)
    if match:
        iso = _to_iso(match.group("date"))
        if iso:
            return Field(value=iso, quote=_quote(raw, match.start(), match.end()), confidence="high")
    return None


# ------------------------------------------------------------------ 采购方 / 编号
_BUYER_ANCHOR = re.compile(
    r"(?:采购人名称|采购人|采购单位|招标人|招标单位|建设单位|业主单位)"
    r"\s*[：:]\s*(?P<name>[^\s，,；;。:：|、]{2,40})"
)
_BUYER_NOISE = ("地址", "联系人", "联系电话", "电话", "邮编", "代理机构")

# 真实数据里采购方常被后续正文粘连：「宁夏国运新能源股份有限公司1.3采购」、
# 「浙江省创新投资集团有限公司二」、「中电建长崃(浠水)新材料有限公司1.3采购项目概况」。
# 招投标的采购方一定是法人或机关，所以截到最后一个组织结构后缀为止。
_ORG_SUFFIX = (
    "股份有限公司", "有限责任公司", "集团有限公司", "有限公司", "分公司", "公司",
    "集团", "研究院", "设计院", "学院", "大学", "医院", "事务所",
    "委员会", "管理局", "管理委员会", "办公室", "管理处", "中心", "政府",
    "银行", "局", "厅", "部", "委员会",
)

# 打码或占位形式的采购方（「山东×」「XX公司」）不可用
_BUYER_PLACEHOLDER = re.compile(r"[×*]|(?i:xx)|某某")


def _trim_org(name: str) -> str:
    """截到最右的组织后缀结尾，丢掉后面粘连的段落号/正文。"""
    end = 0
    for suffix in _ORG_SUFFIX:
        index = name.rfind(suffix)
        if index >= 0:
            end = max(end, index + len(suffix))
    return name[:end] if end > 0 else name


def parse_buyer(text: str) -> Field | None:
    raw = text or ""
    norm = to_halfwidth(raw)
    match = _BUYER_ANCHOR.search(norm)
    if not match:
        return None
    name = match.group("name")
    for noise in _BUYER_NOISE:
        if noise in name:
            name = name.split(noise)[0]
    name = _trim_org(name).strip(" 　,，.。")
    if len(name) < 4 or _BUYER_PLACEHOLDER.search(name):
        return None
    return Field(value=name, quote=_quote(raw, match.start(), match.end()), confidence="high")


_NO_ANCHOR = re.compile(
    r"(?:项目编号|招标编号|采购编号|采购计划编号|项目编码|标段编号|招标项目编号)"
    r"\s*[：:]\s*(?P<no>[A-Za-z0-9\-—－_/\[\]()（）]{4,40})"
)


def parse_project_no(text: str) -> Field | None:
    raw = text or ""
    norm = to_halfwidth(raw)
    match = _NO_ANCHOR.search(norm)
    if not match:
        return None
    no = match.group("no").strip("()（）[]")
    if not any(ch.isdigit() for ch in no):
        return None
    return Field(value=no, quote=_quote(raw, match.start(), match.end()), confidence="high")


# ------------------------------------------------------------------ 金额分档
def amount_bucket(amount: Decimal | None, buckets: list[dict]) -> str:
    """落在哪个金额档。左闭右开，最后一档无上界。"""
    if amount is None:
        return "N/A"
    for bucket in buckets:
        low = Decimal(str(bucket["min"]))
        high = bucket.get("max")
        if high is None:
            if amount >= low:
                return str(bucket["label"])
        elif low <= amount < Decimal(str(high)):
            return str(bucket["label"])
    return "N/A"

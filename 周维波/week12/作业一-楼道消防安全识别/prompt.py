# -*- coding: utf-8 -*-
"""提示词与模型输出解析：楼道消防安全风险识别（对应课程作业要求）"""

SYSTEM_PROMPT = (
    "你是一名专业的消防安全检查员，负责检查楼道等公共区域的消防安全隐患。"
    "你的判断必须严格、客观、准确，只依据图片中能看到的内容。"
)

TASK_PROMPT = """请判断这张图片：
1. 是否为楼道（楼梯间、走廊、过道等公共区域）场景？
2. 若是楼道，是否存在消防安全隐患，危险程度如何？

风险等级定义：
- 高风险：楼道中出现电动车、电瓶、飞线充电等可能起火的元素。
- 中风险：楼道中存在大量堆积物严重影响通行，或堆放大量纸箱、木质家具等能造成火势蔓延的堵塞物。
- 低风险：存在楼道堆物现象但不严重。
- 无风险：楼道干净，无堆放物品。
- 非楼道：与楼道无关的图片（如户外街道、室内房间、商场等场景）。

要求：只输出一个 JSON 对象，不要输出解释或其他任何文字，格式如下：
{"category": "高风险|中风险|低风险|无风险|非楼道", "reason": "不超过60字的判断依据，说明图片中的关键元素"}"""

# 演示模式（未配置密钥 / 前端选择演示模式时使用）
MOCK_RESULT = (
    "中风险",
    "【演示模式】图片中楼道拐角可见大量纸箱与杂物堆积，已明显影响通行，"
    "纸箱属于可燃物，存在火势蔓延隐患（未调用真实模型，配置密钥后可实测）。",
)

_CATEGORY_ALIASES = {
    "高风险": "高风险", "高危": "高风险", "高": "高风险", "危": "高风险",
    "危险": "高风险", "danger": "高风险",
    "中风险": "中风险", "中等风险": "中风险", "中危": "中风险", "中": "中风险",
    "medium": "中风险",
    "低风险": "低风险", "低危": "低风险", "轻微": "低风险", "低": "低风险",
    "low": "低风险",
    "无风险": "无风险", "无隐患": "无风险", "无危险": "无风险", "无": "无风险",
    "none": "无风险",
    "非楼道": "非楼道", "不是楼道": "非楼道", "非": "非楼道", "无关": "非楼道",
}

_VALID = {"高风险", "中风险", "低风险", "无风险", "非楼道"}


def normalize_category(raw: str) -> str:
    """把模型输出的各种写法归一为五档标准类别"""
    text = (raw or "").strip().replace(" ", "").replace("\n", "")
    if text in _VALID:
        return text
    if text in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[text]
    # 子串兜底：先按标准类别，再按别名（长词优先，避免"不是楼道"与"非楼道"错位）
    for key in list(_VALID) + sorted(_CATEGORY_ALIASES, key=len, reverse=True):
        if key in text:
            return _CATEGORY_ALIASES.get(key, key)
    raise ValueError(f"无法识别的风险类别: {raw!r}")


def parse_response(text: str) -> tuple[str, str]:
    """从模型输出中提取 {category, reason}，返回 (category, reason)"""
    t = (text or "").strip()
    # 去掉可能的 ```json 代码块围栏
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
        t = t.strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1 or end <= start:
        # 无 JSON 时按关键词直接抽取（兜底）
        category = normalize_category(t)
        reason = t.replace(category, "").strip(" ,:：。")
        return category, reason[:120]
    import json
    try:
        obj = json.loads(t[start:end + 1])
    except Exception:
        # 非严格 JSON 时，尝试直接按关键词抽取
        category = normalize_category(t)
        reason = t.replace(category, "").strip(" ,:：。")
        return category, reason[:120]
    if not isinstance(obj, dict):
        raise ValueError("模型输出不是 JSON 对象")
    category_raw = obj.get("category") or obj.get("风险等级") or obj.get("level") or ""
    reason = (
        obj.get("reason") or obj.get("依据") or obj.get("说明")
        or obj.get("原因") or obj.get("analysis") or ""
    )
    return normalize_category(str(category_raw)), str(reason).strip()

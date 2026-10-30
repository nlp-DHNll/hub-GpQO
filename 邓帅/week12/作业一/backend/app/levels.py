"""五级风险枚举与归一化映射(纯逻辑,无外部依赖,单测主战场)。

归一化策略(T5):清洗收尾符后按有序别名表做子串匹配,首个命中即返回。
顺序规则:特异长的词在前(非楼道/无X 系先于 高/中/低,中等风险先于中风险),
保证"该楼道无风险"命中 none 而非其他。此表即归一化的单一事实源。
"""
from typing import Literal

Level = Literal["high", "medium", "low", "none", "not_corridor"]

# 有序别名表:按序做子串匹配,首个命中即返回
ALIASES: list[tuple[str, Level]] = [
    ("非楼道", "not_corridor"),
    ("无隐患", "none"),
    ("无风险", "none"),
    ("无堆物", "none"),
    ("干净",   "none"),
    ("高风险", "high"),
    ("中等风险", "medium"),
    ("中风险", "medium"),
    ("低风险", "low"),
]


def normalize(raw: str) -> Level | None:
    """模型原始输出 → 五枚举之一;无法映射返回 None(走解析失败路径 S6)。"""
    text = raw.strip().strip("\"'“”·。！! ")   # 去首尾空白与常见收尾符
    for alias, level in ALIASES:
        if alias in text:
            return level
    return None

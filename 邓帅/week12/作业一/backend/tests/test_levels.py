"""归一化全分支用例(技术设计 §4.2 四组)。"""
import pytest

from app.levels import normalize


# 1. 五个枚举词原样输出 → 各自 level
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("高风险", "high"),
        ("中风险", "medium"),
        ("低风险", "low"),
        ("无风险", "none"),
        ("非楼道", "not_corridor"),
    ],
)
def test_exact_enum_words(raw, expected):
    assert normalize(raw) == expected


# 2. PRD §2.1 列名变体词
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("无隐患", "none"),
        ("无堆物", "none"),
        ("干净", "none"),
        ("中等风险", "medium"),
    ],
)
def test_variant_words(raw, expected):
    assert normalize(raw) == expected


# 3. 带收尾符/前后缀仍命中(有序表保证"无风险"先于"风险"类误命中)
@pytest.mark.parametrize(
    "raw, expected",
    [
        ('"高风险。', "high"),
        ("风险等级：低风险", "low"),
        ("该楼道无风险", "none"),
        (" 中风险 ", "medium"),
    ],
)
def test_with_wrappers(raw, expected):
    assert normalize(raw) == expected


# 4. 不可映射 → None(走解析失败路径)
@pytest.mark.parametrize(
    "raw",
    ["这个楼道很危险", "无法判断", "", "maybe fire"],
)
def test_unmappable(raw):
    assert normalize(raw) is None

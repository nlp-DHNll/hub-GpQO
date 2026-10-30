"""LLM 输出的容错解析工具。

模型输出永远是不可控的（多余的解释、markdown 代码块、布尔写成字符串……），
所以在进入控制流之前，一律先归一化，避免“解析失败就当通过”这类事故。
"""

import json
import re
from typing import Any


def parse_json(text: str) -> dict:
    """容错解析 LLM 返回的 JSON（自动剥离 ```json 代码块等噪声）。"""
    if not text:
        return {}
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.S)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # 再尝试从文本中截取第一个 {...}
        m = re.search(r"\{.*\}", cleaned, flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return {}
        return {}


def extract_sql(text: str) -> str:
    """从 LLM 输出中提取纯 SQL 文本（去除 markdown 代码块与前后说明）。"""
    cleaned = (text or "").strip()
    m = re.search(r"```(?:sql)?\s*(.*?)```", cleaned, flags=re.S | re.I)
    if m:
        cleaned = m.group(1).strip()
    cleaned = cleaned.strip("`").strip()
    if cleaned.lower().startswith("sql\n"):
        cleaned = cleaned[4:].strip()
    return cleaned.rstrip(";").strip()


def pick_sql(data: dict, raw: str) -> str:
    """从 LLM 返回中取出 SQL。

    JSON 解析成功时只取 sql 字段（字段为空就返回空串，不能把整段 JSON 当 SQL）；
    解析失败（模型直接输出了裸 SQL）时，才退化为从原始文本中提取。
    """
    if data:
        return extract_sql(str(data.get("sql", "") or ""))
    return extract_sql(raw)


def as_bool(value: Any, default: bool = True) -> bool:
    """把 LLM 返回的布尔字段归一化。

    模型可能输出 "false" / 0 / "否"，直接写 `value is False` 会把它们当成真，
    导致有问题的 SQL 被放行。
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "是", "ok", "通过", "valid"}:
        return True
    if text in {"false", "0", "no", "n", "否", "不通过", "invalid"}:
        return False
    return default


def normalize_tables(value: Any, valid_names: list[str]) -> list[str]:
    """把 LLM 给出的表名列表归一化，并做白名单过滤。

    兼容模型把 tables 写成字符串（如 "tracks, genres"）或带引号、带 schema 前缀的情况。
    """
    if isinstance(value, str):
        candidates: list[Any] = re.split(r"[,\s、]+", value)
    elif isinstance(value, (list, tuple, set)):
        candidates = list(value)
    else:
        candidates = []

    valid = set(valid_names)
    tables: list[str] = []
    for item in candidates:
        name = str(item).strip().strip('"\'`[]')
        # 去掉可能的 schema 前缀，如 main.tracks
        name = name.split(".")[-1].strip()
        if name in valid and name not in tables:
            tables.append(name)
    return tables

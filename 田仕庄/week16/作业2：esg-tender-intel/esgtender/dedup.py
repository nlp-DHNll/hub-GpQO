"""去重：项目编号 → 业务指纹 → 标题相似度（疑似待核实）。

三条硬约束：

1. **空编号不参与比对**。招标公告普遍没有项目编号，若把空串也纳入精确匹配，
   所有无编号记录会互判重复、只剩一条。这是静默失败，必须显式挡住。
2. **指纹带版本号** ``fp_v1``。规则升级后全量重建，不与历史指纹混用。
3. **相似度只做「疑似」**。保留在结果里、打 ``suspect_of`` 标记交人工复核，
   绝不自动合并。

为什么不用 SimHash
------------------
实测在中文短标题上区分度不足（见 tests/test_pipeline.py）：

    真实重复对   汉明距离 7 ~ 16
    碳盘查/碳核查（不同项目）  13

阈值无论取 3 还是 13 都会同时误判。改用 ``difflib`` 编辑相似度后，
重复对落在 0.90 ~ 0.93，不同项目落在 0.889 以下，阈值 0.90 可区分。

代价仍是 O(n²) 次比较，但每次比较在 ``title_ratio_at_least`` 里被两层上界预筛
拦下（长度差、quick_ratio），实测 747 条 2.7s → 0.6s，且结果与全量精确比较
完全一致。若单窗口超过 1 万条，再考虑 SimHash + LSH 分桶。
"""

from __future__ import annotations

import hashlib
from difflib import SequenceMatcher
from typing import Any

FP_VERSION = "fp_v1"
SIMILARITY_THRESHOLD = 0.90

_EMPTY_TOKENS = {"", "n/a", "na", "none", "null", "-"}


def is_blank(value: str | None) -> bool:
    return value is None or str(value).strip().lower() in _EMPTY_TOKENS


def fingerprint(title_norm: str, buyer_norm: str, amount_cny: str | None) -> str:
    """业务指纹：标题 + 采购方 + 金额。任一为空用占位符，保证可复算。"""
    amount = "N/A" if is_blank(amount_cny) else str(amount_cny)
    raw = f"{FP_VERSION}|{title_norm}|{buyer_norm}|{amount}"
    return f"{FP_VERSION}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()}"


def record_id(url: str, title: str) -> str:
    raw = f"{url}|{title}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def title_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return round(SequenceMatcher(None, left, right).ratio(), 3)


def title_ratio_at_least(left: str, right: str, threshold: float) -> float:
    """达到阈值返回相似度，否则返回 0.0。与 ``title_similarity(...) >= threshold`` 等价。

    两层预筛都取自 ``SequenceMatcher.ratio()`` 的**上界**，被跳过的对一定不达标，
    所以是「无损加速」而不是抽样：

    1. 长度上界 ``2*min(la,lb)/(la+lb)``：最长公共子序列不可能长于短串。
    2. ``quick_ratio()``：只统计字符多重集交集，O(n) 级，是 ``ratio()`` 的廉价上界。

    实测 600 条标题两两比较（179,700 对）：6.48s → 1.02s，只有 68 对进入精确计算。
    """
    la, lb = len(left), len(right)
    if not la or not lb:
        return 0.0
    if 2 * min(la, lb) / (la + lb) < threshold:
        return 0.0
    matcher = SequenceMatcher(None, left, right)
    if matcher.quick_ratio() < threshold:
        return 0.0
    score = round(matcher.ratio(), 3)
    return score if score >= threshold else 0.0


_MERGE_FIELDS = ("amount", "deadline", "buyer", "project_no")


def _merge_richer(target: dict[str, Any], source: dict[str, Any]) -> bool:
    """把 ``source`` 里更完整的字段补进 ``target``，返回是否发生补充。

    真实场景：同一项目先发「竞争性谈判公告」（无金额），几周后发「成交结果公告」
    （有成交金额）。归一化后两条指纹相同，若简单丢弃后者，报告里就永远看不到
    中标金额——而那正是市场调研最想看的数据。所以合并：保留先到记录的骨架，
    把后到记录里 target 缺失的字段补上。
    """
    changed = False
    target_fields = target.setdefault("fields", {})
    source_fields = source.get("fields") or {}
    for name in _MERGE_FIELDS:
        current = (target_fields.get(name) or {}).get("value")
        incoming = (source_fields.get(name) or {}).get("value")
        if current or not incoming:
            continue
        target_fields[name] = dict(source_fields[name])
        changed = True
        if name == "amount":
            target_fields["amount_cny"] = source_fields.get("amount_cny")
            target["amount_bucket"] = source.get("amount_bucket")
        if name == "project_no":
            target_fields["project_no_norm"] = source_fields.get("project_no_norm")
    if changed:
        target.setdefault("flags", {}).setdefault("reasons", []).append("merged_fields")
        target.setdefault("source", {}).setdefault("merged_from", []).append(
            (source.get("source") or {}).get("url", "")
        )
    return changed


def deduplicate(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict], list[dict]]:
    """返回 (保留, 被丢弃, 疑似重复对)。输入顺序即优先级，先到先得。"""
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    suspects: list[dict[str, Any]] = []

    seen_no: dict[str, str] = {}  # 归一化编号 -> 保留记录 id
    seen_fp: dict[str, str] = {}  # 指纹 -> 保留记录 id
    by_id: dict[str, dict[str, Any]] = {}

    for record in records:
        fields = record.get("fields") or {}
        no_norm = (fields.get("project_no_norm") or "").strip()
        fp = record.get("fp") or ""

        # 规则 1：编号非空且完全一致
        if not is_blank(no_norm) and no_norm in seen_no:
            record["flags"]["duplicate_of"] = seen_no[no_norm]
            record["flags"]["reasons"].append("project_no")
            _merge_richer(by_id[seen_no[no_norm]], record)
            dropped.append(record)
            continue

        # 规则 2：业务指纹一致
        if fp and fp in seen_fp:
            record["flags"]["duplicate_of"] = seen_fp[fp]
            record["flags"]["reasons"].append("fingerprint")
            _merge_richer(by_id[seen_fp[fp]], record)
            dropped.append(record)
            continue

        # 规则 3：标题高度相似 —— 只标记，不合并
        title_norm = record.get("title_norm") or ""
        track_id = (record.get("track") or {}).get("id")
        for other in kept:
            if (other.get("track") or {}).get("id") != track_id:
                continue
            score = title_ratio_at_least(
                title_norm, other.get("title_norm") or "", SIMILARITY_THRESHOLD
            )
            if score:
                record["flags"]["suspect_of"] = other["id"]
                record["flags"]["reasons"].append(f"title_similarity:{score}")
                other["flags"]["reasons"].append(f"title_similarity:{score}")
                suspects.append(
                    {
                        "a": other["id"],
                        "b": record["id"],
                        "similarity": score,
                        "a_title": other.get("raw", {}).get("title", ""),
                        "b_title": record.get("raw", {}).get("title", ""),
                    }
                )
                break

        if not is_blank(no_norm):
            seen_no[no_norm] = record["id"]
        if fp:
            seen_fp[fp] = record["id"]
        by_id[record["id"]] = record
        kept.append(record)

    return kept, dropped, suspects

"""去重与标题相似度

运行（不需要 pytest）::

    python -m unittest discover -s tests
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from esgtender import (  # noqa: E402
    cli,
    crawl,
    dedup,
    docx_export,
    env,
    extract,
    netguard,
    notify,
    package,
    pipeline,
    presets,
    render,
    search,
    sources,
    store,
    triage,
)


class TestDedup(unittest.TestCase):
    def test_empty_project_no_does_not_collapse(self):
        """两条都无编号的不同项目，不能因为空串相等而被判重复。"""
        records = [
            _record("a", "某市碳盘查服务项目", "甲单位", "100000", None),
            _record("b", "某省碳核查服务项目", "乙单位", "200000", None),
        ]
        kept, dropped, _ = dedup.deduplicate(records)
        self.assertEqual(len(kept), 2)
        self.assertEqual(dropped, [])

    def test_blank_markers_are_ignored(self):
        a = _record("a", "某某碳盘查项目", "甲单位", "100000", None)
        b = _record("b", "另一碳核查项目", "乙单位", "200000", None)
        a["fields"]["project_no_norm"] = "N/A"
        b["fields"]["project_no_norm"] = "n/a"
        kept, dropped, _ = dedup.deduplicate([a, b])
        self.assertEqual(len(kept), 2)
        self.assertEqual(dropped, [])

    def test_same_project_no_is_duplicate(self):
        records = [
            _record("a", "某集团碳盘查服务采购公告", "某集团", "1200000", "NYJT-2026-1101"),
            _record("b", "某集团碳盘查及核算服务招标公告", "某集团", "1200000", "NYJT-2026-1101"),
        ]
        kept, dropped, _ = dedup.deduplicate(records)
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(dropped), 1)
        self.assertEqual(dropped[0]["flags"]["duplicate_of"], "a")

    def test_same_fingerprint_is_duplicate(self):
        records = [
            _record("a", "某市碳盘查服务项目招标公告", "某委", "500000", None),
            _record("b", "某市碳盘查服务项目", "某委", "500000", None),
        ]
        kept, dropped, _ = dedup.deduplicate(records)
        self.assertEqual(len(kept), 1)
        self.assertIn("fingerprint", dropped[0]["flags"]["reasons"])

    def test_similar_title_is_suspect_not_merged(self):
        records = [
            _record("a", "某市重点企业碳盘查服务项目", "某委", "500000", None),
            _record("b", "某市重点企业碳盘查服务项目（二次）", "某委", "520000", None),
        ]
        kept, dropped, suspects = dedup.deduplicate(records)
        self.assertEqual(len(kept), 2, "疑似重复必须保留，不能自动合并")
        self.assertTrue(suspects)

    def test_later_stage_fills_missing_amount(self):
        """同一项目先发招标公告（无金额）、后发成交结果公告（有金额）。
        指纹相同 → 合并为一条，但成交金额必须补进保留记录，不能丢。"""
        tender = _record("a", "某市碳盘查服务项目竞争性谈判公告", "某委", None, None)
        award = _record("b", "某市碳盘查服务项目成交结果公告", "某委", None, None)
        award["fields"]["amount"] = {"value": "860000.00", "quote": "成交金额86万元", "confidence": "high"}
        award["fields"]["amount_cny"] = "860000.00"
        award["amount_bucket"] = "50–100万"

        kept, dropped, _ = dedup.deduplicate([tender, award])

        self.assertEqual(len(kept), 1, "同项目不同阶段应合并为一条")
        self.assertEqual(kept[0]["id"], "a", "保留先到记录")
        self.assertEqual(kept[0]["fields"]["amount_cny"], "860000.00", "成交金额应被补入")
        self.assertEqual(kept[0]["amount_bucket"], "50–100万")
        self.assertIn("merged_fields", kept[0]["flags"]["reasons"])
        self.assertIn("fingerprint", dropped[0]["flags"]["reasons"])


class TestSimilarity(unittest.TestCase):
    def test_near_duplicates_are_flagged(self):
        a = extract.norm_title("某市碳盘查服务项目招标公告")
        b = extract.norm_title("某市碳盘查服务项目采购公告")
        self.assertGreaterEqual(dedup.title_similarity(a, b), dedup.SIMILARITY_THRESHOLD)

    def test_distinct_projects_stay_apart(self):
        """碳盘查 vs 碳核查只差一个字，但它们是不同业务，不能被判成疑似重复。"""
        a = extract.norm_title("某市碳盘查服务项目")
        b = extract.norm_title("某市碳核查服务项目")
        self.assertLess(dedup.title_similarity(a, b), dedup.SIMILARITY_THRESHOLD)

    def test_unrelated_titles_are_far(self):
        a = extract.norm_title("某市碳盘查服务项目")
        b = extract.norm_title("某工业园区绿色工厂申报咨询")
        self.assertLess(dedup.title_similarity(a, b), 0.5)


class TestDedupPrefilter(unittest.TestCase):
    """预筛必须无损：等价于逐对全量精确比较。"""

    def test_equivalence_with_brute_force(self):
        pairs = [
            ("某市碳盘查服务项目招标公告", "某市碳盘查服务项目招标公告"),
            ("某市碳盘查服务项目招标公告", "某市碳核查服务项目中标公告"),
            ("某市碳盘查服务项目招标公告", "某工业园区绿色工厂创建咨询服务采购"),
            ("碳排放核查", "碳核查"),
            ("", "碳核查"),
        ]
        for left, right in pairs:
            expected = dedup.title_similarity(left, right)
            actual = dedup.title_ratio_at_least(left, right, 0.90)
            if expected >= 0.90:
                self.assertEqual(actual, expected, f"{left} / {right}")
            else:
                self.assertEqual(actual, 0.0, f"{left} / {right}")

    def test_length_gap_is_rejected_without_comparing(self):
        """长度差太大时 ratio 上界就够判负，不必构造 SequenceMatcher。"""
        self.assertEqual(dedup.title_ratio_at_least("碳盘查", "碳" * 100, 0.90), 0.0)

    def test_dedup_result_matches_brute_force(self):
        """同一批记录：预筛版与「逐对全量精确比较」的结论必须完全一致。"""
        import copy

        titles = [
            "某市碳盘查服务项目招标公告",
            "某市碳盘查服务项目招标公吿",       # 一字之差 → 疑似
            "某工业园区绿色工厂创建咨询服务采购",
            "某工业园区绿色工厂创建咨询服务",
        ]
        records = [
            {
                "id": f"r{index}",
                "title_norm": title,
                "fp": f"fp{index}",
                "fields": {"project_no_norm": ""},
                "track": {"id": "T5"},
                "raw": {"title": title},
                "flags": {"reasons": []},
            }
            for index, title in enumerate(titles)
        ]
        kept, dropped, suspects = dedup.deduplicate(copy.deepcopy(records))

        def brute(left, right, threshold):
            score = dedup.title_similarity(left, right)
            return score if score >= threshold else 0.0

        with mock.patch.object(dedup, "title_ratio_at_least", side_effect=brute):
            kept2, dropped2, suspects2 = dedup.deduplicate(copy.deepcopy(records))

        self.assertEqual([r["id"] for r in kept], [r["id"] for r in kept2])
        self.assertEqual(len(dropped), len(dropped2))
        self.assertEqual(len(suspects), len(suspects2))
        self.assertGreaterEqual(len(suspects), 1, "用例本身要能触发疑似判定")


def _record(rid: str, title: str, buyer: str, amount: str | None, no: str | None) -> dict:
    title_norm = extract.norm_title(title)
    buyer_norm = extract.norm_buyer(buyer)
    return {
        "id": rid,
        "title_norm": title_norm,
        "fp": dedup.fingerprint(title_norm, buyer_norm, amount),
        "source": {"url": f"https://example.com/{rid}"},
        "raw": {"title": title},
        "fields": {"project_no_norm": extract.norm_project_no(no) if no else None},
        "track": {"id": "T5", "relevance": 0.9},
        "flags": {"duplicate_of": None, "suspect_of": None, "reasons": []},
    }


if __name__ == "__main__":
    unittest.main(verbosity=2)

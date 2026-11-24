"""公告性质闸门与赛道归类

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


SCOPE = {
    "tracks": {
        "core": {
            "T5": {"name": "碳资产", "keywords": ["碳盘查", "碳核查"], "sub": {"碳盘查": ["碳盘查"]}},
            "T4": {"name": "双碳规划", "keywords": ["碳达峰", "碳中和"]},
        },
        "extended": {"绿色工厂园区": ["绿色工厂"]},
        "edge": {
            "require_any": ["碳排放", "碳中和"],
            "also_require_any": ["环评", "环保咨询"],
        },
    },
    "relevance": {
        "threshold": {"core": 0.6, "extended": 0.65, "edge": 0.75},
        "gray_low": 0.2,
        "weights": {"title_base": 0.65, "title_extra": 0.30, "body_bonus": 0.30, "body_saturate": 3},
    },
}


class TestTriage(unittest.TestCase):
    def test_title_hit_accepts(self):
        result = triage.classify("某市碳盘查服务项目采购公告", "采购内容为碳盘查。", SCOPE)
        self.assertEqual(result["group"], "core")
        self.assertEqual(result["id"], "T5")
        self.assertEqual(result["sub"], "碳盘查")
        self.assertEqual(result["decision"], "accept")

    def test_body_only_lands_in_gray(self):
        result = triage.classify(
            "某咨询服务项目采购公告", "服务内容包括碳盘查与碳核查。", SCOPE
        )
        self.assertEqual(result["decision"], triage.DECISION_GRAY)
        self.assertAlmostEqual(result["relevance"], 0.2, places=2)

    def test_body_only_single_hit_drops(self):
        result = triage.classify("某咨询服务项目采购公告", "其中提及碳盘查。", SCOPE)
        self.assertEqual(result["decision"], triage.DECISION_DROP)

    def test_edge_requires_both_groups(self):
        positive = triage.classify(
            "某园区规划环境影响评价及碳排放评价", "开展环评并编制碳排放专章。", SCOPE
        )
        self.assertEqual(positive["group"], "edge")
        self.assertEqual(positive["decision"], "accept")

        negative = triage.classify("某污水处理厂环保咨询采购", "提供环保咨询与验收服务。", SCOPE)
        self.assertEqual(negative["group"], "none")
        self.assertEqual(negative["decision"], triage.DECISION_DROP)

    def test_extended_not_stolen_by_core(self):
        result = triage.classify("某绿色工厂申报咨询项目", "绿色工厂创建辅导。", SCOPE)
        self.assertEqual(result["group"], "extended")

    def test_relevance_spread(self):
        one_hit = triage.classify("某碳盘查项目", "详情见附件。", SCOPE)
        two_hits = triage.classify("某碳盘查项目", "采购碳盘查与碳核查服务。", SCOPE)
        self.assertLess(one_hit["relevance"], two_hits["relevance"])


class TestIntentGate(unittest.TestCase):
    """主题相关 ≠ 采购公告。真实检索里研报、债券上市、协会新闻都会命中
    赛道关键词，必须单独挡住，否则清单里三成内容不是招标。"""

    SCOPE = dict(SCOPE, intent={
        "require_any": ["招标", "采购", "中标", "成交", "公告", "询价"],
        "deny_any": ["研报", "快讯", "清单", "上市", "点评"],
    })

    def test_research_report_rejected(self):
        result = triage.classify(
            "东吴证券:《固收点评:绿色债券周度数据跟踪|研报》-发现报告",
            "绿色债券发行规模 163.48 亿元。",
            self.SCOPE,
        )
        self.assertEqual(result["decision"], triage.DECISION_NOT_TENDER)
        self.assertIn("deny:研报", result["rule"])

    def test_bond_listing_rejected(self):
        result = triage.classify(
            "上交所发布符合《可持续金融共同分类目录》标准的存量绿色债券清单",
            "碳中和债存量规模 1273.7 亿元。",
            self.SCOPE,
        )
        self.assertEqual(result["decision"], triage.DECISION_NOT_TENDER)

    def test_news_flash_rejected(self):
        result = triage.classify(
            "行业快讯 | 国家发展改革委印发《国家碳达峰试点建设方案》",
            "碳达峰试点。",
            self.SCOPE,
        )
        self.assertEqual(result["decision"], triage.DECISION_NOT_TENDER)

    def test_real_tender_passes(self):
        result = triage.classify(
            "某市碳盘查服务项目竞争性磋商公告", "采购碳盘查服务。", self.SCOPE
        )
        self.assertNotEqual(result["decision"], triage.DECISION_NOT_TENDER)
        self.assertEqual(result["group"], "core")

    def test_missing_intent_config_is_permissive(self):
        # 没配 intent 段时应放行，避免配置缺失把全部记录挡掉
        result = triage.classify("某市碳盘查服务项目", "", SCOPE)
        self.assertNotEqual(result["decision"], triage.DECISION_NOT_TENDER)

    def test_real_config_keeps_listed_companies(self):
        """真实配置回归：deny 里曾写「上市」，把「某上市公司ESG报告编制服务采购」
        这类正常招标一起挡掉了——「上市公司」是采购方身份，不是债券上市事件。"""
        import yaml

        scope = yaml.safe_load((SKILL_ROOT / "config" / "scope.yaml").read_text("utf-8"))
        titles = [
            "某国有控股上市公司2026年度ESG报告编制及第三方鉴证服务采购公告",
            "某上市银行ESG评级提升及信息披露优化咨询项目竞争性磋商公告",
        ]
        for title in titles:
            with self.subTest(title=title):
                result = triage.classify(title, "", scope)
                self.assertNotEqual(result["decision"], triage.DECISION_NOT_TENDER)

    def test_real_config_rejects_bond_listing(self):
        import yaml

        scope = yaml.safe_load((SKILL_ROOT / "config" / "scope.yaml").read_text("utf-8"))
        title = "关于某公司碳中和绿色公司债券(第三期)在深圳证券交易所上市有关事项的通知"
        result = triage.classify(title, "", scope)
        self.assertEqual(result["decision"], triage.DECISION_NOT_TENDER)

    def test_real_config_rejects_bond_issuance(self):
        """两年窗口实测：40 条里 12 条是债券发行/付息公告，是最大噪音源。

        这些标题都带「绿色」被赛道关键词命中，但体裁是融资公告；早期 deny 只挡了
        「债券上市」，挡不住「发行完毕 / 发行总额 / 付息」。
        """
        import yaml

        scope = yaml.safe_load((SKILL_ROOT / "config" / "scope.yaml").read_text("utf-8"))
        titles = [
            "重庆银行股份有限公司关于绿色金融债券发行完毕的公告",
            "中国长江三峡集团2024年度第四期绿色中期票据发行总额200,000万元",
            "2026年第十二期中国铁路建设债券(绿色债券)发行办法",
            "某银行绿色金融债券2026年付息公告",
            "某公司碳中和绿色公司债券申购说明",
        ]
        for title in titles:
            with self.subTest(title=title):
                result = triage.classify(title, "", scope)
                self.assertEqual(result["decision"], triage.DECISION_NOT_TENDER)

    def test_real_config_rejects_policy_draft(self):
        """「公开征求意见的公告」有「公告」「实施方案」，但没有任何采购行为。"""
        import yaml

        scope = yaml.safe_load((SKILL_ROOT / "config" / "scope.yaml").read_text("utf-8"))
        result = triage.classify("关于对拟修改《抚顺市碳达峰实施方案》公开征求意见的公告", "", scope)
        self.assertEqual(result["decision"], triage.DECISION_NOT_TENDER)

    def test_real_config_accepts_mainstream_carbon_verification_wording(self):
        """标书里最主流的写法是「碳排放核查」「温室气体排放核查」，不是「碳核查」。

        只配「碳核查」会漏掉一大片真项目（两年窗口实测：成都统一、六安市碳管理
        体系等全部被丢）。这条守住关键词表，别再缩回去。
        """
        import yaml

        scope = yaml.safe_load((SKILL_ROOT / "config" / "scope.yaml").read_text("utf-8"))
        titles = [
            "成都统一碳排放核查服务项目招标公告",
            "六安市建立公司碳管理体系项目招标公告",
            "某市2025年度温室气体排放核查服务采购公告",
        ]
        for title in titles:
            with self.subTest(title=title):
                result = triage.classify(title, "", scope)
                self.assertEqual(result["decision"], triage.DECISION_ACCEPT)
                self.assertEqual(result["group"], "core", "碳核查属于核心·碳资产")

    def test_track_keywords_are_computed_once(self):
        """关键词表按 scope 缓存：逐条重建是白花 CPU。

        2000 条记录 × 上百个关键词，`_track_keywords` 每次重新遍历 + 拼接；
        缓存后同一 scope 只算一次（返回同一个 list 对象即证明走了缓存）。
        """
        import yaml

        scope = yaml.safe_load((SKILL_ROOT / "config" / "scope.yaml").read_text("utf-8"))
        first = triage._track_keywords(scope)
        second = triage._track_keywords(scope)
        self.assertIs(first, second)
        self.assertTrue(first, "关键词表不能为空")
        # 缓存不能影响判断结果
        result = triage.classify("某市碳盘查服务项目招标公告", "", scope)
        self.assertEqual(result["decision"], triage.DECISION_ACCEPT)


if __name__ == "__main__":
    unittest.main(verbosity=2)

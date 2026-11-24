"""字段抽取与归一化

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


class TestChineseNumber(unittest.TestCase):
    def test_financial_numerals(self):
        self.assertEqual(extract.cn_to_int("壹佰贰拾万"), 1200000)
        self.assertEqual(extract.cn_to_int("壹拾捌万"), 180000)
        self.assertEqual(extract.cn_to_int("贰仟伍佰"), 2500)

    def test_plain_numerals(self):
        self.assertEqual(extract.cn_to_int("一百二十万"), 1200000)
        self.assertEqual(extract.cn_to_int("十八"), 18)
        self.assertIsNone(extract.cn_to_int(""))

    def test_garbage_returns_none(self):
        self.assertIsNone(extract.cn_to_int("一百二十abc"))


class TestAmount(unittest.TestCase):
    def test_wan_unit(self):
        field = extract.parse_amount("预算金额：120万元。投标截止时间：2026-12-05")
        self.assertEqual(field.value, "1200000.00")
        self.assertEqual(field.confidence, "high")

    def test_comma_separated_yuan(self):
        field = extract.parse_amount("预算金额：1,200,000.00元")
        self.assertEqual(field.value, "1200000.00")
        self.assertEqual(field.confidence, "high")

    def test_chinese_capitals(self):
        field = extract.parse_amount("预算金额：壹拾捌万元整。报价截止时间：2026年12月01日")
        self.assertEqual(field.value, "180000.00")
        self.assertEqual(field.confidence, "high")

    def test_total_investment_is_not_budget(self):
        # 「项目总投资」不是采购预算。真实数据里这类数字会把金额统计带偏，
        # 且没有预算类提示词，因此不认。
        self.assertIsNone(extract.parse_amount("项目总投资约1.2亿元，其中环保投资占 3%"))

    def test_no_amount(self):
        self.assertIsNone(extract.parse_amount("本次采购不设预算金额限制，详见附件"))

    def test_traditional_chinese_amount(self):
        """繁体公告也要能抽金额。

        `parse_amount` 只做了 to_halfwidth、没走 _TRAD2SIMP，于是
        「採購預算金額為 1200 萬元」一个锚点都匹配不上，整条记录金额 N/A。
        """
        field = extract.parse_amount("採購預算金額為 1200 萬元")
        self.assertIsNotNone(field)
        self.assertEqual(field.value, "12000000.00")
        # 大写繁体数字（壹佰貳拾萬）同样要认：貳 / 參 经 translate 后归一成贰 / 叁
        field = extract.parse_amount("採購預算金額為 壹佰貳拾萬元")
        self.assertIsNotNone(field)
        self.assertEqual(field.value, "1200000.00")

    def test_decimal_precision(self):
        field = extract.parse_amount("最高限价：28.5万元")
        self.assertEqual(field.value, "285000.00")

    def test_unit_price_rejected(self):
        # 真实数据踩过：碳配额「¥118万元/吨」被当成 118 万元项目预算
        self.assertIsNone(extract.parse_amount("北京_碳配额¥118万元/吨I能耗指标和减排采购中标公告"))

    def test_bond_scale_rejected_by_ceiling(self):
        # 绿色债券存量规模 1273.7 亿，不可能是单条采购预算
        self.assertIsNone(extract.parse_amount("存量绿色债券清单，合计12737000万元"))

    def test_financing_amount_rejected(self):
        """融资口径的「金额」不是项目预算。

        两年窗口实测：三峡绿色中期票据的「合规申购金额 684,000 万元」被当成中标
        金额，把报告里的「金额合计」从 68.4 万元推到 68.41 亿元。锚点与兜底两条
        路径都要挡。
        """
        cases = [
            "合规申购家数9家,合规申购金额684,000.00万元,最高申购价位2.90%",
            "本期发行规模200,000万元",
            "本期债券发行总额100,000万元",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(extract.parse_amount(text))

    def test_real_budget_anchor_still_works(self):
        """挡住融资口径不能误伤真预算。"""
        cases = {
            "中标金额 44.8万元": "448000.00",
            "采购预算金额为 550 万元": "5500000.00",
            "合同金额人民币 120 万元": "1200000.00",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(extract.parse_amount(text).value, expected)


class TestDeadline(unittest.TestCase):
    def test_dash_format(self):
        field = extract.parse_deadline("投标截止时间：2026-12-05。")
        self.assertEqual(field.value, "2026-12-05")
        self.assertEqual(field.confidence, "high")

    def test_chinese_format(self):
        field = extract.parse_deadline("开标时间：2026年12月05日。")
        self.assertEqual(field.value, "2026-12-05")

    def test_invalid_date_rejected(self):
        field = extract.parse_deadline("截止时间：2026年13月45日")
        self.assertIsNone(field)

    def test_bare_date_rejected(self):
        # 无锚点的日期不能当截止日期：真实数据里 24/25 条都抽到了「截止」，
        # 但那是发布日期，会让用户按错日期投标。
        self.assertIsNone(extract.parse_deadline("本项目于2026-11-20发布，详见正文。"))


class TestBuyerAndNo(unittest.TestCase):
    def test_buyer_anchor(self):
        field = extract.parse_buyer("采购人：某市发展和改革委员会。预算金额：120万元")
        self.assertEqual(field.value, "某市发展和改革委员会")

    def test_buyer_strips_noise(self):
        field = extract.parse_buyer("采购单位：某县教育局地址：某路1号")
        self.assertEqual(field.value, "某县教育局")

    def test_project_no(self):
        field = extract.parse_project_no("项目编号：ZC-2026-1102。采购人：某委")
        self.assertEqual(field.value, "ZC-2026-1102")
        self.assertEqual(extract.norm_project_no(field.value), "ZC20261102")

    def test_project_no_requires_digit(self):
        self.assertIsNone(extract.parse_project_no("项目编号：见我司公告"))

    def test_buyer_truncated_at_org_suffix(self):
        # 真实数据：采购方被后续正文粘连成「…股份有限公司1.3采购」
        cases = {
            "采购人：宁夏国运新能源股份有限公司1.3采购": "宁夏国运新能源股份有限公司",
            "采购人：浙江省创新投资集团有限公司二": "浙江省创新投资集团有限公司",
            "采购人：中电建长崃(浠水)新材料有限公司1.3采购项目概况": "中电建长崃(浠水)新材料有限公司",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(extract.parse_buyer(text).value, expected)

    def test_buyer_placeholder_rejected(self):
        self.assertIsNone(extract.parse_buyer("采购人：山东×。预算：120万元"))


class TestCleanTitle(unittest.TestCase):
    def test_strips_site_tail(self):
        cases = {
            "【招标公告】碳配额招标公告-宁夏招标网": "碳配额招标公告",
            "上交所发布绿色债券清单_凤凰网": "上交所发布绿色债券清单",
            "关于碳达峰补助项目的公示 | 镇江市住房和城乡建设局": "关于碳达峰补助项目的公示",
            "某市碳盘查服务项目招标公告 - 公告公示": "某市碳盘查服务项目招标公告",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(extract.clean_title(text), expected)

    def test_keeps_legitimate_hyphen(self):
        # 正文里的连字符不能被当站点尾巴切掉
        text = "编制《南充市“十五五”碳达峰行动方案》服务采购项目竞争性谈判公告"
        self.assertEqual(extract.clean_title(text), text)

    def test_same_content_different_sites_collapse(self):
        # 同一内容三站转载：清洗后应得到同一标题，指纹才能对齐
        a = extract.clean_title("上交所发布符合《可持续金融共同分类目录》标准的存量绿色债券清单-海融网")
        b = extract.clean_title("上交所发布符合《可持续金融共同分类目录》标准的存量绿色债券清单_凤凰网")
        self.assertEqual(a, b)


class TestNormalization(unittest.TestCase):
    def test_reprint_prefix_removed(self):
        a = extract.norm_title("【转载】某市碳盘查服务项目招标公告")
        b = extract.norm_title("某市碳盘查服务项目")
        self.assertEqual(a, b)

    def test_fullwidth_and_punctuation(self):
        a = extract.norm_title("某市碳盘查服务项目（重新招标）")
        b = extract.norm_title("某市碳盘查服务项目(重新招标)")
        self.assertEqual(a, b)

    def test_buyer_suffix_normalized(self):
        a = extract.norm_buyer("某省属能源集团有限公司")
        b = extract.norm_buyer("某省属能源集团有限责任公司")
        self.assertEqual(a, b)

    def test_distinct_titles_stay_distinct(self):
        a = extract.norm_title("某市碳盘查服务项目")
        b = extract.norm_title("某市碳核查服务项目")
        self.assertNotEqual(a, b)


class TestAmountBucket(unittest.TestCase):
    BUCKETS = [
        {"label": "<10万", "min": 0, "max": 100000},
        {"label": "10–50万", "min": 100000, "max": 500000},
        {"label": "50–100万", "min": 500000, "max": 1000000},
        {"label": "100–500万", "min": 1000000, "max": 5000000},
        {"label": "≥500万", "min": 5000000, "max": None},
    ]

    def test_boundaries_are_left_closed(self):
        self.assertEqual(extract.amount_bucket(Decimal(100000), self.BUCKETS), "10–50万")
        self.assertEqual(extract.amount_bucket(Decimal(99999), self.BUCKETS), "<10万")
        self.assertEqual(extract.amount_bucket(Decimal(5000000), self.BUCKETS), "≥500万")

    def test_none(self):
        self.assertEqual(extract.amount_bucket(None, self.BUCKETS), "N/A")


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""脚本版的单元测试：一律不打真网络、不调真模型。"""

import json
from datetime import date

import pytest

from esgscript import zhipu
from esgscript.ccgp import parse_results, yearly_chunks
from esgscript.collect import CollectSpec, _is_new, merge_hits, pick_candidates, seen_keys
from esgscript.parsing import (
    normalize_topic,
    notice_type_of,
    parse_amount,
    purchaser_type_of,
    region_of,
    rule_scope,
    source_site_of,
    tier_of,
)
from esgscript.queries import SearchTask
from esgscript.stats import amount_bucket, bid_stats, format_amount, period_of

# ---- 金额 ----


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("190万元", 1900000),
        ("1.2亿元", 120000000),
        ("86.5万", 865000),
        ("1900000元", 1900000),
        ("人民币壹佰玖拾万元整", 1900000),
        ("壹亿贰仟万元整", 120000000),
        ("86.5万元（按收费标准下浮 5%）", 865000),
        ("中标金额（元）：1900000", 1900000),
        ("1,900,000.00元", 1900000),
        ("190万元（小写：1900000元）", 1900000),
        ("按国家收费标准下浮 20%", None),
        ("80万元至100万元", None),
        ("预算金额：120万元", None),
        ("190万元、86万元", None),
        ("5%", None),
        (None, None),
    ],
)
def test_金额的多种写法(text, expected):
    assert parse_amount(text) == expected


def test_金额分档与展示():
    assert amount_bucket(999999) == "100 万元以下"
    assert amount_bucket(1000000) == "100 万（含）至 1000 万元"
    assert amount_bucket(10**7) == "1000 万元（含）以上"
    assert format_amount(1900000) == "190 万元"
    assert format_amount(120000000) == "1.20 亿元"
    assert format_amount(None) == "金额不可得"


def test_日期归到月或季():
    assert period_of("2026-03-05", True) == "2026Q1"
    assert period_of("2026-03-05", False) == "2026-03"
    assert period_of(None, True) is None


# ---- 检索两路的解析 ----


def _sse(payload: dict) -> str:
    return (
        "event:message\ndata:"
        + json.dumps({"jsonrpc": "2.0", "id": 1, "result": payload}, ensure_ascii=False)
        + "\n\n"
    )


def test_智谱响应的双重编码能解出命中列表():
    items = [
        {
            "title": "某公告",
            "link": "http://www.ccgp.gov.cn/a.htm",
            "content": "2026年11月2日 — 摘要",
            "refer": "ref_1",
        }
    ]
    inner = json.dumps(json.dumps(items, ensure_ascii=False), ensure_ascii=False)
    hits = zhipu.decode_hits(_sse({"content": [{"type": "text", "text": inner}], "isError": False}))
    assert [(hit["url"], hit["title"], hit["engine_date"]) for hit in hits] == [
        ("http://www.ccgp.gov.cn/a.htm", "某公告", "2026年11月2日")
    ]


def test_智谱返回错误时抛出运行时错误():
    with pytest.raises(RuntimeError):
        zhipu.decode_hits(_sse({"content": [{"type": "text", "text": "MCP error -429"}], "isError": True}))


_CCGP_PAGE = """
<ul class="vT-srch-result-list-bid">
  <li>
    <a href="http://www.ccgp.gov.cn/cggg/dfgg/zbgg/202611/t20261113_27679546.htm"
      >某区<font color=red>碳排放核算</font>课题报告采购项目中标(成交)结果公告</a>
    <p>一、项目编号：CBNB-1 二、项目名称：……</p>
    <span>2026.11.13 16:41:28 | 采购人：宁波市北仑区发展和改革局 | 代理机构：宁波中基国际招标有限公司
      <br/> <strong> 中标公告 </strong> | 浙江 | <strong> </strong> </span>
  </li>
  <li><a href="javascript:void(0)">没有链接的条目</a></li>
</ul>
"""


def test_政采网搜索页解析():
    hits = parse_results(_CCGP_PAGE)
    assert len(hits) == 1
    assert hits[0]["published_at"] == "2026-11-13"
    assert hits[0]["purchaser"] == "宁波市北仑区发展和改革局"
    assert hits[0]["region"] == "浙江"
    assert hits[0]["notice_label"] == "中标公告"
    assert "碳排放核算" in hits[0]["title"]


def test_超过一年的时间窗按年分段():
    chunks = yearly_chunks(date(2024, 11, 26), date(2026, 11, 26))
    assert len(chunks) == 3  # 24 个月零 1 天：等分成三段，每段都不超过 365 天
    assert chunks[0][0] == date(2024, 11, 26) and chunks[-1][1] == date(2026, 11, 26)
    assert all((last - first).days <= 364 for first, last in chunks)
    starts = [date.fromordinal(prev[1].toordinal() + 1) for prev, _ in zip(chunks, chunks[1:], strict=False)]
    assert starts == [nxt[0] for _, nxt in zip(chunks, chunks[1:], strict=False)]
    assert yearly_chunks(date(2026, 11, 1), date(2026, 11, 26)) == [(date(2026, 11, 1), date(2026, 11, 26))]


def test_搜索引擎的跳转链接被丢弃():
    task = SearchTask(key="k", label="汇总·A", backend="zhipu", text="碳", run=lambda: [])
    cache = {
        "k": {
            "ok": True,
            "hits": [
                {"url": "https://www.google.com/goto?url=abc", "title": "跳转", "snippet": ""},
                {"url": "http://www.ccgp.gov.cn/a.htm", "title": "甲", "snippet": ""},
            ],
        }
    }
    hits = merge_hits(cache, [task])
    assert [hit["title"] for hit in hits] == ["甲"]


def test_同一页面的多次命中合成一条():
    task = SearchTask(key="k", label="汇总·A", backend="ccgp", text="碳", run=lambda: [])
    other = SearchTask(key="k2", label="汇总·B", backend="zhipu", text="碳 中标", run=lambda: [])
    cache = {
        "k": {"ok": True, "hits": [{"url": "http://www.ccgp.gov.cn/a.htm", "title": "甲", "snippet": ""}]},
        "k2": {"ok": True, "hits": [{"url": "http://www.ccgp.gov.cn/a.htm/", "title": "甲", "snippet": ""}]},
    }
    hits = merge_hits(cache, [task, other])
    assert len(hits) == 1
    assert hits[0]["labels"] == ["汇总·A", "汇总·B"]
    assert hits[0]["origins"] == ["ccgp", "zhipu"]
    assert hits[0]["source_site"] == "中国政府采购网"


# ---- 确定性分类 ----


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("某项目中标公告", "award"),
        ("某服务采购项目竞争性磋商公告", "tender"),
        ("中标结果更正公告", "other"),
        ("某单位碳核查服务", "other"),
    ],
)
def test_公告类型按标题判断(title, expected):
    assert notice_type_of(title) == expected


def test_主题与范围的规则():
    assert rule_scope("某市重点企业碳排放核算与核查服务采购项目") == {
        "topic": "碳排放核算与核查",
        "in_scope": True,
        "needs_review": False,
    }
    mixed = rule_scope("某园区碳排放监测系统设备采购安装工程")
    assert mixed["in_scope"] is False
    assert mixed["needs_review"] is True
    assert rule_scope("某办公家具采购")["topic"] is None
    assert normalize_topic("ESG报告编制") == "报告编制与鉴证"
    assert normalize_topic("环保工程") is None


def test_来源分级与站点():
    assert tier_of("https://www.ndrc.gov.cn/x") == 1
    assert tier_of("https://www.sohu.com/a/123") == 3
    assert tier_of("https://finance.sina.com.cn/a") is None  # 一级还是二级，交给模型
    assert source_site_of("http://www.ccgp.gov.cn/a.htm") == "中国政府采购网"
    assert source_site_of("https://finance.sina.com.cn/a") == "sina.com.cn"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("宁波市北仑区发展和改革局", "政府部门"),
        ("某开发区管委会", "开发区/园区管委会"),
        ("国网某省电力有限公司", "国有企业"),
        ("某碳咨询有限公司", "企业（未区分所有制）"),
        ("中国银行业协会", "行业协会与社会组织"),
        (None, "其它"),
    ],
)
def test_采购人类型只凭名称判断(name, expected):
    assert purchaser_type_of(name) == expected


def test_地区从名称或正文里找():
    assert region_of("浙江省宁波市某局") == "浙江"
    assert region_of("", "北京市某区") == "北京"
    assert region_of(None) is None


# ---- 统计 ----


def _record(
    title: str,
    *,
    topic: str,
    in_scope: bool = True,
    kind: str = "award",
    amount: float | None = None,
    published: str | None = None,
    purchaser: str = "某市生态环境局",
    region: str = "北京",
    verification: str = "verified",
) -> dict:
    return {
        "title": title,
        "url": f"http://www.ccgp.gov.cn/{title}.htm",
        "notice_type": kind,
        "published_at": published,
        "purchaser": purchaser,
        "region": region,
        "topic": topic,
        "in_scope": in_scope,
        "amount": amount,
        "amount_text": None,
        "winner": None,
        "source_site": "中国政府采购网",
        "verification": verification,
        "purchaser_type": purchaser_type_of(purchaser),
    }


def test_汇总统计只在范围内的中标公告上做():
    stats = bid_stats(
        [
            _record("甲", topic="碳排放核算与核查", amount=1900000, published="2026-02-05"),
            _record(
                "乙",
                topic="碳资产管理与交易",
                published="2025-09-01",
                purchaser="某开发区管委会",
                region="广东",
            ),
            _record("丙", topic="环保工程", in_scope=False, amount=5000000),
            _record("丁", topic="培训认证", kind="tender"),
            _record("戊", topic="咨询规划", verification="excluded", published="2023-01-01"),
        ]
    )
    assert stats["sample_size"] == 2
    assert stats["in_scope_tender_count"] == 1
    assert stats["out_of_scope_total"] == 1
    assert stats["excluded_total"] == 1
    assert stats["amount_available"] == 1
    assert stats["amount_rate"] == 0.5
    assert [row["topic"] for row in stats["topic_rank"]] == ["碳排放核算与核查", "碳资产管理与交易"]
    assert [row["count"] for row in stats["amount_distribution"]] == [0, 1, 0, 1]
    assert [row["period"] for row in stats["trend"]] == ["2025Q3", "2026Q1"]
    assert stats["purchaser_types"] == {"政府部门": 1, "开发区/园区管委会": 1}


# ---- 监控模式 ----


_MONITOR = CollectSpec(
    case="bid-radar", mode="monitor", window_start=date(2026, 11, 25), window_end=date(2026, 11, 26)
)


def _hit(url: str, published: str | None = None) -> dict:
    return {
        "url": url,
        "title": "某单位碳排放核算服务采购公告",
        "snippet": "",
        "labels": ["监控·碳排放核算与核查"],
        "origins": ["zhipu"],
        "published_at": published,
    }


def test_监控模式初筛掉已见与不晚于基线的候选():
    seen = seen_keys({"records": [{"url": "https://a.gov.cn/x/"}]})
    picked = pick_candidates(
        _MONITOR,
        [
            _hit("http://a.gov.cn/x"),
            _hit("https://b.gov.cn/y", "2026-11-25"),
            _hit("https://c.gov.cn/z", "2026-11-26"),
            _hit("https://d.gov.cn/w"),
        ],
        seen,
    )
    assert [hit["url"] for hit in picked] == ["https://c.gov.cn/z", "https://d.gov.cn/w"]


def test_日报条目的硬条件():
    record = {"notice_type": "tender", "published_at": "2026-11-26", "url": "https://n.gov.cn/1"}
    assert _is_new(_MONITOR, record, set())
    assert not _is_new(_MONITOR, record | {"notice_type": "award"}, set())
    assert not _is_new(_MONITOR, record | {"published_at": "2026-11-25"}, set())
    assert not _is_new(_MONITOR, record, seen_keys({"records": [record]}))

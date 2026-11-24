"""编排：时间窗、趋势、关联、并发、CLI

运行（不需要 pytest）::

    python -m unittest discover -s tests
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

import httpx

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


class TestWindow(unittest.TestCase):
    """--days 必须真的过滤。provider 的 freshness 最细只到 oneYear，
    只靠它会在「近 30 天」的报告里混进一年前的项目。"""

    def test_parse_published_variants(self):
        self.assertEqual(pipeline.parse_published("2026-11-18T11:30:00+08:00"), date(2026, 11, 18))
        self.assertEqual(pipeline.parse_published("2026年11月18日"), date(2026, 11, 18))
        self.assertEqual(pipeline.parse_published("2026/11/18"), date(2026, 11, 18))
        self.assertIsNone(pipeline.parse_published(""))
        self.assertIsNone(pipeline.parse_published("recent"))

    def test_old_records_are_dropped(self):
        today = date.today()
        recent = (today - timedelta(days=5)).isoformat()
        old = (today - timedelta(days=400)).isoformat()
        records = [
            {"source": {"published": recent}},
            {"source": {"published": old}},
            {"source": {"published": ""}},
        ]
        kept, out_of_window, unknown = pipeline.split_by_window(records, 30)
        self.assertEqual(len(kept), 2, "无发布日期的记录应保留，不能静默丢弃")
        self.assertEqual(out_of_window, 1)
        self.assertEqual(unknown, 1)


class TestFreshnessWindows(unittest.TestCase):
    """超过 31 天必须按时间切片检索。

    博查的 freshness 同时改变召回池与排序：单用 oneYear 时 top-50 被年内高相关
    的旧页面占满（实测 --days 90 只剩 7 条，是 --days 30 的严格子集）；整两年
    塞进一段时返回的 50 条稀疏撒在 24 个月里，等于均匀采样。它的 freshness 接受
    ``YYYY-MM-DD..YYYY-MM-DD`` 闭区间，所以正确做法是切段，而不是放大单次范围。
    """

    TODAY = date(2026, 11, 23)

    def test_short_window_uses_single_token(self):
        self.assertEqual(search.freshness_windows_for(30), ["oneMonth"])
        self.assertEqual(search.freshness_windows_for(7), ["oneWeek"])
        self.assertEqual(search.freshness_windows_for(1), ["oneDay"])

    def test_two_years_slices_cover_window_exactly(self):
        windows = search.freshness_windows_for(730, today=self.TODAY)
        self.assertEqual(len(windows), 25, "730 天按 30 天切应得 25 段")
        self.assertEqual(windows[0].split("..")[1], "2026-11-23", "首段必须结束在今天")
        self.assertEqual(windows[-1].split("..")[0], "2024-11-24", "末段必须落在窗口起点")

        span_start = date.fromisoformat(windows[-1].split("..")[0])
        span_end = date.fromisoformat(windows[0].split("..")[1])
        self.assertEqual((span_end - span_start).days + 1, 730, "不得漏天，也不得多取天")

    def test_slices_are_contiguous_and_reverse_ordered(self):
        windows = search.freshness_windows_for(730, today=self.TODAY)
        for newer, older in zip(windows, windows[1:]):
            self.assertEqual(
                date.fromisoformat(newer.split("..")[0])
                - date.fromisoformat(older.split("..")[1]),
                timedelta(days=1),
                "相邻段之间必须恰好相差 1 天，不能重叠也不能有空洞",
            )

    def test_slice_cap_lengthens_segments(self):
        """--days 3650 不能发 122 次请求：段数超上限时自动放长每段。"""
        windows = search.freshness_windows_for(3650, today=self.TODAY)
        self.assertLessEqual(len(windows), 26)
        span_start = date.fromisoformat(windows[-1].split("..")[0])
        span_end = date.fromisoformat(windows[0].split("..")[1])
        self.assertEqual((span_end - span_start).days + 1, 3650)

    def test_cfg_keeps_window_list(self):
        cfg = pipeline.load_scope_freshness({"search": {"provider": "bocha"}}, 730)
        self.assertEqual(len(cfg["freshness_list"]), 25)
        self.assertEqual(cfg["freshness"], cfg["freshness_list"][0])

    def test_request_payload_uses_the_slice_not_cfg(self):
        """回归：请求必须用**当前切片**，不能用 cfg 里的 fallback。

        早期实现的 ``_bocha_once`` 直接读 ``cfg["freshness"]``，于是 25 个切片
        全部请求了同一个区间，缓存 key 却按切片生成——结果是 2025 年整年一条
        都搜不到，而缓存看起来「每段都有数据」。
        """

        captured = {}

        class _Resp:
            status_code = 200

            @staticmethod
            def json():
                return {"code": 200, "data": {"webPages": {"value": []}}}

            @staticmethod
            def raise_for_status():
                return None

        class _Client:
            @staticmethod
            def post(url, json=None, headers=None):
                captured.update(json or {})
                return _Resp()

        cfg = {"count": 50, "freshness": "2024-11-24..2024-12-03"}
        search._bocha_once(
            "碳盘查 招标公告",
            cfg=cfg,
            api_key="k",
            endpoint="https://example.invalid",
            client=_Client(),
            freshness="2025-05-03..2025-06-01",
        )
        self.assertEqual(captured["freshness"], "2025-05-03..2025-06-01")


class TestTrend(unittest.TestCase):
    """两年汇总的价值在趋势，不在清单长度。"""

    def _record(self, published, group="core", amount=None):
        return {
            "source": {"published": published},
            "track": {"group": group},
            "fields": {"amount_cny": amount},
        }

    def test_quarter_buckets_sorted_by_time(self):
        records = [
            self._record("2026-11-02T00:00:00+08:00"),
            self._record("2025-03-10"),
            self._record("2025-12-01"),
            self._record("2025-02-01"),
        ]
        trend = pipeline.build_trend(records)
        self.assertEqual([t["label"] for t in trend], ["2025Q1", "2025Q4", "2026Q4"])
        self.assertEqual(trend[0]["count"], 2, "2025-02 与 2025-03 同属 Q1")

    def test_amount_summed_per_quarter_not_counted_when_missing(self):
        records = [
            self._record("2026-01-05", amount=100000),
            self._record("2026-02-05", amount=50000),
            self._record("2026-03-05", amount=None),
        ]
        trend = pipeline.build_trend(records)
        self.assertEqual(trend[0]["amount_known"], 2, "N/A 不补零，也不计入已知条数")
        self.assertEqual(trend[0]["amount_sum"], "15.00 万元")

    def test_records_without_date_do_not_create_bucket(self):
        trend = pipeline.build_trend([self._record(""), self._record("recent")])
        self.assertEqual(trend, [])

    def test_partial_quarter_flagged(self):
        """窗口首尾所在的季度不是完整季度，必须打标，否则会被读成断崖下跌。"""
        records = [self._record("2026-11-05"), self._record("2025-02-10")]
        trend = pipeline.build_trend(records, days=730, today=date(2026, 11, 23))
        self.assertEqual([t["label"] for t in trend], ["2025Q1", "2026Q4"])
        self.assertFalse(trend[0]["partial"], "2025Q1 在窗口内是完整季度")
        self.assertTrue(trend[1]["partial"], "2026Q4 只过到 11 月，必然不完整")

    def test_group_split(self):
        records = [
            self._record("2026-05-01", group="core"),
            self._record("2026-05-02", group="extended"),
            self._record("2026-06-01", group="edge"),
        ]
        trend = pipeline.build_trend(records)
        self.assertEqual(trend[0]["core"], 1)
        self.assertEqual(trend[0]["extended"], 1)
        self.assertEqual(trend[0]["count"], 3, "边缘也算总数，只是不计入核心/扩展列")


class TestStage(unittest.TestCase):
    def test_tender_stage(self):
        for title in ("某市碳盘查服务项目招标公告", "XX项目竞争性磋商公告", "XX咨询服务采购"):
            with self.subTest(title=title):
                self.assertEqual(extract.parse_stage(title)["code"], "tender")

    def test_award_stage(self):
        for title in ("XX项目中标公告", "XX项目成交结果公告", "XX项目中标候选人公示"):
            with self.subTest(title=title):
                self.assertEqual(extract.parse_stage(title)["code"], "award")

    def test_change_beats_tender(self):
        # 「变更公告」里没有招标字样，但如果同时出现，变更优先于招标
        self.assertEqual(extract.parse_stage("XX项目招标变更公告")["code"], "change")

    def test_site_name_is_not_a_stage_signal(self):
        """站点尾巴「-中国招标网」不能把非招标内容判成招标。"""
        self.assertEqual(extract.parse_stage("集团简介-中国招标网")["code"], "other")

    def test_bracket_label_wins_over_body(self):
        """真实标题「【招标结果】…成交候选人公示-山西招标网」曾被判成「招标」。

        标签说「招标结果」（已结束），正文说「成交候选人公示」，两处都指向
        award；旧实现只看正文、且 award 词表里没有「成交候选人」，于是被标签
        里的「招标」二字吃掉 → 已经成交的项目显示成「可投」。
        """
        cases = (
            "【招标结果】山西天脊潞安化工有限公司“十四五”能源审计项目成交候选人公示-山西招标网",
            "【招标结果】某市碳盘查服务项目成交候选人公示",
            "某市碳盘查服务项目成交候选人公示",
        )
        for title in cases:
            with self.subTest(title=title):
                self.assertEqual(extract.parse_stage(title)["code"], "award")

    def test_non_genre_label_is_stripped(self):
        """「【招标信用】」只是站点栏目分类，不是体裁；剥掉后再按正文判。"""
        title = "【招标信用】龙岩市林业局关于公开征集福建林业碳中和项目(龙岩)审定与核查机构的公告-福建招标网"
        stage = extract.parse_stage(title)
        self.assertEqual(stage["code"], "tender")
        self.assertFalse(stage["rule"].startswith("标签:"), "栏目标签不该被当成阶段信号")

    def test_genre_label_detected(self):
        stage = extract.parse_stage("【招标公告】凌钢技术中心产品生命周期评价系统采购招标公告-辽宁招标网")
        self.assertEqual(stage["code"], "tender")
        self.assertTrue(stage["rule"].startswith("标签:"))

    def test_stage_counts_in_stats(self):
        scope = self._scope_for_stats()
        hit = search.Hit(
            title="某市碳盘查服务项目中标公告",
            url="https://e.com/a",
            snippet="中标金额 44.8 万元",
            site="e.com",
            published="2026-11-01",
            query="碳盘查",
            provider="fixture",
        )
        record = pipeline.build_record(hit, ["碳盘查"], scope)
        stats = render.build_stats([record], scope.get("amount_buckets") or [])
        self.assertEqual(stats["award_count"], 1)
        self.assertEqual(stats["tender_count"], 0)
        self.assertEqual(stats["award_amount_known"], 1)
        self.assertIn("pct", stats["by_stage"][0])
        # pct 是条形宽度（相对最大值），share 才是真占比；两个都要有，
        # 否则 JSON 消费者会把「招标 pct=100」读成「招标占 100%」
        self.assertIn("share", stats["by_stage"][0])
        self.assertEqual(stats["by_stage"][0]["share"], 100.0)

    def test_stage_kpi_counts_by_code_not_label(self):
        """KPI 必须按 stage.code 统计，不能按中文展示标签。

        旧实现把 ``stage["label"]`` 当 Counter key，KPI 又按字面量
        ``stage_counter.get("招标")`` 读回：只要 STAGE_LABELS 里改一个字，
        或记录带了自定义 label，页面就显示「可投 0 条」而记录里明明有招标公告。
        """
        record = {
            "track": {"group": "core", "id": "T1", "name": "碳盘查"},
            "amount_bucket": "N/A",
            "fields": {},
            # 故意给一个和 STAGE_LABELS 不一致的 label，模拟文案调整
            "stage": {"code": "tender", "label": "招标中（可投）", "rule": "招标公告"},
            "flags": {},
        }
        stats = render.build_stats([record], [])
        self.assertEqual(stats["tender_count"], 1)
        self.assertEqual(stats["by_stage"][0]["code"], "tender")
        self.assertEqual(stats["by_stage"][0]["label"], "招标")  # 展示名统一取自常量表

    def test_na_bucket_ratio_is_capped(self):
        """被 skip 的 N/A 行不能算出 >100% 的条形宽度。

        真实数据里「N/A 10 条、已知金额 1 条」，N/A 被排除在分母外，
        旧实现算出 pct=share=1000，写进 HTML 是 width:1000%（溢出容器），
        写进 run_meta 是坏值。
        """
        rows = [
            {"label": "<10万", "count": 0},
            {"label": "10–50万", "count": 1},
            {"label": "N/A", "count": 10},
        ]
        result = render.with_pct(rows, skip={"N/A"})
        na = [row for row in result if row["label"] == "N/A"][0]
        self.assertEqual(na["pct"], 100.0)
        self.assertEqual(na["share"], 100.0)
        for row in result:
            self.assertLessEqual(row["pct"], 100.0)
            self.assertLessEqual(row["share"], 100.0)

    def _scope_for_stats(self):
        import yaml

        return yaml.safe_load((SKILL_ROOT / "config" / "scope.yaml").read_text("utf-8"))


class TestDeadlineSanity(unittest.TestCase):
    """截止日期早于发布日期 = 抽取错误，宁可 N/A。"""

    def _record(self, published, snippet):
        import yaml

        scope = yaml.safe_load((SKILL_ROOT / "config" / "scope.yaml").read_text("utf-8"))
        hit = search.Hit(
            title="某市碳盘查服务项目招标公告",
            url="https://e.com/d",
            snippet=snippet,
            site="e.com",
            published=published,
            query="碳盘查",
            provider="fixture",
        )
        return pipeline.build_record(hit, ["碳盘查"], scope)

    def test_past_deadline_dropped(self):
        record = self._record(
            "2026-11-10T09:00:00+08:00", "投标截止时间：2025-11-13。预算金额：25 万元"
        )
        self.assertIsNone(record["fields"]["deadline"]["value"])

    def test_future_deadline_kept(self):
        record = self._record(
            "2026-11-10T09:00:00+08:00", "投标截止时间：2026-11-30。预算金额：25 万元"
        )
        self.assertEqual(record["fields"]["deadline"]["value"], "2026-11-30")


class TestLinkAwards(unittest.TestCase):
    def _record(self, title, url, amount_line="预算金额：25 万元"):
        import yaml

        scope = yaml.safe_load((SKILL_ROOT / "config" / "scope.yaml").read_text("utf-8"))
        hit = search.Hit(
            title=title,
            url=url,
            snippet=amount_line,
            site="e.com",
            published="2026-11-01",
            query="碳盘查",
            provider="fixture",
        )
        return pipeline.build_record(hit, ["碳盘查"], scope)

    def test_award_amount_backfills_tender(self):
        bid = self._record("某市碳盘查服务项目招标公告", "https://e.com/bid", "")
        award = self._record("某市碳盘查服务项目中标公告", "https://e.com/award", "中标金额 44.8 万元")
        self.assertEqual(bid["title_norm"], award["title_norm"])
        linked = pipeline.link_awards([bid, award])
        self.assertEqual(linked, 1)
        self.assertEqual(bid["flags"]["award"]["url"], "https://e.com/award")
        # 招标记录原本没有金额，应由中标记录补上
        self.assertEqual(bid["fields"]["amount_cny"], "448000.00")
        self.assertEqual(award["flags"]["awarded_by"], bid["id"])

    def test_short_titles_are_not_paired(self):
        """归一化标题太短时配对风险高（不同项目同名），宁可不关联。"""
        bid = self._record("碳核查服务招标", "https://e.com/1")
        award = self._record("碳核查服务中标", "https://e.com/2")
        self.assertEqual(pipeline.link_awards([bid, award]), 0)


class TestIncrementalCLI(unittest.TestCase):
    """端到端：fixture 跑两遍，第二遍新增必须为 0、退出码为 0。"""

    def _run(self, argv):
        import contextlib
        import io
        import json

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = cli.main(argv)
        payload = None
        for line in buffer.getvalue().splitlines():
            if line.startswith("{"):
                payload = json.loads(line)
        return code, payload

    def test_second_run_reports_zero_new(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "t.db")
            base = [
                "--provider", "fixture", "--days", "30", "--incremental",
                "--db", db, "--out", tmp, "--limit", "5", "--print-json",
            ]
            code1, first = self._run(base)
            self.assertEqual(code1, 0)
            self.assertGreater(first["new"], 0)

            code2, second = self._run(base)
            self.assertEqual(code2, 0)
            self.assertEqual(second["new"], 0)
            self.assertEqual(second["window_total"], first["window_total"])

    def test_only_new_with_nothing_new_exits_zero(self):
        """cron 场景：没有新增不是失败，退出码必须是 0。"""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "t.db")
            base = ["--provider", "fixture", "--days", "30", "--db", db, "--out", tmp, "--limit", "5"]
            self.assertEqual(cli.main([*base, "--incremental"]), 0)
            self.assertEqual(cli.main([*base, "--only-new"]), 0)

    def test_preset_flows_into_meta(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            code, payload = self._run(
                ["--provider", "fixture", "--days", "30", "--preset", "energy",
                 "--out", tmp, "--limit", "5", "--print-json"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(payload["preset"], "energy")

    def test_run_meta_records_notify_result(self):
        """推送结果必须落进 run_meta.json —— 它是失败时唯一的排查线索。

        旧实现先写 run_meta 再推送，``meta["notify"]`` 恒为 null，
        而 references/schema.md 把 notify 列为 run_meta 字段，契约是空的。
        """
        import json as _json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "t.db")
            code, _payload = self._run(
                ["--provider", "fixture", "--days", "30", "--incremental", "--db", db,
                 "--out", tmp, "--limit", "5", "--format", "md",
                 "--notify", "webhook", "--notify-dry-run"]
            )
            self.assertEqual(code, 0)
            metas = list(Path(tmp).glob("*/run_meta.json"))
            self.assertEqual(len(metas), 1)
            saved = _json.loads(metas[0].read_text(encoding="utf-8"))
            notify = (saved.get("meta") or {}).get("notify")
            self.assertIsNotNone(notify, "notify 结果没写进 run_meta.json")
            self.assertTrue(notify["ok"])
            self.assertEqual(notify["target"], "dry-run")

    def test_notify_marks_all_new_even_when_list_truncated(self):
        """--limit 截断的清单不影响「已推送」标记。

        旧实现只标 ``shaped.shown``（受 --limit 截断）里的新增：--limit 2 而新增 7
        条时，剩下 5 条既没被列出、也没标已推，此后按 first_seen 算「往期已见」，
        永远不会出现在任何一次推送里，只能靠翻报告才发现。
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "t.db"
            fake_result = {
                "ok": True, "channel": "webhook", "target": "group", "error": "",
            }
            with mock.patch.object(notify, "notify", return_value=dict(fake_result)):
                code, payload = self._run(
                    ["--provider", "fixture", "--days", "30", "--incremental",
                     "--db", str(db_path), "--out", tmp, "--limit", "2", "--format", "md",
                     "--notify", "webhook", "--print-json"]
                )
            self.assertEqual(code, 0)
            new_count = payload["new"]
            self.assertGreater(new_count, 2, "用例要能触发 --limit 截断")
            self.assertEqual(payload["notify"]["marked"], new_count)

            db = store.Store(str(db_path))
            try:
                self.assertEqual(db.pending(), [], "被截断的新增也必须标为已推送")
            finally:
                db.close()


class TestQueryBudget(unittest.TestCase):
    """--max-queries 是计费护栏：--sources 追加的定向 query 也要算在预算里。"""

    def _queries(self, argv):
        captured: list[list[str]] = []

        def fake_run(queries, **kwargs):
            captured.append(list(queries))
            return [], []

        site_items = [
            {"query": f"site:src{i}.com 碳盘查", "source_id": f"s{i}", "source_name": f"源{i}"}
            for i in range(3)
        ]
        with mock.patch.object(
            pipeline.sources_mod, "site_queries", return_value=site_items
        ), mock.patch.object(
            pipeline.sources_mod, "crawl_all", return_value=([], [], [])
        ), mock.patch.object(pipeline.search_mod, "run_queries", side_effect=fake_run):
            pipeline.collect(cli.parse_args(argv), run_id="t", now=datetime.now())
        return captured[0]

    def test_site_queries_count_towards_budget(self):
        queries = self._queries(
            ["--provider", "fixture", "--days", "30", "--sources", "--max-queries", "5",
             "--query", "碳盘查,碳核查,碳足迹,碳资产,碳交易,碳管理"]
        )
        self.assertEqual(len(queries), 5, "总请求数不能超过 --max-queries")
        # 定向 query 是用户显式要的，必须保住；被截掉的是自动关键词
        self.assertEqual(sum(1 for q in queries if q.startswith("site:")), 3)
        self.assertEqual(queries[:2], ["碳盘查", "碳核查"])

    def test_budget_without_sources_is_unchanged(self):
        queries = self._queries(
            ["--provider", "fixture", "--days", "30", "--max-queries", "3",
             "--query", "碳盘查,碳核查,碳足迹"]
        )
        self.assertEqual(queries, ["碳盘查", "碳核查", "碳足迹"])


class TestConfigExitCode(unittest.TestCase):
    """配置错误的退出码必须是 2（README/SKILL 的约定）。

    旧实现用 ``raise SystemExit("...")``，Python 把字符串参数当消息、退出码设成
    1，与文档里的「配置错误 → 2」不符：cron 只按 != 0 判断倒没差，但调用方脚本
    区分「没结果(2)」和「崩了(1)」时会走错分支。
    """

    def test_missing_scope_exits_2(self):
        import contextlib
        import io
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = cli.main(
                    ["--provider", "fixture", "--scope", str(Path(tmp) / "none.yaml"), "--out", tmp]
                )
            self.assertEqual(code, 2)
            self.assertIn("[错误]", err.getvalue())

    def test_unknown_preset_exits_2(self):
        import contextlib
        import io
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = cli.main(["--provider", "fixture", "--preset", "nope", "--out", tmp])
            self.assertEqual(code, 2)
            self.assertIn("找不到预设", err.getvalue())

    def test_only_new_with_no_store_exits_2(self):
        """没有库就没有「见过」，`--only-new` 必然产出 0 条。

        旧行为是静默输出空报告 + 退出码 0，命令行只写「保留 0 条」，
        看不出是参数矛盾还是检索失败。
        """
        import contextlib
        import io
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = cli.main(
                    ["--provider", "fixture", "--days", "30", "--only-new",
                     "--no-store", "--out", tmp]
                )
            self.assertEqual(code, 2)
            self.assertIn("--only-new", err.getvalue())
            self.assertFalse(list(Path(tmp).glob("*/records.json")), "不该产出任何报告")

    def test_count_above_bocha_limit_exits_2(self):
        """博查 count 上限 50：传 100 不会报错、只会安静地少给，必须提前拒绝。"""
        import contextlib
        import io
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = cli.main(
                    ["--provider", "bocha", "--days", "30", "--count", "100", "--out", tmp]
                )
            self.assertEqual(code, 2)
            self.assertIn("50", err.getvalue())


class TestFixtureDbIsolation(unittest.TestCase):
    """fixture 演练不能写生产增量库。

    真实事故：用 ``--provider fixture --incremental`` 演示「首跑 7 / 二跑 0」，
    7 条「某市…」样本直接落进 ``data/tenders.db``，之后真跑时它们在库里顶着，
    真实项目的「往期已见」判断被假数据污染。
    """

    def test_fixture_without_db_uses_separate_file(self):
        path = pipeline._resolve_db(None, {"provider": "fixture"})
        self.assertIsNotNone(path)
        self.assertTrue(str(path).endswith("tenders_fixture.db"))
        self.assertNotEqual(Path(path), Path(pipeline.store_mod.DEFAULT_DB))

    def test_bocha_keeps_production_db(self):
        self.assertIsNone(pipeline._resolve_db(None, {"provider": "bocha"}))

    def test_explicit_db_wins(self):
        self.assertEqual(pipeline._resolve_db("/tmp/custom.db", {"provider": "fixture"}), "/tmp/custom.db")


class TestCrawlFailurePropagation(unittest.TestCase):
    """crawl 一条没抓到、但源失败时，失败原因不能丢（回归 B1）。"""

    def test_failures_survive_empty_crawl_result(self):
        import contextlib
        import io
        import json
        import tempfile

        failure = search.Failure(
            query="crawl:ccgp", provider="crawl", reason="robots.txt 禁止抓取 https://x/list"
        )
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            pipeline.sources_mod, "site_queries", return_value=[]
        ), mock.patch.object(
            pipeline.sources_mod, "crawl_all", return_value=([], [failure], [])
        ):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = cli.main(
                    [
                        "--provider", "fixture", "--days", "30", "--sources",
                        "--out", tmp, "--limit", "5", "--print-json",
                    ]
                )
        self.assertEqual(code, 0)
        payload = [json.loads(line) for line in buffer.getvalue().splitlines() if line.startswith("{")][0]
        reasons = [item["reason"] for item in payload["failures"]]
        self.assertIn("robots.txt 禁止抓取 https://x/list", reasons)


class TestConcurrentSearch(unittest.TestCase):
    """并发检索：结果顺序稳定、单条失败不吞其它结果、限频可退避。"""

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    def _cfg(self, concurrency=2, retry=0):
        return {
            "provider": "bocha",
            "endpoint": "https://example.invalid",
            "count": 50,
            "retry": retry,
            "concurrency": concurrency,
            "freshness_list": ["oneMonth"],
        }

    def _hit(self, query):
        return search.Hit(
            title=query, url=f"https://e.com/{query}", snippet="", site="",
            published="", query=query, provider="bocha",
        )

    def test_results_keep_request_order(self):
        """完成的先后不能影响结果顺序，否则同一输入会产出两份不同报告。"""
        import time as _time

        def fake(query, **kwargs):
            _time.sleep(0.03 if query == "a" else 0.0)  # a 后完成
            return [self._hit(query)]

        with mock.patch.object(search, "search_bocha", side_effect=fake), mock.patch.object(
            search, "load_env", return_value={"BOCHA_API_KEY": "k"}
        ), mock.patch.object(search.httpx, "Client", self._Client):
            hits, failures = search.run_queries(["a", "b"], cfg=self._cfg())

        self.assertEqual([hit.title for hit in hits], ["a", "b"])
        self.assertEqual(failures, [])

    def test_one_failure_keeps_other_results(self):
        def fake(query, **kwargs):
            if query == "bad":
                raise search.SearchError("boom")
            return [self._hit(query)]

        with mock.patch.object(search, "search_bocha", side_effect=fake), mock.patch.object(
            search, "load_env", return_value={"BOCHA_API_KEY": "k"}
        ), mock.patch.object(search.httpx, "Client", self._Client):
            hits, failures = search.run_queries(["ok1", "bad", "ok2"], cfg=self._cfg(concurrency=3))

        self.assertEqual([hit.title for hit in hits], ["ok1", "ok2"])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].reason, "boom")

    def test_rate_limit_retries_with_backoff(self):
        calls = []

        def fake_once(query, **kwargs):
            calls.append(query)
            if len(calls) == 1:
                raise search.RateLimitError("博查限频：并发过高")
            return []

        with mock.patch.object(search, "_bocha_once", side_effect=fake_once), mock.patch.object(
            search.time, "sleep"
        ) as sleeper:
            hits = search._bocha_with_retry(
                object(), "q", cfg={"retry": 2}, api_key="k", endpoint="",
                key="k1", freshness="oneMonth", use_cache=False,
            )
        self.assertEqual(hits, [])
        self.assertEqual(len(calls), 2)
        sleeper.assert_called_once_with(4)  # 限频退避从 4 秒起

    def test_auth_failure_is_not_retried(self):
        calls = []

        def fake_once(query, **kwargs):
            calls.append(query)
            raise search.SearchError("博查鉴权失败：检查 BOCHA_API_KEY 是否有效")

        with mock.patch.object(search, "_bocha_once", side_effect=fake_once), mock.patch.object(
            search.time, "sleep"
        ):
            with self.assertRaises(search.SearchError):
                search._bocha_with_retry(
                    object(), "q", cfg={"retry": 2}, api_key="bad", endpoint="",
                    key="k1", freshness="oneMonth", use_cache=False,
                )
        self.assertEqual(len(calls), 1, "401 重试只会白烧配额")

    # ---- 边界：provider 返回 5xx / 坏 JSON 时必须是 SearchError，不能穿透 ----
    class _Resp:
        """够用的假响应：只实现 _bocha_once 用到的那几个成员。"""

        def __init__(self, status_code, *, body=None, bad_json=False):
            self.status_code = status_code
            self._body = body or {}
            self._bad_json = bad_json
            self.headers = {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"{self.status_code}", request=httpx.Request("POST", "https://x"),
                    response=httpx.Response(self.status_code),
                )

        def json(self):
            if self._bad_json:
                raise ValueError("Expecting value: line 1 column 1 (char 0)")
            return self._body

    class _StubClient:
        def __init__(self, *responses):
            self._responses = list(responses)
            self.calls = 0

        def post(self, *args, **kwargs):
            self.calls += 1
            return self._responses[min(self.calls - 1, len(self._responses) - 1)]

    def test_http_5xx_becomes_search_error(self):
        """`raise_for_status()` 抛的 HTTPStatusError 必须在边界处转成 SearchError。

        否则它会穿过 `_bocha_with_retry` 的 `except SearchError` 与 `run_queries`
        的兜底，让一整个分片批次的结果随最后一个 502 一起丢。
        """
        client = self._StubClient(self._Resp(502))
        with self.assertRaises(search.SearchError) as ctx:
            search._bocha_once(
                "q", cfg={"count": 10}, api_key="k", endpoint="https://x",
                client=client, freshness="oneMonth",
            )
        self.assertIn("502", str(ctx.exception))

    def test_non_json_body_becomes_search_error(self):
        """网关错误页是 HTML，`resp.json()` 会抛 ValueError，同样要转。"""
        client = self._StubClient(self._Resp(200, bad_json=True))
        with self.assertRaises(search.SearchError):
            search._bocha_once(
                "q", cfg={"count": 10}, api_key="k", endpoint="https://x",
                client=client, freshness="oneMonth",
            )

    def test_5xx_is_retried_then_succeeds(self):
        """5xx 属于可重试错误：退避一次后拿到正常响应就该成功。"""
        ok = self._Resp(200, body={"code": 200, "data": {"webPages": {"value": [
            {"name": "标题", "url": "https://e.com/a", "summary": "s"}
        ]}}})
        client = self._StubClient(self._Resp(500), ok)
        with mock.patch.object(search.time, "sleep") as sleeper:
            hits = search._bocha_with_retry(
                client, "q", cfg={"retry": 1, "count": 10}, api_key="k",
                endpoint="https://x", key="k1", freshness="oneMonth", use_cache=False,
            )
        self.assertEqual([hit.title for hit in hits], ["标题"])
        self.assertEqual(client.calls, 2)
        sleeper.assert_called_once_with(1)  # 5xx 按 2**0 退避，不占限频的 4s 档

    def test_unexpected_error_is_wrapped_by_search_bocha(self):
        """哪怕 provider 层冒出意外异常，单条 query 也只能变成 SearchError。"""
        with mock.patch.object(
            search, "_bocha_with_retry", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(search.SearchError) as ctx:
                search.search_bocha(
                    "q", cfg={"count": 10, "retry": 0}, api_key="k",
                    endpoint="https://x", use_cache=False,
                )
        self.assertIn("RuntimeError", str(ctx.exception))

    def test_http_error_does_not_kill_the_batch(self):
        """整批里一条 query 撞 5xx，其余结果必须照常返回。"""
        def fake_once(query, **kwargs):
            if query == "bad":
                raise httpx.HTTPStatusError(
                    "500", request=httpx.Request("POST", "https://x"),
                    response=httpx.Response(500),
                )
            return [self._hit(query)]

        with mock.patch.object(search, "_bocha_once", side_effect=fake_once), mock.patch.object(
            search, "load_env", return_value={"BOCHA_API_KEY": "k"}
        ), mock.patch.object(search.httpx, "Client", self._Client), mock.patch.object(
            search.time, "sleep"
        ):
            hits, failures = search.run_queries(
                ["ok1", "bad", "ok2"], cfg=self._cfg(concurrency=3)
            )

        self.assertEqual([hit.title for hit in hits], ["ok1", "ok2"])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].query, "bad")
        self.assertIn("HTTPStatusError", failures[0].reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)

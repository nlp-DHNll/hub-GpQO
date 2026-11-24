"""报告渲染、外链安全与推送

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


class TestReport(unittest.TestCase):
    """报告是最终交付物，模板改动最容易在这里静默出错。"""

    def _context(self, title="某市碳盘查服务项目招标公告", snippet="预算金额：25 万元"):
        import yaml

        scope = yaml.safe_load((SKILL_ROOT / "config" / "scope.yaml").read_text("utf-8"))
        hit = search.Hit(
            title=title,
            url="https://example.com/a",
            snippet=snippet,
            site="example",
            published="2026-11-01T00:00:00+08:00",
            query="碳盘查 招标公告",
            provider="fixture",
        )
        record = pipeline.build_record(hit, ["碳盘查 招标公告"], scope)
        meta = {
            "generated_date": "2026-11-23",
            "generated_at": "2026-11-23 10:00:00",
            "query_label": "碳盘查 招标公告",
            "days": 30,
            "provider": "fixture",
            "raw_hits": 1,
            "raw_hits_total": 1,
            "queries": ["碳盘查 招标公告"],
            "freshness_windows": ["oneMonth"],
            "kept_total": 1,
            "shown": 1,
            "failures": [],
            "duplicates": 0,
            "below_threshold": 0,
            "not_tender": 0,
            "out_of_window": 0,
            "unknown_date": 0,
            "thresholds": {"core": 0.6, "extended": 0.65, "edge": 0.75},
            "gray_low": 0.2,
            "weights": (scope.get("relevance") or {}).get("weights") or {},
        }
        return {
            "meta": meta,
            "records": [record],
            "stats": render.build_stats([record], scope.get("amount_buckets") or []),
            "trend": pipeline.build_trend([record], days=30),
            "suspects": [],
            "coverage": render.build_coverage(meta),
        }

    def test_html_is_self_contained(self):
        html = render.render_report(self._context(), "html")
        self.assertTrue(html.lstrip().startswith("<!DOCTYPE html>"))
        self.assertIn("</html>", html)
        # 单文件交付：不能依赖外部 CSS/JS，否则离线打开会掉样式
        self.assertNotIn("<link", html)
        self.assertNotIn("<script src", html)
        self.assertNotIn("http://", html.split("<body")[0])

    def test_html_escapes_page_content(self):
        """标题来自网页，含 < > 时必须转义，否则会破坏结构甚至注入。"""
        html = render.render_report(
            self._context(title="碳盘查<b>服务</b>项目招标公告 & 采购"), "html"
        )
        self.assertIn("&lt;b&gt;", html)
        self.assertNotIn("<b>服务</b>", html)

    def test_markdown_does_not_escape(self):
        md = render.render_report(self._context(), "md")
        self.assertIn("# ESG 招标情报清单", md)
        # Markdown 里转义会把尖括号印成 &lt;
        self.assertNotIn("&lt;", md)

    def test_bars_have_pct(self):
        ctx = self._context()
        for row in ctx["stats"]["by_bucket"]:
            self.assertIn("pct", row)
        self.assertEqual(ctx["stats"]["amount_unknown"], 0)

    def test_write_reports_both_formats(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            paths = render.write_reports(self._context(), Path(tmp), "both")
            names = sorted(p.name for p in paths)
            self.assertEqual(names, ["tender_list.html", "tender_list.md"])

    def test_unknown_format_rejected(self):
        with self.assertRaises(ValueError):
            render.write_reports(self._context(), Path("."), "pdf")

    def test_amount_wan_is_fixed_unit(self):
        """趋势列必须统一单位，否则 3.16 亿元和 6286 万元没法比大小。"""
        self.assertEqual(render.fmt_amount_wan("62864200"), "6,286.42 万元")
        self.assertEqual(render.fmt_amount_wan("316000000"), "31,600.00 万元")


class TestUrlSafety(unittest.TestCase):
    """外部 URL 只允许 http(s)：检索层、模板层、docx 层各挡一次。"""

    def _record(self, url):
        import yaml

        scope = yaml.safe_load((SKILL_ROOT / "config" / "scope.yaml").read_text("utf-8"))
        hit = search.Hit(
            title="某市碳盘查服务项目招标公告",
            url=url,
            snippet="预算金额：25 万元",
            site="example",
            published="2026-11-01",
            query="碳盘查 招标公告",
            provider="fixture",
        )
        return pipeline.build_record(hit, ["碳盘查 招标公告"], scope)

    def _context(self, record):
        meta = {
            "generated_date": "2026-11-23",
            "generated_at": "2026-11-23 10:00:00",
            "query_label": "碳盘查 招标公告",
            "days": 30,
            "provider": "fixture",
            "raw_hits": 1,
            "raw_hits_total": 1,
            "queries": ["碳盘查 招标公告"],
            "freshness_windows": ["oneMonth"],
            "kept_total": 1,
            "shown": 1,
            "failures": [],
            "duplicates": 0,
            "below_threshold": 0,
            "not_tender": 0,
            "out_of_window": 0,
            "unknown_date": 0,
            "award_links": 0,
            "thresholds": {"core": 0.6, "extended": 0.65, "edge": 0.75},
            "gray_low": 0.2,
            "weights": {"title_base": 0.65, "title_extra": 0.3, "body_bonus": 0.3, "body_saturate": 3},
        }
        return {
            "meta": meta,
            "records": [record],
            "stats": render.build_stats([record], []),
            "trend": [],
            "suspects": [],
            "coverage": render.build_coverage(meta),
        }

    def test_search_layer_drops_non_http_url(self):
        self.assertEqual(search._clean_url("javascript:alert(1)"), "")
        self.assertEqual(search._clean_url("data:text/html,<script>x</script>"), "")
        self.assertEqual(search._clean_url(" https://e.com/a "), "https://e.com/a")

    def test_template_filter_returns_hash(self):
        self.assertEqual(render._safe_url("javascript:alert(1)"), "#")
        self.assertEqual(render._safe_url(None), "#")
        self.assertEqual(render._safe_url("http://e.com"), "http://e.com")

    def test_html_report_never_emits_javascript_href(self):
        html = render.render_report(self._context(self._record("javascript:alert(1)")), "html")
        self.assertNotIn("javascript:", html)
        self.assertIn('href="#"', html)

    def test_docx_skips_non_http_hyperlink(self):
        document, rels = docx_export.build_document(
            self._context(self._record("javascript:alert(1)"))
        )
        self.assertNotIn("javascript:", rels or "")
        self.assertNotIn("javascript:", document)
        self.assertIn("某市碳盘查", document)


class TestReportContract(unittest.TestCase):
    """ReportContext 是模板上下文的唯一契约；docx 也要能走 write_reports。"""

    def _context(self):
        import yaml

        scope = yaml.safe_load((SKILL_ROOT / "config" / "scope.yaml").read_text("utf-8"))
        hit = search.Hit(
            title="某市碳盘查服务项目招标公告",
            url="https://e.com/1",
            snippet="预算金额：25 万元",
            site="example",
            published="2026-11-01",
            query="碳盘查",
            provider="fixture",
        )
        record = pipeline.build_record(hit, ["碳盘查"], scope)
        meta = {
            "generated_date": "2026-11-23",
            "generated_at": "2026-11-23 10:00:00",
            "query_label": "碳盘查",
            "days": 30,
            "provider": "fixture",
            "raw_hits": 1,
            "raw_hits_total": 1,
            "queries": ["碳盘查"],
            "freshness_windows": ["oneMonth"],
            "kept_total": 1,
            "shown": 1,
            "failures": [],
            "duplicates": 0,
            "below_threshold": 0,
            "not_tender": 0,
            "out_of_window": 0,
            "unknown_date": 0,
            "thresholds": {"core": 0.6, "extended": 0.65, "edge": 0.75},
            "gray_low": 0.2,
            "weights": {"title_base": 0.65, "title_extra": 0.3, "body_bonus": 0.3, "body_saturate": 3},
        }
        return render.ReportContext(
            meta=meta,
            records=[record],
            stats=render.build_stats([record], []),
            coverage=render.build_coverage(meta),
            trend=[],
            suspects=[],
        )

    def test_dataclass_fills_defaults(self):
        context = self._context()
        self.assertEqual(context.trend, [])
        self.assertIsNone(context.incremental)
        self.assertEqual(context.report_path, "")
        self.assertEqual(context.stages, [])

    def test_coerce_ignores_unknown_keys(self):
        context = render.ReportContext.coerce(
            {"meta": {}, "records": [], "stats": {}, "coverage": {}, "unknown": 1}
        )
        self.assertNotIn("unknown", context.as_dict())

    def test_render_accepts_plain_dict_too(self):
        """调用方（含测试与外部脚本）仍可直接传 dict。"""
        html = render.render_report(self._context().as_dict(), "html")
        self.assertIn("某市碳盘查", html)

    def test_docx_written_through_write_reports(self):
        """回归：write_reports 里 docx 分支曾用平铺 import，包化后必炸。"""
        import tempfile
        from zipfile import ZipFile

        with tempfile.TemporaryDirectory() as tmp:
            paths = render.write_reports(self._context(), Path(tmp), "docx")
            names = ZipFile(paths[0]).namelist()
        self.assertIn("word/document.xml", names)


class TestDocx(unittest.TestCase):
    def _context(self):
        scope = __import__("yaml").safe_load(
            (SKILL_ROOT / "config" / "scope.yaml").read_text("utf-8")
        )
        hit = search.Hit(
            title="某市碳盘查 & 核查服务项目招标公告",
            url="https://example.com/a?x=1&y=2",
            snippet="预算金额：25 万元",
            site="example",
            published="2026-11-01",
            query="碳盘查",
            provider="fixture",
        )
        record = pipeline.build_record(hit, ["碳盘查"], scope)
        meta = {
            "generated_date": "2026-11-23",
            "generated_at": "2026-11-23 10:00:00",
            "query_label": "碳盘查",
            "days": 30,
            "provider": "fixture",
            "raw_hits": 1,
            "raw_hits_total": 1,
            "queries": ["碳盘查"],
            "freshness_windows": ["oneMonth"],
            "kept_total": 1,
            "shown": 1,
            "failures": [],
            "duplicates": 0,
            "below_threshold": 0,
            "not_tender": 0,
            "out_of_window": 0,
            "unknown_date": 0,
            "thresholds": {"core": 0.6, "extended": 0.65, "edge": 0.75},
            "gray_low": 0.2,
            "weights": {},
        }
        return {
            "meta": meta,
            "records": [record],
            "stats": render.build_stats([record], scope.get("amount_buckets") or []),
            "trend": [],
            "suspects": [],
            "coverage": render.build_coverage(meta),
        }

    def test_package_has_required_parts(self):
        import tempfile
        from zipfile import ZipFile

        with tempfile.TemporaryDirectory() as tmp:
            path = docx_export.write_docx(self._context(), Path(tmp) / "r.docx")
            with ZipFile(path) as archive:
                names = set(archive.namelist())
                document = archive.read("word/document.xml").decode("utf-8")
            self.assertIn("[Content_Types].xml", names)
            self.assertIn("word/document.xml", names)
            # 外链需要 rels，否则超链接在 Word 里点不动
            self.assertIn("word/_rels/document.xml.rels", names)
            # 文本里的 & 必须转义，否则 XML 解析失败
            self.assertIn("&amp;", document)
            self.assertNotIn("某市碳盘查 & 核查", document)

    def test_amount_format_matches_other_formats(self):
        """Word 里的金额必须和网页/JSON 写法一致。

        旧实现自己抄了一份浮点版（「1.26 亿」、无小数、单位缺「元」），
        同一个数字在 html 与 docx 里长得不一样。
        """
        import re
        import tempfile
        from zipfile import ZipFile

        context = self._context()
        context["records"][0]["fields"]["amount_cny"] = "126000000"
        with tempfile.TemporaryDirectory() as tmp:
            path = docx_export.write_docx(context, Path(tmp) / "r.docx")
            with ZipFile(path) as archive:
                document = archive.read("word/document.xml").decode("utf-8")
        expected = render.fmt_amount("126000000")
        self.assertEqual(expected, "1.26 亿元")
        self.assertIn(expected, document)

    def test_table_grid_fits_page(self):
        """所有表格的 gridCol 合计都不能超过页宽，否则右边会顶出页边距。"""
        import re
        import tempfile
        from zipfile import ZipFile

        with tempfile.TemporaryDirectory() as tmp:
            path = docx_export.write_docx(self._context(), Path(tmp) / "r.docx")
            with ZipFile(path) as archive:
                document = archive.read("word/document.xml").decode("utf-8")
        grids = re.findall(r"<w:tblGrid>(.*?)</w:tblGrid>", document, re.S)
        self.assertTrue(grids)
        for grid in grids:
            widths = [int(w) for w in re.findall(r'<w:gridCol w:w="(\d+)"', grid)]
            self.assertLessEqual(sum(widths), docx_export.TABLE_W, widths)

    def test_fit_widths_scales_down_proportionally(self):
        widths = [420, 3300, 1500, 1200, 900, 800, 1400, 600]  # 旧清单表：10120
        fitted = docx_export._fit_widths(widths)
        self.assertEqual(sum(fitted), docx_export.TABLE_W)
        self.assertTrue(all(w >= 1 for w in fitted))
        self.assertEqual(fitted[1], max(fitted), "最宽的列仍应最宽")
        # 不超宽时原样返回，不做无谓的精度损失
        self.assertEqual(docx_export._fit_widths([2600, 3200]), [2600, 3200])

    def test_openable_by_python_docx(self):
        import tempfile

        try:
            import docx
        except ImportError:  # 没装就只做结构校验
            self.skipTest("python-docx 未安装")
        with tempfile.TemporaryDirectory() as tmp:
            path = docx_export.write_docx(self._context(), Path(tmp) / "r.docx")
            doc = docx.Document(str(path))
            text = "\n".join(p.text for p in doc.paragraphs)
            self.assertIn("招标情报清单", text)
            self.assertGreaterEqual(len(doc.tables), 3)


class TestNotify(unittest.TestCase):
    def test_payload_per_vendor(self):
        feishu = notify.build_payload("https://open.feishu.cn/open-apis/bot/v2/hook/x", "t", "body")
        self.assertEqual(feishu["msg_type"], "text")
        wecom = notify.build_payload("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=1", "t", "body")
        self.assertEqual(wecom["msgtype"], "text")
        dingtalk = notify.build_payload("https://oapi.dingtalk.com/robot/send?access_token=x", "t", "body")
        self.assertEqual(dingtalk["msgtype"], "markdown")

    def test_detect_channel(self):
        self.assertEqual(notify.detect_channel("https://open.feishu.cn/x"), "feishu")
        self.assertEqual(notify.detect_channel("https://qyapi.weixin.qq.com/x"), "wecom")
        self.assertEqual(notify.detect_channel("https://example.com/hook"), "generic")

    def test_message_contains_key_numbers(self):
        scope = __import__("yaml").safe_load(
            (SKILL_ROOT / "config" / "scope.yaml").read_text("utf-8")
        )
        hit = search.Hit(
            title="某市碳盘查服务项目招标公告",
            url="https://e.com/a",
            snippet="预算金额：25 万元",
            site="e.com",
            published="2026-11-01",
            query="碳盘查",
            provider="fixture",
        )
        record = pipeline.build_record(hit, ["碳盘查"], scope)
        stats = render.build_stats([record], scope.get("amount_buckets") or [])
        title, text = notify.build_message(
            {"meta": {"generated_date": "2026-11-23", "days": 30, "provider": "fixture"},
             "stats": stats,
             "records": [record],
             "incremental": {"new": 1, "seen": 0},
             "stages": stats["by_stage"],
             "report_path": "/tmp/r.html"}
        )
        self.assertIn("新增", title)
        self.assertIn("25", text)
        self.assertIn("/tmp/r.html", text)

    def test_message_title_counts_new_not_total(self):
        """标题曾写「新增 7 条」而正文写「本期新增 0 条」。

        原因是标题取了 ``stats.total``（窗口内全量），正文取了 ``incremental.new``。
        推送是唯一会被转发的产物，数字自相矛盾比没有数字更糟。
        """
        records = [{"raw": {"title_clean": f"项目{i}"}, "fields": {}} for i in range(7)]
        title, text = notify.build_message(
            {
                "meta": {"generated_date": "2026-11-24", "days": 30, "provider": "bocha"},
                "stats": {"total": 7},
                "records": records,
                "incremental": {"new": 0, "seen": 7},
            }
        )
        self.assertIn("新增 0 条", title)
        self.assertNotIn("新增 7 条", title)
        self.assertIn("本期新增 0 条", text)

        # 没有增量信息时（未开 --incremental）退回「本期 N 条」，不能凭空说「新增」
        title2, _ = notify.build_message(
            {"meta": {"generated_date": "2026-11-24"}, "stats": {"total": 7}, "records": records}
        )
        self.assertIn("本期 7 条", title2)

    def test_message_amount_uses_shared_format(self):
        """推送里的金额要和网页/Word 一个写法。

        旧实现是 `f"{float(amount)/1e4:.2f} 万"`：浮点算钱、单位少个「元」，
        同一个项目在群里显示「25.00 万」、在报告里显示「25.00 万元」。
        """
        records = [
            {"raw": {"title_clean": "项目"}, "fields": {"amount_cny": "250000"}},
            {"raw": {"title_clean": "项目2"}, "fields": {"amount_cny": "126000000"}},
        ]
        _, text = notify.build_message(
            {"meta": {"generated_date": "2026-11-24"}, "stats": {"total": 2}, "records": records}
        )
        self.assertIn(render.fmt_amount("250000"), text)      # 25.00 万元
        self.assertIn(render.fmt_amount("126000000"), text)   # 1.26 亿元
        self.assertNotIn("25.00 万 ", text)

    def test_webhook_errcode_reported_as_failure(self):
        class Resp:
            status_code = 200
            text = '{"errcode": 93000, "errmsg": "invalid webhook url"}'

        class Client:
            def post(self, url, json=None):
                return Resp()

        with mock.patch.object(netguard, "_resolve", return_value=["93.184.216.34"]):
            result = notify.send_webhook("https://qyapi.weixin.qq.com/x", "t", "b", client=Client())
        self.assertFalse(result["ok"])
        self.assertIn("93000", result["error"])

    def test_webhook_redirect_is_failure(self):
        """3xx 不能当成功：httpx 默认不跟随重定向，消息其实没送到。"""
        class Resp:
            status_code = 302
            text = ""

        class Client:
            def post(self, url, json=None):
                return Resp()

        with mock.patch.object(netguard, "_resolve", return_value=["93.184.216.34"]):
            result = notify.send_webhook("https://example.com/hook", "t", "b", client=Client())
        self.assertFalse(result["ok"])
        self.assertIn("302", result["error"])

    def test_webhook_success(self):
        class Resp:
            status_code = 200
            text = '{"errcode": 0, "errmsg": "ok"}'

        class Client:
            def post(self, url, json=None):
                return Resp()

        # 单测不依赖真实 DNS：把解析结果钉成公网地址
        with mock.patch.object(netguard, "_resolve", return_value=["93.184.216.34"]):
            result = notify.send_webhook("https://qyapi.weixin.qq.com/x", "t", "b", client=Client())
        self.assertTrue(result["ok"])

    def test_email_without_config_does_not_raise(self):
        result = notify.send_email("s", "b", env={})
        self.assertFalse(result["ok"])
        self.assertIn("SMTP_HOST", result["error"])


class TestPresets(unittest.TestCase):
    def _scope(self):
        import yaml

        return yaml.safe_load((SKILL_ROOT / "config" / "scope.yaml").read_text("utf-8"))

    def test_deep_merge_replaces_lists_and_merges_dicts(self):
        base = {"a": {"b": 1, "c": [1, 2]}, "keep": True}
        merged = presets.deep_merge(base, {"a": {"c": [9]}})
        self.assertEqual(merged["a"]["c"], [9])
        self.assertEqual(merged["a"]["b"], 1)
        self.assertTrue(merged["keep"])
        # 原字典不能被改动
        self.assertEqual(base["a"]["c"], [1, 2])

    def test_apply_preset_does_not_mutate_base(self):
        scope = self._scope()
        original = scope["tracks"]["core"]["T5"]["keywords"][:]
        preset = presets.load_preset("energy")
        applied = presets.apply_preset(scope, preset)
        self.assertNotEqual(applied["tracks"]["core"]["T5"]["keywords"], original)
        self.assertEqual(scope["tracks"]["core"]["T5"]["keywords"], original)
        self.assertEqual(applied["preset"]["name"], "energy")

    def test_missing_preset_message_lists_available(self):
        with self.assertRaises(presets.PresetError) as ctx:
            presets.load_preset("no-such-preset")
        self.assertIn("energy", str(ctx.exception))

    def test_all_shipped_presets_load(self):
        items = presets.list_presets()
        names = {item["name"] for item in items}
        self.assertTrue({"energy", "manufacturing", "finance"} <= names)
        for item in items:
            data = presets.load_preset(item["name"])
            self.assertIn("scope", data)


if __name__ == "__main__":
    unittest.main(verbosity=2)

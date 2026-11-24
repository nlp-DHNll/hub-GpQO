"""已推送库（增量与幂等）

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


class TestStore(unittest.TestCase):
    """已推送库：幂等是硬要求——重复跑不能把「新增」算错。"""

    def _record(self, title="某市碳盘查服务项目招标公告", snippet="预算金额：25 万元", url="https://e.com/1"):
        import yaml

        scope = yaml.safe_load((SKILL_ROOT / "config" / "scope.yaml").read_text("utf-8"))
        hit = search.Hit(
            title=title,
            url=url,
            snippet=snippet,
            site="e.com",
            published="2026-11-20T00:00:00+08:00",
            query="碳盘查 招标公告",
            provider="fixture",
        )
        return pipeline.build_record(hit, ["碳盘查"], scope)

    def test_annotate_marks_new_then_seen(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with store.Store(Path(tmp) / "t.db") as db:
                record = self._record()
                first = db.annotate([record], run_id="r1")
                self.assertEqual(first["new"], 1)
                self.assertTrue(record["flags"]["is_new"])

                second = db.annotate([self._record()], run_id="r2")
                self.assertEqual(second["new"], 0)
                self.assertEqual(second["seen"], 1)
                self.assertFalse(second["stats"]["total"] == 0)
                self.assertEqual(second["stats"]["total"], 1)

    def test_idempotent_upsert_does_not_duplicate_rows(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with store.Store(Path(tmp) / "t.db") as db:
                for _ in range(3):
                    db.annotate([self._record()], run_id="r")
                self.assertEqual(db.stats()["total"], 1)

    def test_title_match_catches_fingerprint_drift(self):
        """同一条公告后补了中标金额 → 指纹变了，但标题没变，不能算新增。"""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with store.Store(Path(tmp) / "t.db") as db:
                base = self._record(snippet="")
                db.annotate([base], run_id="r1")
                changed = self._record(snippet="中标金额 30 万元")
                self.assertNotEqual(base["fp"], changed["fp"])
                result = db.annotate([changed], run_id="r2")
                self.assertEqual(result["new"], 0)

    def test_mark_notified_and_pending(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with store.Store(Path(tmp) / "t.db") as db:
                record = self._record()
                db.annotate([record], run_id="r1")
                self.assertEqual(len(db.pending()), 1)
                changed = db.mark_notified([record["fp"]])
                self.assertEqual(changed, 1)
                self.assertEqual(db.pending(), [])
                # 重复标记不应再次计数（幂等）
                db.mark_notified([record["fp"]])
                self.assertEqual(len(db.pending()), 0)

    def test_prune_removes_stale_rows(self):
        import tempfile
        from datetime import date

        with tempfile.TemporaryDirectory() as tmp:
            with store.Store(Path(tmp) / "t.db") as db:
                db.annotate([self._record()], run_id="r1", today=date(2024, 1, 1))
                self.assertEqual(db.prune(keep_days=30, today=date(2026, 1, 1)), 1)
                self.assertEqual(db.stats()["total"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

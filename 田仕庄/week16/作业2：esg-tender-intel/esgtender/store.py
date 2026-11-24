"""已推送库（SQLite）：跨天增量、幂等写入、推送去重。

为什么需要它
------------
检索是「无状态」的：每次跑 ``--days 30`` 都会把窗口内的项目重新捞一遍，同一
条公告今天进报告、明天还进报告。做日报/周报时读者要的是「**这一期新增了
什么**」，而不是一份高度重合的快照。判断「新增」必须有个跨进程持久化的账本，
这就是本模块。

三条设计约束
------------
1. **幂等**。同一份记录重复写入不产生新行、不重复计数（``ON CONFLICT DO
   UPDATE``），所以中断后重跑、同一天跑两次都不会污染「新增」判断。
2. **身份用业务指纹 ``fp``，但 ``title_norm`` 也算「见过」**。``fp`` 含金额，
   同一条公告后补了中标金额就会变成新指纹；只按 ``fp`` 判断会把它又报成新增。因此标题归一化后已入库的，也视为见过（宁可少报「新增」，不要把旧项目
   当新闻推给用户）。
3. **只存摘要字段，不存原文**。库是索引不是存档；原文回查靠 ``records.json``
   与 ``source.url``。联系人/电话一律不入库（与 SKILL.md 的硬约束一致）。
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "tenders.db"
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    fp          TEXT PRIMARY KEY,
    id          TEXT NOT NULL,
    title       TEXT NOT NULL,
    title_norm  TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL,
    buyer       TEXT,
    amount_cny  TEXT,
    track_id    TEXT,
    track_name  TEXT,
    stage       TEXT,
    published   TEXT,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    seen_count  INTEGER NOT NULL DEFAULT 1,
    last_run    TEXT,
    notified_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_title_norm ON records(title_norm);
CREATE INDEX IF NOT EXISTS idx_records_last_seen ON records(last_seen);
CREATE INDEX IF NOT EXISTS idx_records_notified ON records(notified_at);

CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    started_at  TEXT NOT NULL,
    days        INTEGER,
    provider    TEXT,
    query_label TEXT,
    kept        INTEGER,
    new_count   INTEGER,
    notified    INTEGER
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _chunks(items: list[str], size: int = 400) -> Iterable[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class Store:
    """已推送库的读写门面。用 ``with Store(path) as store:`` 打开，退出时自动提交关闭。"""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._migrate()

    # ---------------------------------------------------------------- 基础
    def _migrate(self) -> None:
        self.conn.executescript(_SCHEMA)
        row = self.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
        self.conn.commit()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def close(self) -> None:
        try:
            self.conn.commit()
        finally:
            self.conn.close()

    # ---------------------------------------------------------------- 查询
    def known_fingerprints(self, fps: list[str]) -> dict[str, str]:
        """返回 ``{fp: first_seen}``，只含库中已有的记录。"""
        hits: dict[str, str] = {}
        for chunk in _chunks([fp for fp in fps if fp]):
            placeholders = ",".join("?" * len(chunk))
            rows = self.conn.execute(
                f"SELECT fp, first_seen FROM records WHERE fp IN ({placeholders})", chunk
            ).fetchall()
            for row in rows:
                hits[row["fp"]] = row["first_seen"]
        return hits

    def known_titles(self, titles: list[str]) -> dict[str, str]:
        """按归一化标题查已入库记录，用于兜住「金额补全导致指纹变化」。"""
        hits: dict[str, str] = {}
        for chunk in _chunks([t for t in titles if t]):
            placeholders = ",".join("?" * len(chunk))
            rows = self.conn.execute(
                f"SELECT title_norm, MIN(first_seen) AS first_seen FROM records "
                f"WHERE title_norm IN ({placeholders}) GROUP BY title_norm",
                chunk,
            ).fetchall()
            for row in rows:
                hits[row["title_norm"]] = row["first_seen"]
        return hits

    def pending(self, limit: int = 200) -> list[dict[str, Any]]:
        """已入库但从未推送过的记录（按首次发现时间升序）。"""
        rows = self.conn.execute(
            "SELECT * FROM records WHERE notified_at IS NULL ORDER BY first_seen LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT COUNT(*) AS total, MIN(first_seen) AS oldest, MAX(last_seen) AS newest, "
            "SUM(CASE WHEN notified_at IS NULL THEN 1 ELSE 0 END) AS pending FROM records"
        ).fetchone()
        return {
            "total": row["total"] or 0,
            "oldest": row["oldest"],
            "newest": row["newest"],
            "pending": row["pending"] or 0,
            "db": str(self.path),
        }

    # ---------------------------------------------------------------- 写入
    def annotate(
        self,
        records: list[dict[str, Any]],
        *,
        run_id: str,
        today: date | None = None,
    ) -> dict[str, Any]:
        """标注 ``flags.is_new`` / ``flags.first_seen``，然后幂等写入。

        返回 ``{"new": n, "seen": n, "new_ids": [...], "db": path, "stats": {...}}``。
        调用方据此决定「只报新增」还是「全量」。
        """
        stamp = (today or date.today()).isoformat()
        fps = [record.get("fp") or "" for record in records]
        titles = [record.get("title_norm") or "" for record in records]
        seen_fp = self.known_fingerprints(fps)
        seen_title = self.known_titles(titles)

        new_ids: list[str] = []
        new_count = 0
        for record in records:
            fp = record.get("fp") or ""
            title_norm = record.get("title_norm") or ""
            first_seen = seen_fp.get(fp) or seen_title.get(title_norm)
            flags = record.setdefault("flags", {})
            if first_seen:
                flags["is_new"] = False
                flags["first_seen"] = first_seen
            else:
                flags["is_new"] = True
                flags["first_seen"] = stamp
                new_count += 1
                new_ids.append(record.get("id") or "")

        self._upsert(records, run_id=run_id, stamp=stamp)
        return {
            "enabled": True,
            "new": new_count,
            "seen": len(records) - new_count,
            "new_ids": new_ids,
            "db": str(self.path),
            "stats": self.stats(),
        }

    def _upsert(self, records: list[dict[str, Any]], *, run_id: str, stamp: str) -> None:
        rows = []
        for record in records:
            fields = record.get("fields") or {}
            stage = (record.get("stage") or {}).get("label")
            rows.append(
                (
                    record.get("fp") or "",
                    record.get("id") or "",
                    (record.get("raw") or {}).get("title_clean")
                    or (record.get("raw") or {}).get("title", ""),
                    record.get("title_norm") or "",
                    (record.get("source") or {}).get("url", ""),
                    (fields.get("buyer") or {}).get("value"),
                    fields.get("amount_cny"),
                    (record.get("track") or {}).get("id"),
                    (record.get("track") or {}).get("name"),
                    stage,
                    (record.get("source") or {}).get("published"),
                    stamp,
                    stamp,
                    run_id,
                )
            )
        self.conn.executemany(
            """
            INSERT INTO records(
                fp, id, title, title_norm, url, buyer, amount_cny,
                track_id, track_name, stage, published,
                first_seen, last_seen, seen_count, last_run
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(fp) DO UPDATE SET
                id         = excluded.id,
                title      = excluded.title,
                title_norm = excluded.title_norm,
                url        = excluded.url,
                buyer      = COALESCE(excluded.buyer, records.buyer),
                amount_cny = COALESCE(excluded.amount_cny, records.amount_cny),
                track_id   = excluded.track_id,
                track_name = excluded.track_name,
                stage      = excluded.stage,
                published  = excluded.published,
                last_seen  = excluded.last_seen,
                seen_count = records.seen_count + 1,
                last_run   = excluded.last_run
            """,
            rows,
        )
        self.conn.commit()

    def record_run(
        self,
        *,
        run_id: str,
        meta: dict[str, Any],
        kept: int,
        new_count: int,
        notified: int = 0,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO runs(run_id, started_at, days, provider, query_label, kept, new_count, notified)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                kept      = excluded.kept,
                new_count = excluded.new_count,
                notified  = excluded.notified
            """,
            (
                run_id,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                meta.get("days"),
                meta.get("provider"),
                meta.get("query_label"),
                kept,
                new_count,
                notified,
            ),
        )
        self.conn.commit()

    def mark_notified(self, fps: list[str], *, when: datetime | None = None) -> int:
        """把记录标记为已推送。推送失败时**不要**调用，否则这批新增永远不会再被提醒。"""
        stamp = (when or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
        changed = 0
        for chunk in _chunks([fp for fp in fps if fp]):
            placeholders = ",".join("?" * len(chunk))
            cursor = self.conn.execute(
                f"UPDATE records SET notified_at = ? WHERE fp IN ({placeholders})",
                [stamp, *chunk],
            )
            changed += cursor.rowcount
        self.conn.commit()
        return changed

    def prune(self, keep_days: int = 730, *, today: date | None = None) -> int:
        """删除 ``keep_days`` 天没再出现过的记录。默认两年，与最长窗口对齐。"""
        cutoff = ((today or date.today()) - timedelta(days=max(keep_days, 1))).isoformat()
        cursor = self.conn.execute("DELETE FROM records WHERE last_seen < ?", (cutoff,))
        self.conn.commit()
        return cursor.rowcount

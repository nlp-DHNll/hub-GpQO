"""抓取候选链接的原文：页面标题、发布日期、正文，输出 pages.jsonl。结果带本地缓存，重跑不重复请求。

用法：
  python fetch.py --in results.jsonl list_items.jsonl --out pages.jsonl
                 [--since 2026-10-27 --until 2026-11-26] [--limit 80] [--max-chars 5000] [--concurrency 4]
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402


def fetch_one(rec: dict, max_chars: int) -> dict:
    out = dict(rec)
    try:
        r = c.http_get(rec["url"], timeout=25)
    except Exception as e:
        return out | {"fetch_ok": False, "fetch_error": type(e).__name__}
    if not r.get("ok"):
        return out | {"fetch_ok": False, "fetch_error": r.get("error") or f"HTTP {r.get('status')}"}
    html = r.get("html") or ""
    basis, page_date = next(iter(c.extract_dates(html, r.get("final_url") or rec["url"]).items()), ("", ""))
    text, stats = c.extract_main(html, max_chars)
    out.update(
        fetch_ok=True,
        final_url=r.get("final_url"),
        page_title=c.page_title(html),
        page_date=page_date,
        date_basis=basis,
        text=text,
        **stats,
    )
    return out


def merge_same_url(rows: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for r in rows:
        key = c.canonical_url(r["url"]) or r["url"]
        if key in seen:
            for q in r.get("queries", []) or [r.get("query", "")]:
                if q and q not in seen[key]["queries"]:
                    seen[key]["queries"].append(q)
            continue
        seen[key] = dict(r, queries=list(r.get("queries") or [r.get("query", "")]))
    return list(seen.values())


def fetch_all(indexed: list[tuple[int, dict]], max_chars: int, workers: int, delay: float) -> list[tuple[int, dict]]:
    """同一站点内串行抓取并留间隔，不同站点之间并行。返回 (原始序号, 记录)。"""
    groups: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for i, r in indexed:
        groups[c.host(r["url"])].append((i, r))

    def run(host: str) -> list[tuple[int, dict]]:
        out = []
        for n, (i, r) in enumerate(groups[host]):
            out.append((i, fetch_one(r, max_chars)))
            if n < len(groups[host]) - 1:
                time.sleep(delay)
        return out

    pairs = [pair for group in c.pmap(list(groups), run, workers) for pair in group]
    return sorted(pairs, key=lambda x: x[0])


def main() -> int:
    c.init()
    ap = argparse.ArgumentParser(description="抓取候选链接的原文")
    ap.add_argument("--in", dest="inp", nargs="+", required=True, help="输入文件，可给多个（搜索结果、栏目页扫描结果）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--since", help="给了时间窗时，已知在窗外的链接不再抓取")
    ap.add_argument("--until")
    ap.add_argument("--tolerance-days", type=int, default=3, help="日期解析有误差，窗口两端各放宽的天数")
    ap.add_argument("--limit", type=int, default=80, help="最多实际抓取的页面数")
    ap.add_argument("--max-chars", type=int, default=5000, help="每页保留的正文最大字数")
    ap.add_argument("--concurrency", type=int, default=4, help="同时抓取的站点数，同一站点内串行")
    ap.add_argument("--delay", type=float, default=0.5, help="同一站点两次请求的间隔秒数")
    args = ap.parse_args()

    rows = merge_same_url([r for p in args.inp for r in c.read_jsonl(p)])
    since = c.to_date(args.since) - timedelta(days=args.tolerance_days) if args.since else None
    until = c.to_date(args.until) + timedelta(days=args.tolerance_days) if args.until else None
    out_window: set[int] = set()
    if since and until:
        for i, r in enumerate(rows):
            d = c.to_date(r.get("published", ""))
            if d and not (since <= d <= until):
                out_window.add(i)
    todo = [i for i in range(len(rows)) if i not in out_window][: args.limit]

    fetched = dict(fetch_all([(i, rows[i]) for i in todo], args.max_chars, args.concurrency, args.delay))
    ok = 0
    for i, r in enumerate(rows):
        if i in fetched:
            rows[i] = fetched[i]
            ok += bool(fetched[i].get("fetch_ok"))
        else:
            reason = "已知在时间窗外" if i in out_window else "超出抓取上限"
            rows[i] = r | {"fetch_ok": False, "fetch_skipped": reason}
    n = c.write_jsonl(args.out, rows)
    fail = sum(1 for r in rows if r.get("fetch_ok") is False and r.get("fetch_error"))
    print(f"[fetch] 输入={n} 抓取成功={ok} 抓取失败={fail} 未抓取={n - ok - fail} 输出={args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(c.guard("fetch", main))

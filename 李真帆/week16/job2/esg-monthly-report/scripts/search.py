"""联网搜索：把一组检索式交给搜索源，输出统一格式的结果。

搜索源按 BOCHA_API_KEY、TAVILY_API_KEY、SERPER_API_KEY 的顺序自动选择，也可用 --provider 指定。
都没有配置时用 --provider file，读取 agent 用内置搜索导出的结果文件
（TSV，带表头，列：query、title、url、published、snippet；也接受每行一个 JSON 对象的 JSONL）。

用法：
  python search.py --plan queries.txt --out results.jsonl --days 30
  python search.py --provider file --raw agent_results.tsv --out results.jsonl
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

ENDPOINTS = {
    "bocha": "https://api.bochaai.com/v1/web-search",
    "tavily": "https://api.tavily.com/search",
    "serper": "https://google.serper.dev/search",
}
KEYS = {"bocha": "BOCHA_API_KEY", "tavily": "TAVILY_API_KEY", "serper": "SERPER_API_KEY"}
FIELDS = {
    "title": ("name", "title"),
    "url": ("url", "link"),
    "snippet": ("summary", "snippet", "content", "description"),
    "published": ("datePublished", "publish_time", "published", "published_date", "publishDate", "date"),
}


def _first(d: dict, names: tuple) -> str:
    for n in names:
        if d.get(n):
            return str(d[n])
    return ""


def _normalize(items: list, query: str, provider: str) -> list[dict]:
    rows = []
    for i, it in enumerate(items or [], 1):
        url = _first(it, FIELDS["url"])
        if not url.startswith("http"):
            continue
        rows.append({
            "query": query, "rank": i, "title": _first(it, FIELDS["title"])[:200], "url": url,
            "snippet": _first(it, FIELDS["snippet"])[:400],
            "site": _first(it, ("siteName", "site", "source", "media")) or c.host(url),
            "published": c.normalize_date(_first(it, FIELDS["published"])), "provider": provider,
        })
    return rows


def _freshness(days: int | None, table: tuple) -> str:
    return next((v for d, v in table if days and days <= d), "")


def search(query: str, provider: str, count: int, days: int | None) -> list[dict]:
    key = os.environ.get(KEYS[provider], "")
    if provider == "bocha":
        body = {"query": query, "summary": True, "count": count, "freshness": _freshness(
            days, ((1, "oneDay"), (7, "oneWeek"), (31, "oneMonth"), (366, "oneYear"))) or "noLimit"}
        resp = c.session().post(ENDPOINTS["bocha"], json=body, headers={"Authorization": f"Bearer {key}"}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") not in (None, 200):
            raise RuntimeError(f"code={data.get('code')} msg={data.get('msg')}")
        pages = (data.get("data") or {}).get("webPages") or (data.get("data") or {}).get("webpage") or []
        items = pages.get("value", []) if isinstance(pages, dict) else pages
    elif provider == "tavily":
        body = {"api_key": key, "query": query, "max_results": count, "include_answer": False,
                "search_depth": "basic"}
        if days and days <= 31:
            body.update(topic="news", days=days)
        resp = c.session().post(ENDPOINTS["tavily"], json=body, timeout=30)
        resp.raise_for_status()
        items = resp.json().get("results") or []
    else:
        body = {"q": query, "num": count}
        window = _freshness(days, ((1, "qdr:d"), (7, "qdr:w"), (31, "qdr:m"), (366, "qdr:y")))
        if window:
            body["tbs"] = window
        resp = c.session().post(ENDPOINTS["serper"], json=body, headers={"X-API-KEY": key}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        items = (data.get("news") or []) + (data.get("organic") or [])
    return _normalize(items, query, provider)


def pick_provider(explicit: str | None = None) -> str:
    """指定了就用指定的；否则按博查、Tavily、Serper 的顺序找已配置的 key；都没有时返回 file。"""
    if explicit:
        return explicit
    return next((p for p in KEYS if os.environ.get(KEYS[p])), "file")


def read_raw(path: str) -> list[dict]:
    lines = [ln for ln in Path(path).read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
    if not lines:
        return []
    rows = []
    if lines[0].lstrip().startswith("{"):
        for d in (json.loads(ln) for ln in lines):
            rows.append({
                "query": d.get("query", ""), "rank": 0, "title": d.get("title", ""), "url": d.get("url", ""),
                "snippet": (d.get("snippet") or "")[:400], "site": d.get("site") or c.host(d.get("url", "")),
                "published": c.normalize_date(d.get("published")), "provider": "file",
            })
        return rows
    for i, d in enumerate(csv.DictReader(lines, delimiter="\t"), 1):
        published = d.get("published") or d.get("date") or d.get("time") or ""
        rows.append({
            "query": d.get("query", ""), "rank": i, "title": (d.get("title") or "").strip(),
            "url": (d.get("url") or "").strip(), "snippet": (d.get("snippet") or "")[:400],
            "site": d.get("site") or c.host(d.get("url", "")), "published": c.normalize_date(published),
            "provider": "file",
        })
    return rows


def dedupe(rows: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for r in rows:
        key = c.canonical_url(r["url"]) or c.norm_title(r["title"])
        if not key:
            continue
        if key in seen:
            seen[key]["hits"] += 1
            if r["query"] and r["query"] not in seen[key]["queries"]:
                seen[key]["queries"].append(r["query"])
            continue
        item = dict(r, queries=[r["query"]], hits=1)
        seen[key] = item
    return list(seen.values())


def main() -> int:
    c.init()
    ap = argparse.ArgumentParser(description="联网搜索并输出统一格式的结果")
    ap.add_argument("--plan", help="检索式文件，一行一个，# 开头为注释")
    ap.add_argument("--query", action="append", default=[], help="单个检索式，可重复")
    ap.add_argument("--raw", help="--provider file 时的输入文件（TSV 或 JSONL）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--provider", choices=["bocha", "tavily", "serper", "file"])
    ap.add_argument("--days", type=int, help="只要最近 N 天的结果，搜索源支持时生效")
    ap.add_argument("--count", type=int, default=10, help="每条检索式返回的条数")
    ap.add_argument("--delay", type=float, default=0.4, help="两次请求之间的间隔秒数")
    args = ap.parse_args()

    provider = pick_provider(args.provider)
    if provider == "file":
        if not args.raw:
            ap.error("未配置搜索 API key。请设置 BOCHA_API_KEY、TAVILY_API_KEY 或 SERPER_API_KEY，"
                     "或用 --provider file --raw <文件> 传入 agent 导出的搜索结果。")
        rows = read_raw(args.raw)
    else:
        queries = list(args.query)
        if args.plan:
            queries += [ln.strip() for ln in Path(args.plan).read_text(encoding="utf-8-sig").splitlines()
                        if ln.strip() and not ln.startswith("#")]
        if not queries:
            ap.error("没有检索式：用 --plan 或 --query 提供")
        rows, failed = [], 0
        for i, q in enumerate(queries, 1):
            try:
                rows += search(q, provider, args.count, args.days)
            except Exception as e:
                failed += 1
                print(f"[search] 失败「{q}」: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
            if i < len(queries):
                time.sleep(args.delay)
        if failed:
            print(f"[search] 有 {failed} 条检索式失败", file=sys.stderr)
    raw_count = len(rows)
    rows = dedupe(rows)
    n = c.write_jsonl(args.out, rows)
    print(f"[search] provider={provider} 原始条数={raw_count} 去重后={n} 输出={args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(c.guard("search", main))

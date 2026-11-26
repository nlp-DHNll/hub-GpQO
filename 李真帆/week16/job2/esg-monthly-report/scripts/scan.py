"""扫描权威栏目页，抽出时间窗内、与 ESG 相关的条目（标题、日期、链接）。

栏目页清单是一个 YAML 列表，每项含 name 和 url。

用法：
  python scan.py --lists references/source_lists.yaml --out list_items.jsonl
                 --since 2026-10-27 --until 2026-11-26 --rules references/keywords.yaml
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402


def _node_text(node) -> str:
    return node.get_text(" ", strip=True) if hasattr(node, "get_text") else str(node)


def date_near(anchor) -> str:
    """日期常紧挨着标题：先看标题后面的兄弟节点，再看前面的，最后看父节点。"""
    fwd, node = "", anchor.next_sibling
    while node is not None and len(fwd) < 120:
        if getattr(node, "name", None) == "a":
            break
        fwd += _node_text(node)
        node = node.next_sibling
    d = c.find_date_in(fwd)
    if d:
        return d
    back, node = "", anchor.previous_sibling
    while node is not None and len(back) < 60:
        if getattr(node, "name", None) == "a":
            break
        back = _node_text(node) + back
        node = node.previous_sibling
    return c.find_date_in(back) or c.find_date_in(_node_text(anchor.parent)[:200])


def scan_list(item: dict) -> list[dict]:
    name, url = item["name"], item["url"]
    try:
        rec = c.http_get(url, timeout=25)
    except Exception as e:
        print(f"[scan] {name}: {type(e).__name__}", file=sys.stderr)
        return []
    if not rec.get("ok"):
        print(f"[scan] {name}: 读取失败（{rec.get('error') or rec.get('status')}）", file=sys.stderr)
        return []
    found, seen = [], set()
    for a in c.soup_of(rec["html"]).find_all("a", href=True):
        title = re.sub(r"\s+", " ", a.get("title") or a.get_text(" ", strip=True) or "").strip()
        href = a["href"].strip()
        if len(title) < 8 or href.startswith(("#", "javascript")):
            continue
        link = urljoin(rec.get("final_url") or url, href)
        if link in seen:
            continue
        d = date_near(a)
        if not d:
            continue
        seen.add(link)
        found.append({"list_name": name, "list_url": url, "title": title, "url": link, "published": d,
                      "site": c.host(link)})
    return found


def main() -> int:
    c.init()
    ap = argparse.ArgumentParser(description="扫描权威栏目页，抽出时间窗内的条目")
    ap.add_argument("--lists", required=True, help="栏目页清单 YAML")
    ap.add_argument("--out", required=True)
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", required=True)
    ap.add_argument("--rules", help="关键词 YAML，给出时只保留标题命中关键词的条目")
    args = ap.parse_args()

    since, until = c.to_date(args.since), c.to_date(args.until)
    keywords = [kw.lower() for kws in c.load_yaml(args.rules)["include"].values() for kw in kws] if args.rules else []

    total, kept, hits = 0, [], 0
    for item in c.load_yaml(args.lists):
        items = scan_list(item)
        total += len(items)
        for it in items:
            if not (since <= c.to_date(it["published"]) <= until):
                continue
            matched = [kw for kw in keywords if kw in it["title"].lower()]
            if keywords and not matched:
                continue
            hits += 1
            kept.append(dict(it, matched=matched, provider="list"))
    n = c.write_jsonl(args.out, kept)
    print(f"[scan] 栏目页条目={total} 时间窗内且关键词命中={hits} 输出={args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(c.guard("scan", main))

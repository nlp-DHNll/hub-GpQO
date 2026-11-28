"""筛选线索：去重、时间窗、关键词相关性。两种模式：news（月报线索）、bid（招投标线索）。

用法：
  python filter.py --mode news --in pages.jsonl --out candidates.jsonl
                 --since 2026-10-27 --until 2026-11-26 --rules references/keywords.yaml
  python filter.py --mode bid --in results.jsonl --out bid_candidates.jsonl --rules references/keywords.yaml
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402


def filter_news(rows: list[dict], rules: dict, since: date, until: date, tol: int, min_score: int):
    keywords = sorted({kw.lower() for kws in rules.get("include", {}).values() for kw in kws})
    block = [h.lower() for h in rules.get("block_hosts", [])]
    noise = [k.lower() for k in rules.get("noise_title", [])]
    aliases = [a.lower() for a in rules.get("client_aliases", [])]
    subjects = [a.lower() for a in rules.get("subject_aliases", [])]
    out, rejects, seen_url, seen_title = [], [], set(), []
    for r in rows:
        list_title, page_title = r.get("title") or "", r.get("page_title") or ""
        text = r.get("text") or ""
        key = c.canonical_url(r.get("url", ""))
        short = c.norm_title(list_title or page_title)
        title_low = f"{list_title} {page_title}".lower()
        reason = ""
        if not r.get("fetch_ok"):
            reason = f"未抓到原文：{r.get('fetch_error') or r.get('fetch_skipped') or '未知原因'}"
        elif not key:
            reason = "无有效链接"
        elif key in seen_url:
            reason = "重复链接"
        elif any(c.host(r["url"]).endswith(h) for h in block):
            reason = "信源黑名单"
        elif len(short) >= 8 and any(c.similar(short, t) >= 0.9 for t in seen_title):
            reason = "重复标题"
        elif r.get("link_count", 0) >= 40 and r.get("link_ratio", 0) >= 0.6:
            reason = "列表页或导航页"
        elif any(k in title_low for k in noise) and not any(a in title_low for a in aliases):
            reason = "常规审批公示"

        search_date, page_date = r.get("published") or "", r.get("page_date") or ""
        strong = r.get("date_basis") in ("meta", "label") and page_date
        published = (page_date if strong else search_date) or page_date or search_date
        d = c.to_date(published)
        if not reason and d and not (since - timedelta(days=tol) <= d <= until):
            reason = "时间窗外"
        score, hits = 0, []
        if not reason:
            hits = [kw for kw in keywords if kw in title_low]
            hits = [kw for kw in hits if not any(kw != other and kw in other for other in hits)]
            body = f"{title_low}\n{text.lower()}"
            score = 3 * len(hits) + min(sum(1 for kw in keywords if kw in body and kw not in hits), 10)
            subjects_hit = [a for a in subjects if a in title_low]
            if subjects_hit:
                hits += subjects_hit
                score = max(score, min_score)
            if score < min_score:
                reason = "关键词不足"
        entry = dict(r, published=published, score=score, keyword_hits=hits,
                     date_ok=None if not d else since <= d <= until,
                     date_conflict=bool(strong and search_date and c.to_date(search_date)
                                       and abs((c.to_date(page_date) - c.to_date(search_date)).days) > 3))
        if reason:
            rejects.append({"title": r.get("title") or title, "url": r.get("url"), "reason": reason})
        else:
            seen_url.add(key)
            seen_title.append(short)
            out.append(entry)
    return out, rejects


def filter_bid(rows: list[dict], rules: dict):
    core = [k.lower() for k in rules["include"].get("core", [])]
    extended = [k.lower() for k in rules["include"].get("extended", [])]
    exclude = [k.lower() for k in rules.get("exclude", [])]
    context = [k.lower() for k in rules.get("co2_context", [])]
    out, rejects, seen = [], [], set()
    for r in rows:
        title = (r.get("title") or "").strip()
        low = title.lower()
        key = c.canonical_url(r.get("url", ""))
        reason, tier, hits = "", "", []
        if not key:
            reason = "无有效链接"
        elif key in seen or c.norm_title(title) in seen:
            reason = "重复"
        else:
            bad = [k for k in exclude if k in low]
            if bad:
                reason = f"排除词：{bad[0]}"
            elif "二氧化碳" in title and not any(k in low for k in context):
                reason = "二氧化碳（非 ESG 语境）"
            else:
                hits = [k for k in core if k in low]
                if hits:
                    tier = "core"
                else:
                    hits = [k for k in extended if k in low]
                    tier = "extended" if hits else ""
                    if not hits:
                        reason = "未命中关键词"
        entry = dict(r, tier=tier, keyword_hits=hits)
        if reason:
            rejects.append({"title": title, "url": r.get("url"), "reason": reason})
        else:
            seen.add(key)
            seen.add(c.norm_title(title))
            out.append(entry)
    return out, rejects


def main() -> int:
    c.init()
    ap = argparse.ArgumentParser(description="筛选线索")
    ap.add_argument("--mode", choices=["news", "bid"], required=True)
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rules", required=True, help="关键词 YAML")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--tolerance-days", type=int, default=3, help="日期解析有误差，窗口两端各放宽的天数")
    ap.add_argument("--min-score", type=int, default=3, help="news 模式的关键词分数下限，3 表示标题命中一个关键词即可")
    args = ap.parse_args()

    rows = c.read_jsonl(args.inp)
    rules = c.load_yaml(args.rules)
    if args.mode == "news":
        if not (args.since and args.until):
            ap.error("news 模式需要 --since 和 --until")
        kept, rejects = filter_news(rows, rules, c.to_date(args.since), c.to_date(args.until),
                                    args.tolerance_days, args.min_score)
    else:
        kept, rejects = filter_bid(rows, rules)
    n = c.write_jsonl(args.out, kept)
    n_rej = c.write_jsonl(str(Path(args.out).with_name(Path(args.out).stem + ".rejected.jsonl")), rejects)
    reasons = "；".join(f"{k} {v} 条" for k, v in Counter(x["reason"].split("：")[0] for x in rejects).most_common())
    if args.mode == "news":
        dated = sum(1 for r in kept if r.get("date_ok"))
        conflict = sum(1 for r in kept if r.get("date_conflict"))
        print(f"[filter] 输入={len(rows)} 保留={n} 剔除={n_rej}（{reasons}）；保留项里时间窗内={dated} 日期无法确认={n - dated} 页面日期与搜索日期不一致={conflict}")
    else:
        tiers = Counter(r["tier"] for r in kept)
        print(f"[filter] 输入={len(rows)} 保留={n}（核心词 {tiers.get('core', 0)}，延伸词 {tiers.get('extended', 0)}）剔除={n_rej}（{reasons}）")
    return 0


if __name__ == "__main__":
    sys.exit(c.guard("filter", main))

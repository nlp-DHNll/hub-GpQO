"""复核一份报告：引用是否闭合、来源能否核验、日期是否在时间窗内，并给出指标。两个版本的报告都用它量。

用法：
  python check_report.py --report report.md --sources sources.jsonl --out check.json
                        [--since 2026-10-27 --until 2026-11-26] [--stats stats.json]
                        [--require 本期要点,政策,评级,行业,公司,对标,行动建议] [--no-fetch]
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

CITE_RE = re.compile(r"\[(S\d+(?:\s*[,，\-–~]\s*S?\d+)*)\]|(?<![A-Za-z0-9])S\d+(?![A-Za-z0-9])")
APPENDIX_RE = re.compile(r"^#{1,3}\s*附录", re.M)
LIST_RE = re.compile(r"^(?:[-*+]|\d+[.、)])\s+\S")


def expand_citation(match: re.Match) -> list[str]:
    """把 [S3]、[S4,S5]、[S4-S6]、表格来源列里的裸 S4，统一展开成编号列表。"""
    inner = match.group(1)
    if inner is None:
        return [match.group(0)]
    ids = []
    for part in re.split(r"[,，]", match.group(1)):
        part = part.strip()
        m = re.match(r"S(\d+)\s*[\-–~]\s*S?(\d+)$", part)
        if m:
            ids += [f"S{i}" for i in range(int(m.group(1)), int(m.group(2)) + 1)]
        elif part:
            ids.append(part if part.startswith("S") else f"S{part}")
    return ids


def split_report(text: str) -> tuple[str, str]:
    m = APPENDIX_RE.search(text)
    return (text[: m.start()].rstrip(), text[m.start():]) if m else (text, "")


def fact_units(body: str) -> list[str]:
    """事实单元：列表项和表格的数据行（不含表头与分隔行）。"""
    lines, out, in_code = body.splitlines(), [], False
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not s:
            continue
        if s.startswith("|"):
            if re.fullmatch(r"\|?[\s\-:|]+\|?", s):
                continue
            nxt = next((x.strip() for x in lines[i + 1:] if x.strip()), "")
            if re.fullmatch(r"\|?[\s\-:|]+\|?", nxt):
                continue
            if len([x for x in s.strip("|").split("|") if x.strip()]) >= 3:
                out.append(s)
        elif LIST_RE.match(s):
            out.append(s)
    return out


def title_ratio(mine: str, haystack: str) -> float:
    """来源标题的字符二元组，在页面标题和正文里能找到的比例。"""
    mine, hay = c.norm_title(mine), c.norm_title(haystack)
    if not mine or not hay:
        return 0.0
    if len(mine) <= 3:
        return 1.0 if mine in hay else 0.0
    grams = {mine[i:i + 2] for i in range(len(mine) - 1)}
    return sum(1 for g in grams if g in hay) / len(grams)


def verify_source(s: dict) -> dict:
    out = {"id": s.get("id"), "status": None, "title_ratio": None, "date_match": None, "page_dates": [],
           "page_title": "", "unreadable": False, "error": ""}
    try:
        r = c.http_get(s["url"], timeout=20)
    except Exception as e:
        out["error"] = type(e).__name__
        return out
    out["status"] = r.get("status")
    if not r.get("ok"):
        out["error"] = r.get("error") or f"HTTP {r.get('status')}"
        return out
    html = r.get("html") or ""
    url = r.get("final_url") or s["url"]
    text = c.main_text(html, 4000)
    out["page_title"] = c.page_title(html)[:80]
    out["unreadable"] = html.lstrip()[:5].upper().startswith("%PDF") or len(text) < 200
    out["title_ratio"] = round(title_ratio(s.get("title"), out["page_title"] + text), 2)
    dates = {c.to_date(x) for x in c.extract_dates(html, url).values()} - {None}
    out["page_dates"] = sorted(d.isoformat() for d in dates)
    sd = c.to_date(s.get("published", ""))
    if sd and dates:
        out["date_match"] = any(abs((d - sd).days) <= 3 for d in dates)
    return out


def classify(v: dict) -> str:
    """verified 标题对得上；date_mismatch 标题对得上但日期不一致（多为转载稿）；
    partial 标题只对上一部分（改写过或正文不可见），需人工看；unreadable 页面是 PDF 或脚本渲染；
    unconfirmed 标题对不上；unreachable 打不开。"""
    if v["status"] != 200 or v["title_ratio"] is None:
        return "unreachable"
    if v["unreadable"]:
        return "unreadable"
    if v["title_ratio"] >= 0.6:
        return "verified" if v["date_match"] is not False else "date_mismatch"
    return "partial" if v["title_ratio"] >= 0.3 else "unconfirmed"


def pct(a: int, b: int) -> float:
    return round(100 * a / b, 1) if b else 0.0


def main() -> int:
    c.init()
    ap = argparse.ArgumentParser(description="复核报告：引用、来源可核验性、时间窗、结构")
    ap.add_argument("--report", required=True)
    ap.add_argument("--sources", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--stats", help="stats.py 输出的统计 JSON，给出时核对正文里的数字")
    ap.add_argument("--require", default="", help="必须出现的章节关键词，逗号分隔")
    ap.add_argument("--no-fetch", action="store_true", help="不访问网络，只做本地检查")
    args = ap.parse_args()

    text = Path(args.report).read_text(encoding="utf-8-sig")
    body, _ = split_report(text)
    sources = c.read_jsonl(args.sources)
    ids = [s.get("id") for s in sources]
    result: dict = {"report": args.report}

    dup_url, dup_title, seen_url, seen_title = [], [], {}, []
    for s in sources:
        k = c.canonical_url(s.get("url", ""))
        if k in seen_url:
            dup_url.append(s["id"])
        else:
            seen_url[k] = s["id"]
        nt = c.norm_title(s.get("title"))
        if len(nt) >= 8 and any(c.similar(nt, t) >= 0.9 for t in seen_title):
            dup_title.append(s["id"])
        else:
            seen_title.append(nt)
    since, until = c.to_date(args.since or ""), c.to_date(args.until or "")
    window = [s for s in sources if (d := c.to_date(s.get("published", ""))) and (not since or since - timedelta(days=3) <= d)
              and (not until or d <= until)]
    result["sources"] = {
        "total": len(sources), "unique_url": len(seen_url), "duplicate_url": dup_url, "duplicate_title": dup_title,
        "missing_date": sum(1 for s in sources if not c.to_date(s.get("published", ""))),
        "in_window": len(window), "out_of_window": len(sources) - sum(1 for s in sources if not c.to_date(s.get("published", ""))) - len(window)
        if since or until else None,
        "unverified_flag": sum(1 for s in sources if s.get("verified") is False),
    }

    cited: list[str] = []
    for m in CITE_RE.finditer(body):
        cited += expand_citation(m)
    id_set = set(ids)
    units = fact_units(body)
    units_cited = sum(1 for u in units if CITE_RE.search(u))
    result["citations"] = {
        "total": len(cited), "distinct": len(set(cited)), "dangling": sorted(set(cited) - id_set),
        "unused": sorted(id_set - set(cited)), "units": len(units), "units_cited": units_cited,
        "coverage": pct(units_cited, len(units)),
    }

    if args.no_fetch:
        result["verification"] = {"skipped": True}
    else:
        detail = c.pmap(sources, verify_source, 4)
        buckets: dict[str, list] = {"verified": [], "date_mismatch": [], "partial": [], "unreadable": [],
                                   "unconfirmed": [], "unreachable": []}
        for v in detail:
            buckets[classify(v)].append(v["id"])
        result["verification"] = {k: v for k, v in buckets.items()} | {
            "verified_rate": pct(len(buckets["verified"]), len(sources)),
            "content_verified_rate": pct(len(buckets["verified"]) + len(buckets["date_mismatch"]), len(sources)),
            "detail": detail}

    heads = [ln.strip("#").strip() for ln in body.splitlines() if ln.startswith("#")]
    required = [k for k in re.split(r"[,，]", args.require) if k.strip()]
    result["structure"] = {
        "chars": len(re.findall(r"[\u4e00-\u9fff]", body)), "headings": heads,
        "tables": sum(1 for ln in body.splitlines() if re.fullmatch(r"\|?[\s\-:|]+\|?", ln.strip())),
        "missing_sections": [k for k in required if not any(k in h for h in heads)],
    }

    if args.stats:
        import json
        stats = json.loads(Path(args.stats).read_text(encoding="utf-8"))
        missing = []
        for k, v in stats.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                num = f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else f"{v:,}"
                if num not in text and f"{v:,}".replace(",", "") not in text.replace(",", ""):
                    missing.append(f"{k}={num}")
        result["numbers"] = {"checked": sum(1 for v in stats.values() if isinstance(v, (int, float)) and not isinstance(v, bool)),
                             "missing": missing}

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(__import__("json").dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    src, cit = result["sources"], result["citations"]
    window_note = f"，时间窗内 {src['in_window']}/{src['total']}" if src["out_of_window"] is not None else ""
    print(f"[check] 来源 {src['total']} 条：缺日期 {src['missing_date']}，重复链接 {len(dup_url)}，重复标题 {len(dup_title)}{window_note}")
    if not args.no_fetch:
        ver = result["verification"]
        print(f"[check] 可核验 {len(ver['verified'])} 条（{ver['verified_rate']}%），标题对得上但日期不一致 "
              f"{len(ver['date_mismatch'])} 条，标题部分对得上 {len(ver['partial'])} 条（需人工看），"
              f"标题对不上 {len(ver['unconfirmed'])} 条，页面无法解析 {len(ver['unreadable'])} 条，"
              f"打不开 {len(ver['unreachable'])} 条")
    print(f"[check] 引用 {cit['total']} 处：悬空 {len(cit['dangling'])}，未被引用的来源 {len(cit['unused'])}；"
          f"事实单元 {cit['units']} 条，带引用 {cit['units_cited']} 条（{cit['coverage']}%）")
    st = result["structure"]
    print(f"[check] 正文 {st['chars']} 字，表格 {st['tables']} 个；缺失章节：{'、'.join(st['missing_sections']) or '无'}")
    if "numbers" in result:
        print(f"[check] 统计数字 {result['numbers']['checked']} 项，正文里找不到的：{'、'.join(result['numbers']['missing']) or '无'}")
    return 0


if __name__ == "__main__":
    sys.exit(c.guard("check_report", main))

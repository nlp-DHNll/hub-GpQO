"""监控新增招标：取最近 N 天的搜索结果，关键词筛选，与已推送记录比对，生成日报，可选推送，更新状态。

默认只用关键词规则，不调用大模型，可以挂到计划任务上无人值守。
搜索结果有两个来源：配了搜索 API key 时 monitor.py 自己搜索；否则用 --results 传入 search.py 的结果文件。
加 --fetch --llm 时会抓取新增条目的原文，并用大模型补齐截止时间、金额、中标人等字段。

用法：
  python monitor.py --state seen.json --days 7 --out-dir daily --rules references/keywords.yaml
  python monitor.py --state seen.json --results monitor_results.jsonl --out-dir daily
                 --rules references/keywords.yaml --fetch --llm
选项：--webhook 企业微信、飞书或钉钉机器人地址；--max-queries 最多使用的检索式数量
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402
import fetch as fetch_mod  # noqa: E402
import filter as filter_mod  # noqa: E402
import search as search_mod  # noqa: E402


def collect(args, since: date, until: date) -> list[dict]:
    if args.results:
        rows = c.read_jsonl(args.results)
        print(f"[monitor] 读入搜索结果 {len(rows)} 条")
        return rows
    provider = search_mod.pick_provider(args.provider)
    if provider == "file":
        sys.exit("未配置搜索 API key：请设置 BOCHA_API_KEY、TAVILY_API_KEY 或 SERPER_API_KEY，"
                "或用 --results 传入搜索结果。")
    rules = c.load_yaml(args.rules)
    keywords = rules["include"]["core"][: args.keywords]
    queries = [f"{kw} {word}" for kw in keywords
               for word in rules.get("notice_words", ["招标公告", "中标公告"])][: args.max_queries]
    rows, failed = [], 0
    for q in queries:
        try:
            rows += search_mod.search(q, provider, args.count, (until - since).days + 1)
        except Exception as e:
            failed += 1
            print(f"[monitor] 检索失败「{q}」: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
    print(f"[monitor] 检索式 {len(queries)} 条，失败 {failed} 条，原始结果 {len(rows)} 条")
    return search_mod.dedupe(rows)


def cell(value) -> str:
    return (str(value or "").replace("|", "／").replace("\n", " ").strip()) or "未获取"


def build_brief(items: list[dict], since: date, until: date) -> str:
    cid = {id(r): f"S{i}" for i, r in enumerate(items, 1)}
    cards = [r for r in items if r.get("card")]
    tender = [r for r in cards if r["card"].get("notice_type") == "tender"]
    award = [r for r in cards if r["card"].get("notice_type") == "award"]
    other = [r for r in items if not r.get("card")]
    count = (f"新增招标 {len(tender)} 条　|　新增中标 {len(award)} 条" if cards
             else f"新增线索 {len(items)} 条（关键词命中，未做结构化提取）")
    lines = [f"# ESG 招标日报 · {until.isoformat()}", "",
             f"**统计区间：** {since.isoformat()} 至 {until.isoformat()}　|　{count}", ""]
    if not cards:
        lines += ["| 日期 | 标题 | 来源 | 链接 |", "|---|---|---|---|"]
        lines += [f"| {cell(r.get('published'))} | {cell(r.get('title'))[:90]} | {cell(r.get('site'))} | [{cid[id(r)]}] |"
                  for r in items[:60]] or ["| （本期无新增） | | | |"]
        lines += ["", "说明：以上是关键词命中的线索，使用前请打开链接核对。"]
    else:
        lines += ["## 新增招标机会", "", "| 截止时间 | 项目 | 招标人 | 预算或最高限价 | 类型 | 链接 |", "|---|---|---|---|---|---|"]
        for r in tender:
            k = r["card"]
            lines.append(f"| {cell(k.get('deadline'))} | {cell(k.get('project') or r.get('title'))[:80]} | {cell(k.get('purchaser'))} | "
                         f"{cell(k.get('budget_text'))} | {k.get('project_type', '')} | [{cid[id(r)]}] |")
        if not tender:
            lines.append("| （本期无新增） | | | | | |")
        lines += ["", "## 新增中标结果", "", "| 公告日期 | 项目 | 招标人 | 中标人 | 金额 | 类型 | 链接 |", "|---|---|---|---|---|---|---|"]
        for r in award:
            k = r["card"]
            amount = f"{k['amount_wan']:g} 万元" if k.get("amount_wan") is not None else cell(k.get("amount_text"))
            lines.append(f"| {cell(r.get('published'))} | {cell(k.get('project') or r.get('title'))[:80]} | {cell(k.get('purchaser'))} | "
                         f"{cell(k.get('winner'))} | {amount} | {k.get('project_type', '')} | [{cid[id(r)]}] |")
        if not award:
            lines.append("| （本期无新增） | | | | | | |")
        if other:
            lines += ["", "## 未能结构化的线索", "", "| 日期 | 标题 | 链接 |", "|---|---|---|"]
            lines += [f"| {cell(r.get('published'))} | {cell(r.get('title'))[:80]} | [{cid[id(r)]}] |" for r in other]
    tips = []
    if not items:
        tips.append("本期无新增。")
    else:
        soon = [r for r in tender if (d := c.to_date(r["card"].get("deadline", ""))) and until <= d <= until + timedelta(days=3)]
        if soon:
            tips.append("3 天内截止：" + "；".join(cell(r["card"].get("project"))[:40] for r in soon))
        biggest = max((r for r in award if r["card"].get("amount_wan")), key=lambda r: r["card"]["amount_wan"], default=None)
        if biggest:
            tips.append(f"本期金额最大：{cell(biggest['card'].get('project'))[:40]}，{biggest['card']['amount_wan']:g} 万元。")
        pending = [r for r in award if "候选人" in (r.get("title") or "") or "候选人" in cell(r["card"].get("amount_text"))]
        if pending:
            tips.append(f"{len(pending)} 条中标结果处于候选人公示阶段，最终金额可能变动。")
        tips.append("线索来自公开检索，不是全量；使用前打开链接核对。")
    return "\n".join(lines + ["", "## 提示", ""] + [f"- {t}" for t in tips] + [""])


def build_sources(items: list[dict]) -> list[dict]:
    rows = []
    for r in items:
        k = r.get("card") or {}
        rows.append({"title": k.get("project") or r.get("title"), "publisher": k.get("purchaser") or r.get("site") or "",
                     "published": r.get("published", ""), "url": r.get("url", ""), "section": "bid",
                     "notice_type": k.get("notice_type", ""), "verified": bool(r.get("text"))})
    return [dict(id=f"S{i}", **row) for i, row in enumerate(rows, 1)]


def push(webhook: str, title: str, text: str) -> None:
    if "qyapi.weixin.qq.com" in webhook:
        payload = {"msgtype": "markdown", "markdown": {"content": text[:4000]}}
    elif "open.feishu.cn" in webhook:
        payload = {"msg_type": "text", "content": {"text": f"{title}\n{text}"[:4000]}}
    elif "dingtalk.com" in webhook:
        payload = {"msgtype": "markdown", "markdown": {"title": title, "text": text}}
    else:
        payload = {"title": title, "text": text}
    r = c.session().post(webhook, json=payload, timeout=20)
    r.raise_for_status()
    print(f"[monitor] 已推送：{c.host(webhook)} 返回 {r.text[:120]}")


def main() -> int:
    c.init()
    ap = argparse.ArgumentParser(description="监控新增的 ESG 相关招标")
    ap.add_argument("--state", required=True, help="已推送记录文件 seen.json")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--rules", required=True)
    ap.add_argument("--days", type=int, help="回看的天数；缺省按上次运行日期")
    ap.add_argument("--results", help="已有的搜索结果文件；给出时不再联网搜索")
    ap.add_argument("--provider")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--keywords", type=int, default=8, help="使用前 N 个核心关键词拼检索式")
    ap.add_argument("--max-queries", type=int, default=16)
    ap.add_argument("--fetch", action="store_true", help="抓取新增条目的原文")
    ap.add_argument("--llm", action="store_true", help="用大模型补齐截止时间、金额、中标人等字段")
    ap.add_argument("--webhook", help="企业微信、飞书或钉钉机器人地址")
    args = ap.parse_args()

    until = date.today()
    state_path = Path(args.state)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    if args.days:
        since = until - timedelta(days=args.days)
    elif state.get("last_run"):
        since = c.to_date(state["last_run"]) + timedelta(days=1)
    else:
        since = until - timedelta(days=7)

    rows = collect(args, since, until)
    in_window = [r for r in rows if not r.get("published")
                 or (d := c.to_date(r["published"])) and since - timedelta(days=3) <= d <= until]
    kept, _ = filter_mod.filter_bid(in_window, c.load_yaml(args.rules))
    seen = set(state.get("urls", []))
    fresh = [r for r in kept if c.canonical_url(r["url"]) not in seen]
    tokens = 0
    for i, r in enumerate(fresh):
        if args.fetch:
            if i:
                time.sleep(0.5)
            r.update(fetch_mod.fetch_one(r, 3000))
        if args.llm:
            import summarize as summarize_mod
            try:
                out = summarize_mod.work(r, "bid")
                r.update(card=out["card"], published=out["published"])
                tokens += sum(out["usage"].values())
            except Exception as e:
                r["card"] = None
                r["llm_error"] = str(e)[:120]
    fresh = [r for r in fresh if not r.get("card") or r["card"].get("is_esg")]
    brief = build_brief(fresh, since, until)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    brief_path = out_dir / f"{until.isoformat()}.md"
    brief_path.write_text(brief, encoding="utf-8")
    c.write_jsonl(out_dir / f"{until.isoformat()}.sources.jsonl", build_sources(fresh))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"last_run": until.isoformat(), "urls": sorted(
        seen | {c.canonical_url(r["url"]) for r in kept})}, ensure_ascii=False), encoding="utf-8")
    if args.webhook:
        push(args.webhook, "ESG 招标日报", brief)
    print(f"[monitor] 区间 {since} 至 {until}：线索 {len(rows)} 条，关键词命中 {len(kept)} 条，新增 {len(fresh)} 条"
          f"{f'，大模型 token {tokens}' if args.llm else ''}，日报={brief_path}")
    return 0


if __name__ == "__main__":
    sys.exit(c.guard("monitor", main))

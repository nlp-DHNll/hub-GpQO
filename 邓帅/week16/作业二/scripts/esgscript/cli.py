"""命令行：检索、抓取、筛选、总结、统计、图表、渲染、核验各是一条「参数进、JSON 出」的命令。

collect 把前三步串起来，build 把后四步串起来；每一步也都能单独调用（读运行目录 work/ 里的参数与中间结果）。
"""

import argparse
import json
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from esgtools.cli import render_verdict
from esgtools.runner import window_from

from . import charts, collect, queries, render, summarize
from .bridge import check_run, contract
from .collect import WORK_DIR, CollectSpec, load_spec, read_json, write_json
from .runrecord import write_run_record
from .stats import bid_stats, monthly_stats

SKILLS = {"monthly-report": "esg-monthly-report-scripted@0.1.0", "bid-radar": "esg-bid-radar-scripted@0.1.0"}
STEPS = ("search", "fetch", "select")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="esgscript", description="ESG 情报的确定性脚本：每一步参数进、JSON 出。"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    full = commands.add_parser("collect", help="检索 → 抓取 → 筛选，写出 data.json 与 review.json")
    _spec_args(full)
    full.add_argument("--out", required=True, help="运行目录")
    full.add_argument(
        "--stages",
        default=",".join(STEPS),
        help="只跑其中几步，逗号分隔（默认全跑）；没跑的用 work/ 里的缓存",
    )

    for step in STEPS:
        single = commands.add_parser(
            step, help=f"只跑{ {'search': '检索', 'fetch': '抓取', 'select': '筛选'}[step] }一步"
        )
        single.add_argument("--out", required=True, help="运行目录（须已有 work/spec.json）")

    draft = commands.add_parser("summarize", help="总结：模型依据 data.json 起草分析，写 analysis.json")
    draft.add_argument("--out", required=True, help="运行目录")
    draft.add_argument("--force", action="store_true", help="已有 analysis.json 也重新起草")

    build = commands.add_parser("build", help="统计 → 图表 → 渲染 → 核验，写出 report.md")
    build.add_argument("--out", required=True, help="运行目录")
    build.add_argument("--seen", help="监控模式的已见清单；给了就把本次新增追加进去")
    build.add_argument("--skill", help="写进运行记录的 skill 版本标识")

    for name, help_text in (
        ("stats", "统计"),
        ("charts", "图表"),
        ("render", "渲染"),
        ("verify", "核验（调用验收器）"),
    ):
        single = commands.add_parser(name, help=help_text)
        single.add_argument("--out", required=True, help="运行目录")
        if name == "verify":
            single.add_argument("--json", action="store_true", help="输出验收器的 JSON 判定")
    return parser


def _spec_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--case", required=True, choices=("monthly-report", "bid-radar"), help="案例")
    parser.add_argument("--mode", choices=("report", "summary", "monitor"), help="运行模式；招投标必填")
    parser.add_argument("--client", help="客户；月报必填")
    parser.add_argument("--industry", help="行业；月报必填")
    parser.add_argument("--client-en", help="客户的英文名，用于英文检索")
    parser.add_argument("--industry-en", help="行业的英文词，用于英文检索")
    window = parser.add_mutually_exclusive_group(required=True)
    window.add_argument("--start", help="起始日期 YYYY-MM-DD（不给 --end 则到今天）")
    window.add_argument("--days", type=int, help="到今天为止往前取的天数（含今天）")
    window.add_argument("--months", type=int, help="到今天为止往前取的月数")
    parser.add_argument("--end", help="结束日期 YYYY-MM-DD，须与 --start 成对给出")
    parser.add_argument("--budget", type=int, default=20, help="智谱搜索的预算（政采网直连另计）")
    parser.add_argument(
        "--max-pages", type=int, default=0, help="最多读多少页；0 用默认（月报 60、招投标 110）"
    )
    parser.add_argument("--peers", help="对标企业，逗号分隔；不给按行业取默认")
    parser.add_argument("--no-ccgp", action="store_true", help="不直连中国政府采购网")
    parser.add_argument("--seen", help="已见清单的路径（监控模式）")
    parser.add_argument("--concurrency", type=int, default=4, help="检索与模型调用的并发数")


def _spec(args: argparse.Namespace) -> CollectSpec:
    today = date.today()
    start, end = window_from(
        today=today,
        start=date.fromisoformat(args.start) if args.start else None,
        end=date.fromisoformat(args.end) if args.end else None,
        days=args.days,
        months=args.months,
    )
    mode = args.mode or ("report" if args.case == "monthly-report" else None)
    if mode is None:
        raise SystemExit("招投标情报须用 --mode summary 或 monitor 指明运行模式")
    if args.case == "monthly-report" and not (args.client and args.industry):
        raise SystemExit("月报须给出 --client 与 --industry")
    if mode == "monitor" and not args.seen:
        raise SystemExit("监控模式须用 --seen 给出已见清单的路径")
    peers = (
        tuple(word.strip() for word in args.peers.split(",") if word.strip())
        if args.peers
        else queries.PEERS.get(args.industry or "", ())
    )
    return CollectSpec(
        case=args.case,
        mode=mode,
        window_start=start,
        window_end=end,
        client=args.client,
        industry=args.industry,
        client_en=args.client_en or "",
        industry_en=args.industry_en or "",
        budget=args.budget,
        max_pages=args.max_pages,
        peers=peers,
        ccgp=not args.no_ccgp,
        seen_path=args.seen,
        concurrency=args.concurrency,
    )


def _stats_for(spec: CollectSpec, data: dict[str, Any]) -> dict[str, Any]:
    if spec.case == "monthly-report":
        return monthly_stats(
            data.get("evidence", []), spec.window_start.isoformat(), spec.window_end.isoformat()
        )
    return bid_stats(data.get("records", []), quarterly=spec.days > 180)


def _pictures(spec: CollectSpec, out_dir: Path, stats: dict[str, Any]) -> list[str]:
    if spec.case == "bid-radar" and spec.mode == "summary":
        return charts.plot_bid_charts(stats, out_dir)
    return []


def _update_seen(out_dir: Path, seen_path: Path) -> int:
    """把本次新增追加到已见清单；已在清单里的不重复加。"""
    records = read_json(out_dir / contract.DATA_FILE, {}).get("records", [])
    seen = read_json(seen_path, {"records": []})
    items = list(seen if isinstance(seen, list) else contract.as_dict(seen).get("records", []))
    known = {contract.dedup_key(item["url"]) for item in items if isinstance(item, dict) and item.get("url")}
    fresh = [record for record in records if contract.dedup_key(record["url"]) not in known]
    items.extend(fresh)
    write_json(seen_path, seen | {"records": items} if isinstance(seen, dict) else items)
    return len(fresh)


def _build(out_dir: Path, *, seen: str | None, skill: str | None) -> dict[str, Any]:
    """统计 → 图表 → 渲染 → 核验。没有 analysis.json 时先用模型起草一份。"""
    started_at = datetime.now().astimezone()
    started = time.perf_counter()
    spec = load_spec(out_dir)
    data = read_json(out_dir / contract.DATA_FILE, {})
    if not data:
        raise SystemExit(f"{out_dir} 下没有 data.json：先运行 collect")
    analysis = read_json(out_dir / summarize.ANALYSIS_FILE, None)
    if not isinstance(analysis, dict):
        analysis = summarize.draft(out_dir, spec)
    stats = _stats_for(spec, data)
    write_json(out_dir / WORK_DIR / "stats.json", stats)
    pictures = _pictures(spec, out_dir, stats)
    notes = render.render(out_dir, spec, analysis, stats, pictures)

    work = out_dir / WORK_DIR
    search = collect.search_summary(work)
    counts = (search.get("zhipu", {}), search.get("ccgp", {}))
    search_count = sum(entry.get("ok", 0) + entry.get("failed", 0) for entry in counts)
    collect.add_stage_time(work, "build_s", time.perf_counter() - started)
    usage = read_json(work / "usage.json", {})
    total_seconds = sum(float(value) for key, value in usage.items() if key.endswith("_s"))
    write_run_record(
        out_dir,
        spec,
        skill_version=skill or SKILLS[spec.case],
        started_at=started_at,
        duration_ms=int(total_seconds * 1000),
        usage=usage,
        search_count=search_count,
    )
    verdict = check_run(out_dir)
    added = _update_seen(out_dir, Path(seen)) if spec.mode == "monitor" and seen else 0
    write_json(
        out_dir / "script_usage.json",
        {
            "searches": {name: entry for name, entry in zip(("zhipu", "ccgp"), counts, strict=True)},
            "model": usage,
            "model_usage": usage,
        },
    )
    failed = [check for check in verdict.checks if not check.passed]
    return {
        "ok": verdict.passed and not notes["problems"],
        "passed": verdict.passed,
        "failed_rules": [check.rule for check in failed],
        "failure_details": [check.detail for check in failed],
        "problems": notes["problems"],
        "warnings": notes["warnings"],
        "report": str(out_dir / contract.REPORT_FILE),
        "charts": pictures,
        "seen_added": added,
        "headline": {
            key: stats.get(key)
            for key in (
                "evidence_total",
                "qualified_sources",
                "date_in_window_rate",
                "sample_size",
                "amount_rate",
            )
        },
    }


def _dispatch(args: argparse.Namespace, out_dir: Path) -> dict[str, Any]:
    if args.command == "collect":
        stages = tuple(step.strip() for step in args.stages.split(",") if step.strip() in STEPS)
        return {"ok": True, **collect.run(_spec(args), out_dir, stages=stages or STEPS)}
    if args.command in STEPS:
        return {"ok": True, **collect.run(load_spec(out_dir), out_dir, stages=(args.command,))}
    if args.command == "summarize":
        analysis = summarize.draft(out_dir, load_spec(out_dir), force=args.force)
        return {"ok": True, "analysis": str(out_dir / summarize.ANALYSIS_FILE), "keys": sorted(analysis)}
    if args.command == "build":
        return _build(out_dir, seen=args.seen, skill=args.skill)
    if args.command == "stats":
        stats = _stats_for(load_spec(out_dir), read_json(out_dir / contract.DATA_FILE, {}))
        write_json(out_dir / WORK_DIR / "stats.json", stats)
        return {
            "ok": True,
            "stats": str(out_dir / WORK_DIR / "stats.json"),
            "headline": {k: v for k, v in stats.items() if not isinstance(v, (dict, list))},
        }
    if args.command == "charts":
        pictures = _pictures(load_spec(out_dir), out_dir, read_json(out_dir / WORK_DIR / "stats.json", {}))
        return {"ok": True, "charts": pictures}
    if args.command == "render":
        spec = load_spec(out_dir)
        return {
            "ok": True,
            **render.render(
                out_dir,
                spec,
                read_json(out_dir / summarize.ANALYSIS_FILE, {}),
                read_json(out_dir / WORK_DIR / "stats.json", {}),
                [],
            ),
        }
    verdict = check_run(out_dir)
    if args.json:
        return verdict.to_dict()
    print(render_verdict(verdict))
    return {
        "ok": verdict.passed,
        "passed": verdict.passed,
        "failed_rules": [check.rule for check in verdict.checks if not check.passed],
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_dir = Path(args.out).expanduser().resolve()
    try:
        result = _dispatch(args, out_dir)
    except SystemExit:
        raise
    except Exception as exc:  # 任何一步出错都只报类型与原因，不把堆栈和凭据打出来
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1

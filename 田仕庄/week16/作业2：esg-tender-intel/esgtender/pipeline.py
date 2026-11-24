#!/usr/bin/env python3
"""流水线编排：组 query → 检索 → 抽取 → 归类 → 关联 → 去重 → 增量 → 统计 → 渲染。

命令行解析与摘要打印在 cli.py；这里只处理「跑一次」的业务逻辑：

    collect()  只碰网络（组 query、检索、抓列表页）
    shape()    只做计算 + 一次已推送库写入（过滤、关联、去重、统计）
    publish()  只碰磁盘与网络（渲染、落盘、推送）

``shape()`` 不依赖网络，``publish()`` 可以对着现成的 ``records.json`` 重跑，
改模板时不必重新计费检索。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from . import dedup as dedup_mod
from . import extract as extract_mod
from . import presets as presets_mod
from . import render as render_mod
from . import search as search_mod
from . import sources as sources_mod
from . import store as store_mod
from . import triage as triage_mod

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCOPE = SKILL_ROOT / "config" / "scope.yaml"
DEFAULT_SOURCES = SKILL_ROOT / "config" / "sources.yaml"


@dataclass(slots=True)
class RunSummary:
    """一次运行的产出：给 cli 打印用，不让 pipeline 直接依赖 stdout。"""

    summary: dict[str, Any]
    report_paths: list[Path]
    shown: list[dict[str, Any]]
    exit_code: int


# ------------------------------------------------------------------ 配置
def load_scope(path: Path | str | None = None, preset: str | None = None) -> dict[str, Any]:
    scope_path = Path(path) if path else DEFAULT_SCOPE
    if not scope_path.exists():
        # 抛 PipelineError 而不是 SystemExit("..."):SystemExit 收到字符串时
        # Python 会把退出码设成 1，而 README/SKILL 约定「配置错误 → 2」；
        # 统一成 PipelineError 后由 execute 统一打印 [错误] 行并返回 2。
        raise PipelineError(f"找不到配置文件：{scope_path}")
    with scope_path.open(encoding="utf-8") as handle:
        scope = yaml.safe_load(handle) or {}
    if preset:
        try:
            scope = presets_mod.apply_preset(scope, presets_mod.load_preset(preset))
        except presets_mod.PresetError as exc:
            raise PipelineError(str(exc)) from exc
    return scope


def build_queries(scope: dict, limit: int) -> list[str]:
    """按 scope 的 query_plan 组检索词。三类赛道各自配额，最后统一截断。

    顺序即优先级：核心 → 扩展 → 边缘。配额的目的是防止核心赛道的关键词
    把 max_queries 全部吃掉，导致扩展/边缘永远发不出 query（静默失效）。
    """
    plan = scope.get("query_plan") or {}
    suffix = str((scope.get("search") or {}).get("query_suffix", "")).strip()
    tracks = scope.get("tracks") or {}

    def compose(keyword: str) -> str:
        return f"{keyword} {suffix}".strip()

    queries: list[str] = []

    per_track = max(1, int(plan.get("core_per_track", 1)))
    for track_def in (tracks.get("core") or {}).values():
        for keyword in (track_def.get("keywords") or [])[:per_track]:
            queries.append(compose(keyword))

    extended_total = int(plan.get("extended_total", 2))
    extended_queries = [
        compose(keywords[0])
        for keywords in (tracks.get("extended") or {}).values()
        if keywords
    ]
    queries.extend(extended_queries[: max(0, extended_total)])

    if int(plan.get("edge_total", 1)) > 0:
        edge = tracks.get("edge") or {}
        require_any = edge.get("require_any") or []
        also = edge.get("also_require_any") or []
        if require_any and also:
            queries.append(compose(f"{require_any[0]} {also[0]}"))

    seen: set[str] = set()
    ordered: list[str] = []
    for query in queries:
        query = query.strip()
        if query and query not in seen:
            seen.add(query)
            ordered.append(query)
    return ordered[:limit]


def load_scope_freshness(scope: dict, days: int) -> dict:
    """把 days 翻译成 provider 的时间参数，供缓存 key 与 API 共用。"""
    cfg = dict(scope.get("search") or {})
    windows = search_mod.freshness_windows_for(days)
    cfg["freshness_list"] = windows
    # 单值 fallback 取**最近**那段：漏传 freshness 时宁可少取，不要把整两年
    # 的时段当成默认值（早期实现就因为这个把所有切片都请求成了同一个区间）。
    cfg["freshness"] = windows[0]
    return cfg


def merge_hits(hits: list[search_mod.Hit]) -> list[tuple[search_mod.Hit, list[str]]]:
    """同一页面常被多条 query 同时召回，先按 (标题, URL) 合并。

    合并不是「去重」：不同平台发布的同一个项目才是重复，那是 ``dedup`` 的活。
    这里只是把「一页被多次召回」收敛成一条，并记下来源 query 列表。
    """
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for hit in hits:
        key = (hit.title.strip(), hit.url.strip())
        entry = merged.setdefault(key, {"hit": hit, "queries": []})
        if hit.query not in entry["queries"]:
            entry["queries"].append(hit.query)
    return [(entry["hit"], entry["queries"]) for entry in merged.values()]


# ------------------------------------------------------------------ 时间窗口
_PUBLISHED_RE = re.compile(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})")


def parse_published(value: str | None) -> date | None:
    """解析 provider 返回的发布日期。解析不了返回 None（不因此丢弃记录）。"""
    text = (value or "").strip()
    if not text:
        return None
    match = _PUBLISHED_RE.search(text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def split_by_window(
    records: list[dict[str, Any]], days: int
) -> tuple[list[dict[str, Any]], int, int]:
    """按发布日期过滤到时间窗口内。

    必须在本地做，不能只依赖 provider 的 freshness：博查的时间参数最细只到
    ``oneYear``，用户要「近 30 天」时若不本地过滤，报告里会混进一年前的项目。
    发布日期缺失的记录**保留**并单独计数——宁可多报也不静默丢。
    """
    cutoff = datetime.now().date() - timedelta(days=max(days, 1))
    kept: list[dict[str, Any]] = []
    out_of_window = 0
    unknown = 0
    for record in records:
        published = parse_published((record.get("source") or {}).get("published"))
        if published is None:
            unknown += 1
            kept.append(record)
        elif published >= cutoff:
            kept.append(record)
        else:
            out_of_window += 1
    return kept, out_of_window, unknown


# ------------------------------------------------------------------ 季度趋势
def build_trend(
    records: list[dict[str, Any]], *, days: int | None = None, today: date | None = None
) -> list[dict[str, Any]]:
    """按季度聚合条数与已知金额，供两年这类长窗口报告看趋势。

    只统计有发布日期的记录；无日期的不进趋势（会虚增某一个季度），但在
    ``overview`` 里已经计入总条数。季度按时间升序输出——趋势表要能顺着读。

    窗口首尾所在的季度往往不是完整季度（比如 11 月跑两年，末季只过了一半），
    必须打 ``partial`` 标记，否则读者会把「当季数据少」误读成「市场断崖下跌」。
    """
    buckets: dict[str, dict[str, Any]] = {}
    for record in records:
        published = parse_published((record.get("source") or {}).get("published"))
        if published is None:
            continue
        label = f"{published.year}Q{(published.month - 1) // 3 + 1}"
        entry = buckets.setdefault(
            label, {"label": label, "count": 0, "core": 0, "extended": 0, "amounts": []}
        )
        entry["count"] += 1
        group = (record.get("track") or {}).get("group")
        if group == "core":
            entry["core"] += 1
        elif group == "extended":
            entry["extended"] += 1
        amount = (record.get("fields") or {}).get("amount_cny")
        if amount:
            entry["amounts"].append(Decimal(str(amount)))

    base = today or date.today()
    window_start = base - timedelta(days=max(days, 1) - 1) if days else None

    trend: list[dict[str, Any]] = []
    for label in sorted(buckets):
        entry = buckets[label]
        amounts = entry.pop("amounts")
        total = sum(amounts) if amounts else None
        entry["amount_known"] = len(amounts)
        entry["amount_sum"] = render_mod.fmt_amount(total) if amounts else "N/A"
        # 趋势列统一用万元（fmt_amount 会按量级换「亿」，同一列里没法比较大小）
        entry["amount_wan"] = render_mod.fmt_amount_wan(total) if amounts else "N/A"

        year = int(label[:4])
        quarter = int(label[-1])
        q_start = date(year, 3 * quarter - 2, 1)
        q_end = date(year, 3 * quarter + 1, 1) - timedelta(days=1) if quarter < 4 else date(year, 12, 31)
        entry["partial"] = q_end > base or (window_start is not None and q_start < window_start)
        trend.append(entry)

    # 条形图宽度相对峰值：直接给「占总数」会把非峰值的季度压成一条线
    peak = max((item["count"] for item in trend), default=0)
    for item in trend:
        item["pct"] = round(item["count"] / peak * 100, 1) if peak else 0
    return trend


# ------------------------------------------------------------------ 记录构造
def _empty_field() -> dict[str, Any]:
    return {"value": None, "quote": "", "confidence": "none"}


def build_record(
    hit: search_mod.Hit, queries: list[str], scope: dict
) -> dict[str, Any]:
    title_clean = extract_mod.clean_title(hit.title) or hit.title
    blob = f"{title_clean} {hit.snippet}"
    amount = extract_mod.parse_amount(blob)
    deadline = extract_mod.parse_deadline(blob)
    buyer = extract_mod.parse_buyer(blob)
    project_no = extract_mod.parse_project_no(blob)

    # 截止日期早于发布日期一定错了（摘要里常混进「2025 年预算」这类旧年份）。
    # 这种日期留着比 N/A 更有害：读者会以为项目已经截止而跳过。
    published_date = parse_published(hit.published)
    if deadline is not None and published_date is not None:
        if deadline.value < published_date.isoformat():
            deadline = None

    # 指纹用清洗后的标题：同一条公告被三站转载时，原文标题各带站点尾巴，
    # 直接做指纹会算出三个不同值，去重就失效了。
    title_norm = extract_mod.norm_title(title_clean)
    buyer_norm = extract_mod.norm_buyer(buyer.value if buyer else "")
    project_no_norm = extract_mod.norm_project_no(project_no.value if project_no else "")
    track = triage_mod.classify(title_clean, hit.snippet, scope)

    amount_cny = amount.value if amount else None
    buckets = scope.get("amount_buckets") or []
    bucket = extract_mod.amount_bucket(
        Decimal(amount_cny) if amount_cny else None, buckets
    )

    return {
        "id": dedup_mod.record_id(hit.url, hit.title),
        "title_norm": title_norm,
        "fp": dedup_mod.fingerprint(title_norm, buyer_norm, amount_cny),
        "source": {
            "provider": hit.provider,
            "query": hit.query,
            "queries": queries,
            "site": hit.site,
            "url": hit.url,
            "published": hit.published,
        },
        "raw": {"title": hit.title, "title_clean": title_clean, "snippet": hit.snippet},
        "fields": {
            "buyer": buyer.as_dict() if buyer else _empty_field(),
            "amount": amount.as_dict() if amount else _empty_field(),
            "amount_cny": amount_cny,
            "deadline": deadline.as_dict() if deadline else _empty_field(),
            "project_no": project_no.as_dict() if project_no else _empty_field(),
            "project_no_norm": project_no_norm or None,
        },
        "track": track,
        "stage": extract_mod.parse_stage(hit.title),
        "amount_bucket": bucket,
        "flags": {
            "duplicate_of": None,
            "suspect_of": None,
            "needs_review": track.get("decision") == triage_mod.DECISION_GRAY,
            "reasons": [],
        },
    }


# ------------------------------------------------------------------ 招标—中标关联
def link_awards(records: list[dict[str, Any]]) -> int:
    """把同一项目的中标/成交公告挂到招标公告上，返回关联对数。

    为什么按 ``title_norm`` 配对而不是项目编号：中标公告大多不带编号（和招标
    公告一样），编号在真实数据里几乎总是空的。归一化标题会把「招标公告 /
    中标公告」这类后缀剥掉，剩下的是项目名，正好是可靠的项目身份。

    只标注、不删除：中标记录本身是「这个项目已经花落谁家」的证据，删掉会让
    历史窗口里的成交金额全部消失。招标记录缺金额时用成交金额补全——对做商机
    的人来说，成交价是最有参考价值的数字。

    必须在 ``deduplicate`` **之前**调用：两条记录的指纹可能因为金额不同而不
    相等，此时去重会各自保留，先关联才能保证被丢弃的那条的信息不丢。
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        norm = record.get("title_norm") or ""
        if len(norm) < 8:  # 太短的归一化标题配对风险高（如「碳核查服务」）
            continue
        groups.setdefault(norm, []).append(record)

    linked = 0
    for group in groups.values():
        tenders = [r for r in group if (r.get("stage") or {}).get("code") == "tender"]
        awards = [r for r in group if (r.get("stage") or {}).get("code") == "award"]
        if not tenders or not awards:
            continue
        # 取发布日期最晚的一条作为「最终结果」，避免把「中标候选人公示」当成最终成交
        award = max(awards, key=lambda r: str((r.get("source") or {}).get("published") or ""))
        info = {
            "id": award.get("id"),
            "url": (award.get("source") or {}).get("url", ""),
            "title": (award.get("raw") or {}).get("title", ""),
            "amount_cny": (award.get("fields") or {}).get("amount_cny"),
            "published": (award.get("source") or {}).get("published", ""),
        }
        for tender in tenders:
            if tender.get("id") == award.get("id"):
                continue
            flags = tender.setdefault("flags", {})
            if flags.get("award") == info:
                continue
            flags["award"] = info
            flags.setdefault("reasons", []).append("award_linked")
            award.setdefault("flags", {})["awarded_by"] = tender.get("id")
            tender_fields = tender.setdefault("fields", {})
            award_fields = award.get("fields") or {}
            if not tender_fields.get("amount_cny") and award_fields.get("amount_cny"):
                tender_fields["amount"] = dict(award_fields.get("amount") or {})
                tender_fields["amount_cny"] = award_fields.get("amount_cny")
                tender["amount_bucket"] = award.get("amount_bucket")
                flags["reasons"].append("award_amount")
            linked += 1
    return linked


# ------------------------------------------------------------------ 输出
def _slugify(text: str, fallback: str = "auto") -> str:
    """只保留 ASCII 字母数字与连字符，避免中文目录名在跨平台/压缩包里出问题。"""
    cleaned = "".join(
        ch if (ch.isascii() and (ch.isalnum() or ch in "-_")) else "_" for ch in text
    )
    cleaned = cleaned.strip("_")
    if not cleaned:
        return fallback
    return cleaned[:24]


def _sort_key(record: dict) -> tuple[float, str]:
    relevance = float((record.get("track") or {}).get("relevance") or 0)
    deadline = (record.get("fields") or {}).get("deadline", {}).get("value") or "9999-99-99"
    return (-relevance, deadline)


def _resolve_db(db_arg: str | None, cfg: dict) -> str | None:
    """fixture 演练绝不能写生产库。

    离线样本是拿来演示和回归的，标题全是「某市…」；一旦落进 ``data/tenders.db``，
    真实增量的「往期已见」就会被这些假数据顶着，第二次真跑还会把真项目当成
    「已见过」。所以 provider=fixture 且用户没显式 ``--db`` 时，自动切到
    同目录的 ``tenders_fixture.db``：演示照样能跑「首跑 7 / 二跑 0」，
    但和生产库完全隔离。显式传 ``--db`` 时尊重用户选择。
    """
    if db_arg:
        return db_arg
    if str(cfg.get("provider", "")).lower() != "fixture":
        return None  # Store 自己用默认生产库
    return str(store_mod.DEFAULT_DB.with_name("tenders_fixture.db"))


# ------------------------------------------------------------------ 主流程
def core_keywords(scope: dict, limit: int = 8) -> list[str]:
    """给定向源兜底的关键词：核心赛道每题取前两个写法。"""
    words: list[str] = []
    for track_def in ((scope.get("tracks") or {}).get("core") or {}).values():
        for keyword in (track_def.get("keywords") or [])[:2]:
            if keyword and keyword not in words:
                words.append(keyword)
    return words[:limit]


class PipelineError(RuntimeError):
    """配置类错误（无 Key、sources.yaml 读不了）：给提示就好，不要抛栈。"""


@dataclass(slots=True)
class CollectResult:
    """① 检索阶段的产出。只含「从外面拿到的东西」。"""

    scope: dict[str, Any]
    cfg: dict[str, Any]
    queries: list[str]
    query_label: str
    preset_meta: dict[str, Any]
    src_cfg: dict[str, Any]
    hits: list[Any]
    merged: list[tuple[Any, list[str]]]
    failures: list[Any]
    source_used: list[dict[str, Any]]
    run_id: str
    now: datetime


@dataclass(slots=True)
class ShapeResult:
    """② 加工阶段的产出。全部是纯计算结果 + 一次库写入。"""

    kept: list[dict[str, Any]]
    duplicates: list[dict[str, Any]]
    suspects: list[dict[str, Any]]
    stats: dict[str, Any]
    trend: list[dict[str, Any]]
    shown: list[dict[str, Any]]
    incremental: dict[str, Any] | None
    store: store_mod.Store | None
    counters: dict[str, int]


def collect(args: argparse.Namespace, *, run_id: str, now: datetime) -> CollectResult:
    """① 检索：组 query → 多源定向 → 检索 → 合并。只碰网络。"""
    # --only-new 的语义是「与库里的记录比，只输出没见过的」。没有库就没有「见过」，
    # 旧实现会给所有记录打上「非新增」→ 静默产出 0 条报告、退出码还是 0，
    # 命令行只显示「保留 0 条」，看起来像检索失败。这种自相矛盾的参数组合
    # 必须在发请求之前就拒绝掉，别浪费一次计费。
    if args.only_new and args.no_store:
        raise PipelineError(
            "--only-new 需要读取已推送库，不能与 --no-store 同时使用；"
            "想演练「只输出新增」请用 --incremental 配一个 --db 路径。"
        )

    scope = load_scope(args.scope, args.preset)
    preset_meta = scope.get("preset") or {}
    cfg = load_scope_freshness(scope, args.days)
    if args.provider:
        cfg["provider"] = args.provider
    cfg["count"] = args.count or cfg.get("count", 50)
    if str(cfg.get("provider")) == "bocha" and int(cfg["count"]) > 50:
        # 博查 count 上限是 50，传 100 不会报错、只会安静地返回 50 条，
        # 让人觉得「要了 100 却只有 50」。与其猜，不如直接说清楚。
        raise PipelineError(f"--count {cfg['count']} 超过博查上限 50")

    max_queries = args.max_queries or int(cfg.get("max_queries", 10))
    if args.query:
        queries = [q.strip() for q in args.query.replace("，", ",").split(",") if q.strip()]
        query_label = "、".join(queries)
    else:
        queries = build_queries(scope, max_queries)
        query_label = "自动组合（scope.yaml 关键词）"
    if preset_meta.get("title"):
        query_label = f"{query_label}｜预设 {preset_meta['title']}"

    # ---- 多源：search_site 定向 query 与 crawl 列表页
    src_cfg: dict[str, Any] = {}
    site_items: list[dict[str, Any]] = []
    if args.sources:
        try:
            src_cfg = sources_mod.load(args.sources_config or DEFAULT_SOURCES)
        except sources_mod.SourceError as exc:
            raise PipelineError(str(exc)) from exc
        site_items = sources_mod.site_queries(
            src_cfg,
            fallback_keywords=core_keywords(scope),
            suffix=str(cfg.get("query_suffix", "")).strip(),
            limit=args.max_site_queries,
            force=True,
        )
        if site_items:
            # --max-queries 是计费护栏，定向 query 必须一起算进去：否则
            # 「--max-queries 10 --sources」实际发出 13 条，超预算还没人知道。
            # 定向源是用户显式打开的、条数少且精准，先给它留位置，再截断
            # 自动组合的关键词——反过来截掉的必然是「用户明确要的 query」。
            budget = max(1, max_queries - len(site_items))
            if len(queries) > budget:
                dropped = queries[budget:]
                queries = queries[:budget]
                print(
                    f"[提示] --max-queries {max_queries} 要为 {len(site_items)} 条定向 query "
                    f"留位，已截断 {len(dropped)} 条关键词 query：{'、'.join(dropped)}",
                    file=sys.stderr,
                )
        for item in site_items:
            if item["query"] not in queries:
                queries.append(item["query"])

    try:
        hits, failures = search_mod.run_queries(
            queries, cfg=cfg, use_cache=not args.no_cache
        )
    except search_mod.SearchError as exc:
        raise PipelineError(str(exc)) from exc

    source_used: list[dict[str, Any]] = []
    if site_items:
        by_query = {item["query"]: item for item in site_items}
        tally: dict[str, dict[str, Any]] = {}
        for hit in hits:
            item = by_query.get(hit.query)
            if not item:
                continue
            entry = tally.setdefault(
                str(item["source_id"]),
                {
                    "id": item["source_id"],
                    "name": item["source_name"],
                    "mode": "search_site",
                    "hits": 0,
                    "queries": [],
                },
            )
            entry["hits"] += 1
            if item["query"] not in entry["queries"]:
                entry["queries"].append(item["query"])
        source_used = list(tally.values())

    if args.sources:
        crawl_hits, crawl_failures, crawl_used = sources_mod.crawl_all(
            src_cfg, fallback_keywords=core_keywords(scope), force=True
        )
        # failures 必须无条件带上去：crawl 的设计是「单源失败不影响其它源」，
        # 两个源都被 robots 拒绝时 hits 是空列表，曾经的 `if crawl_hits:` 会把
        # 失败原因一起吞掉，报告里显示「无失败」——恰好是最该告知用户的情况。
        hits.extend(crawl_hits)
        failures.extend(crawl_failures)
        source_used.extend(crawl_used)

    return CollectResult(
        scope=scope,
        cfg=cfg,
        queries=queries,
        query_label=query_label,
        preset_meta=preset_meta,
        src_cfg=src_cfg,
        hits=hits,
        merged=merge_hits(hits),
        failures=failures,
        source_used=source_used,
        run_id=run_id,
        now=now,
    )


def shape(args: argparse.Namespace, collected: CollectResult) -> ShapeResult:
    """② 加工：抽字段 → 时间窗 → 阈值/阶段 → 关联 → 去重 → 增量 → 统计。

    除「读写已推送库」外不碰外部世界，可以对着现成的 records.json 重跑。
    """
    scope = collected.scope
    records = [build_record(hit, queries, scope) for hit, queries in collected.merged]
    records, out_of_window, unknown_date = split_by_window(records, args.days)

    thresholds = (scope.get("relevance") or {}).get("threshold") or {}
    kept: list[dict] = []
    below_threshold = 0
    not_tender = 0
    stage_filtered = 0
    for record in records:
        decision = record["track"].get("decision")
        if decision == triage_mod.DECISION_NOT_TENDER:
            not_tender += 1
            continue
        if decision == triage_mod.DECISION_DROP:
            below_threshold += 1
            continue
        if args.min_relevance is not None and record["track"]["relevance"] < args.min_relevance:
            below_threshold += 1
            continue
        if args.stage and (record.get("stage") or {}).get("code") != args.stage:
            stage_filtered += 1
            continue
        kept.append(record)

    kept.sort(key=_sort_key)
    # 先关联再去做重：指纹含金额，招标与中标两条的指纹往往不同，去重会各自
    # 保留；先关联才能保证「被丢弃的那条」的成交金额不会凭空消失。
    award_links = link_awards(kept)
    kept, duplicates, suspects = dedup_mod.deduplicate(kept)
    kept.sort(key=_sort_key)

    # ---- 已推送库 / 增量
    use_store = not args.no_store and bool(
        args.incremental or args.only_new or args.notify or args.db
    )
    incremental: dict[str, Any] | None = None
    store_obj: store_mod.Store | None = None
    if use_store:
        db_path = _resolve_db(args.db, collected.cfg)
        if db_path != args.db:
            print(f"[提示] fixture 演练不写生产库，本轮使用 {db_path}", file=sys.stderr)
        try:
            store_obj = store_mod.Store(db_path)
            incremental = store_obj.annotate(kept, run_id=collected.run_id)
            if args.prune_days:
                incremental["pruned"] = store_obj.prune(args.prune_days)
        except Exception as exc:  # 库坏了不该让报告出不来
            print(
                f"[警告] 已推送库不可用（{type(exc).__name__}: {exc}），本轮按全量处理",
                file=sys.stderr,
            )
            store_obj = None
            incremental = None

    report_records = kept
    if args.only_new:
        report_records = [r for r in kept if (r.get("flags") or {}).get("is_new")]

    # 统计与趋势必须基于**全量**，不能跟着 --limit 截断：
    # 两年汇总时 --limit 50 只截清单，若统计也只算前 50 条，金额合计与季度
    # 分布都会失真，而这两个数字恰恰是「汇总」最该可信的部分。
    total_kept = len(report_records)
    stats = render_mod.build_stats(report_records, scope.get("amount_buckets") or [])
    trend = build_trend(report_records, days=args.days)
    shown = report_records[: args.limit] if args.limit else report_records

    return ShapeResult(
        kept=kept,
        duplicates=duplicates,
        suspects=suspects,
        stats=stats,
        trend=trend,
        shown=shown,
        incremental=incremental,
        store=store_obj,
        counters={
            "out_of_window": out_of_window,
            "unknown_date": unknown_date,
            "below_threshold": below_threshold,
            "not_tender": not_tender,
            "stage_filtered": stage_filtered,
            "award_links": award_links,
            "window_total": len(kept),
            "kept_total": total_kept,
        },
    )


def publish(
    args: argparse.Namespace, collected: CollectResult, shaped: ShapeResult
) -> tuple[dict[str, Any], list[Path]]:
    """③ 发布：建目录 → 渲染 → 落盘 → 推送。返回 (meta, 报告路径)。"""
    relevance = collected.scope.get("relevance") or {}
    thresholds = relevance.get("threshold") or {}
    meta = {
        "generated_date": collected.now.strftime("%Y-%m-%d"),
        "generated_at": collected.now.strftime("%Y-%m-%d %H:%M:%S"),
        "run_id": collected.run_id,
        "query_label": collected.query_label,
        "days": args.days,
        "provider": collected.cfg.get("provider"),
        "raw_hits": len(collected.merged),
        "raw_hits_total": len(collected.hits),
        "queries": collected.queries,
        "freshness_windows": collected.cfg.get("freshness_list") or [],
        "kept_total": shaped.counters["kept_total"],
        "window_total": shaped.counters["window_total"],
        "shown": len(shaped.shown),
        "only_new": bool(args.only_new),
        "failures": [asdict(f) for f in collected.failures],
        "duplicates": len(shaped.duplicates),
        "below_threshold": shaped.counters["below_threshold"],
        "not_tender": shaped.counters["not_tender"],
        "out_of_window": shaped.counters["out_of_window"],
        "unknown_date": shaped.counters["unknown_date"],
        "stage_filtered": shaped.counters["stage_filtered"],
        "award_links": shaped.counters["award_links"],
        "thresholds": {
            "core": thresholds.get("core", 0.6),
            "extended": thresholds.get("extended", 0.65),
            "edge": thresholds.get("edge", 0.75),
        },
        "gray_low": relevance.get("gray_low", 0.3),
        "weights": relevance.get("weights") or {},
        "preset": collected.preset_meta or None,
        "sources": (
            sources_mod.describe(collected.src_cfg, used=collected.source_used, force=True)
            if args.sources
            else None
        ),
        "incremental": (
            {k: v for k, v in (shaped.incremental or {}).items() if k != "new_ids"} or None
        ),
        "notify": None,
    }

    # 目录名带上 provider，否则 --provider fixture 的演练会覆盖同名目录下的真实报告
    provider = str(collected.cfg.get("provider")).lower()
    provider_tag = "" if provider == "bocha" else f"_{collected.cfg.get('provider')}"
    # 也得带上行业预设：同一天用 energy 和 finance 各跑一次，口径不同、名单不同，
    # 不带 tag 就是后一次静默覆盖前一次（report 与 run_meta 全被替换）。
    preset_tag = (
        f"_{_slugify(str(collected.preset_meta.get('name') or ''), fallback='preset')}"
        if collected.preset_meta
        else ""
    )
    if args.only_new:
        provider_tag += "_new"
    out_dir = (
        Path(args.out)
        / f"{collected.now.strftime('%Y-%m-%d')}_{_slugify(collected.query_label)}{preset_tag}{provider_tag}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    context = render_mod.ReportContext(
        meta=meta,
        records=shaped.shown,
        stats=shaped.stats,
        coverage=render_mod.build_coverage(meta),
        trend=shaped.trend,
        suspects=shaped.suspects,
        stages=shaped.stats.get("by_stage") or [],
        incremental=shaped.incremental,
        preset=collected.preset_meta or None,
    )
    report_paths = render_mod.write_reports(context, out_dir, args.format)
    context.report_path = str(report_paths[0])

    (out_dir / "records.json").write_text(
        json.dumps(shaped.kept, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    # ---- 推送（放在最后：报告先落盘，推送失败也不影响交付）
    notified = 0
    if args.notify and args.only_new and not shaped.counters["kept_total"]:
        # 日报最常见的情况就是「今天没有新项目」，这时发一条空推送只会让人关通知
        print("本期无新增，跳过推送")
        meta["notify"] = {
            "ok": True, "channel": args.notify, "target": "", "error": "", "skipped": "no-new",
        }
    elif args.notify:
        from . import notify as notify_mod

        if args.notify_dry_run:
            title, text = notify_mod.build_message(context.as_dict())
            print("== 推送预览（未发送）==")
            print(title)
            print(text)
            result: dict[str, Any] = {
                "ok": True, "channel": args.notify, "target": "dry-run", "error": "",
            }
        else:
            result = notify_mod.notify(args.notify, context.as_dict())
        if result.get("ok") and shaped.store is not None and not args.notify_dry_run:
            # 标**全部**新增，而不是只标「清单里展示的那几条」：--limit 50 而新增
            # 80 条时，后 30 条既没被列出、也没标已推，会永远滞留在 pending 里
            # ——下一轮它们按 first_seen 算「往期已见」，再也不会出现在任何推送中。
            new_fps = [
                record.get("fp")
                for record in shaped.kept
                if (record.get("flags") or {}).get("is_new") and record.get("fp")
            ]
            notified = shaped.store.mark_notified(new_fps)
            result["marked"] = notified
        meta["notify"] = result
        if result.get("ok"):
            print(f"已推送：{result.get('channel')} → {result.get('target')}")
        else:
            print(f"[警告] 推送失败：{result.get('error')}", file=sys.stderr)

    # run_meta 必须**在推送之后**写：它曾经写在前面，导致 meta["notify"] 永远是
    # null —— 推送失败时用户唯一的排查线索（错误原文）没落盘，控制台一关就没了。
    # references/schema.md 把 notify 列为 run_meta 字段，这里才对得上契约。
    (out_dir / "run_meta.json").write_text(
        json.dumps(
            {
                "meta": meta,
                "stats": shaped.stats,
                "trend": shaped.trend,
                "suspects": shaped.suspects,
                "incremental": shaped.incremental,
                "dropped_duplicates": [
                    {
                        "id": item["id"],
                        "title": item["raw"]["title"],
                        "of": item["flags"]["duplicate_of"],
                    }
                    for item in shaped.duplicates
                ],
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    if shaped.store is not None:
        try:
            shaped.store.record_run(
                run_id=collected.run_id,
                meta=meta,
                kept=len(shaped.kept),
                new_count=(shaped.incremental or {}).get("new", 0),
                notified=notified,
            )
        finally:
            shaped.store.close()

    return meta, report_paths


def execute(args: argparse.Namespace) -> "RunSummary | int":
    """跑完整流程：collect → shape → publish → 汇总。

    返回 ``RunSummary``（正常）或退出码 ``int``（配置类错误）。
    """
    if getattr(args, "list_presets", False):
        items = presets_mod.list_presets()
        if not items:
            print("没有可用的行业预设（config/presets/*.yaml）")
            return 0
        for item in items:
            print(f"{item['name']:<14} {item['title']}　{item['description']}")
        return 0

    now = datetime.now()
    try:
        collected = collect(args, run_id=now.strftime("%Y%m%d-%H%M%S"), now=now)
    except PipelineError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2

    shaped = shape(args, collected)
    meta, report_paths = publish(args, collected, shaped)

    summary = {
        "run_id": collected.run_id,
        "days": args.days,
        "provider": collected.cfg.get("provider"),
        "preset": collected.preset_meta.get("name") if collected.preset_meta else None,
        "queries": collected.queries,
        "freshness_windows": collected.cfg.get("freshness_list") or [],
        "raw_hits": len(collected.merged),
        "raw_hits_total": len(collected.hits),
        "kept": shaped.counters["kept_total"],
        "window_total": shaped.counters["window_total"],
        "shown": len(shaped.shown),
        "new": (shaped.incremental or {}).get("new"),
        "pruned": (shaped.incremental or {}).get("pruned"),
        "only_new": bool(args.only_new),
        "duplicates": len(shaped.duplicates),
        "below_threshold": shaped.counters["below_threshold"],
        "not_tender": shaped.counters["not_tender"],
        "out_of_window": shaped.counters["out_of_window"],
        "unknown_date": shaped.counters["unknown_date"],
        "stage_filtered": shaped.counters["stage_filtered"],
        "award_links": shaped.counters["award_links"],
        "stages": shaped.stats.get("by_stage") or [],
        "failures": [asdict(f) for f in collected.failures],
        "suspects": len(shaped.suspects),
        "sources": collected.source_used,
        "notify": meta.get("notify"),
        "out_dir": str(Path(report_paths[0]).parent),
        "report": str(report_paths[0]),
        "reports": [str(path) for path in report_paths],
    }
    # 增量模式下「没有新增」是正常结果，退出码必须为 0，否则 cron 会天天报失败
    exit_code = 0 if (shaped.counters["kept_total"] or args.only_new) else 2
    return RunSummary(
        summary=summary, report_paths=report_paths, shown=shaped.shown, exit_code=exit_code
    )

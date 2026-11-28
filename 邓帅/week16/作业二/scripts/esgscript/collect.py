"""检索 → 抓取 → 筛选：把一路路检索收敛成运行目录里的 data.json。

中间结果落在运行目录的 work/ 下并按地址缓存，中途被打断后重跑会接着做。
网络失败一律降级：那一路检索、那一页或那一次模型调用记为失败，不中断整次运行。
"""

import json
import shutil
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, fields
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from . import prompts, queries
from .bridge import contract
from .ccgp import SOURCE_SITE
from .llm import LLM
from .pages import contains, fetch_page
from .parsing import (
    PROVINCES,
    normalize_topic,
    notice_type_of,
    parse_amount,
    purchaser_type_of,
    region_of,
    rule_scope,
    source_site_of,
    tier_of,
)
from .zhipu import ZhipuSearch

WORK_DIR = "work"
"""中间结果的目录：spec.json、search.json、pages.jsonl、select.jsonl、usage.json。"""

MAX_PAGES = {"monthly-report": 60, "bid-radar": 160}
"""最多读多少页：月报 60 页、招投标 160 页。"""

_NOTICE_TYPES = ("tender", "award", "other")
_SECTION_ORDER = {name: index for index, name in enumerate(prompts.MONTHLY_SECTIONS)}

Entry = dict[str, Any]
"""一条候选的处理结果：path（走了哪条路）、record（登记下来的记录或 None）、issues（需要复核的原因）。"""


@dataclass(frozen=True)
class CollectSpec:
    """一次收集的参数：案例、模式、时间窗与预算。"""

    case: str
    mode: str
    window_start: date
    window_end: date
    client: str | None = None
    industry: str | None = None
    client_en: str = ""
    industry_en: str = ""
    budget: int = 20
    max_pages: int = 0
    peers: tuple[str, ...] = ()
    ccgp: bool = True
    seen_path: str | None = None
    concurrency: int = 4

    @property
    def page_limit(self) -> int:
        return self.max_pages or MAX_PAGES[self.case]

    @property
    def days(self) -> int:
        return (self.window_end - self.window_start).days + 1


# ---- 读写中间结果 ----


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_jsonl(path: Path) -> dict[str, Any]:
    """按 url 索引读回逐行 JSON；同一 url 以最后一次为准。"""
    items: dict[str, Any] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            items[item["url"]] = item
    return items


def append_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def load_spec(out_dir: Path) -> CollectSpec:
    raw = read_json(out_dir / WORK_DIR / "spec.json", None)
    if not isinstance(raw, dict):
        raise SystemExit(f"{out_dir} 下没有 work/spec.json：先运行 collect 写下参数")
    return CollectSpec(
        **{field.name: raw[field.name] for field in fields(CollectSpec) if field.name in raw}
        | {
            "window_start": date.fromisoformat(raw["window_start"]),
            "window_end": date.fromisoformat(raw["window_end"]),
        }
    )


# ---- 已见清单 ----


def snapshot_seen(out_dir: Path, seen_path: Path | None) -> dict[str, Any]:
    """监控模式开始检索前，把已见清单原样复制为运行目录下的 seen_before.json（已有则不动）。"""
    target = out_dir / contract.SEEN_SNAPSHOT_FILE
    if target.is_file():
        return _read_seen(target)
    if seen_path is not None and seen_path.is_file():
        shutil.copyfile(seen_path, target)
    else:
        write_json(target, {"records": []})
    return _read_seen(target)


def _read_seen(target: Path) -> dict[str, Any]:
    snapshot = read_json(target, {"records": []})
    return snapshot if isinstance(snapshot, dict) else {"records": []}


def seen_keys(snapshot: Any) -> set[str]:
    items = snapshot if isinstance(snapshot, list) else contract.as_dict(snapshot).get("records", [])
    return {
        contract.dedup_key(item["url"])
        for item in items
        if isinstance(item, dict) and isinstance(item.get("url"), str)
    }


# ---- 检索 ----


def _run_task(task: queries.SearchTask) -> dict[str, Any]:
    try:
        return {"ok": True, "hits": task.run(), "error": None}
    except Exception as exc:  # 这一路失败只记一笔，不影响其它路
        return {"ok": False, "hits": [], "error": type(exc).__name__}


def stage_search(spec: CollectSpec, work: Path, zhipu: ZhipuSearch) -> list[dict[str, Any]]:
    """跑完查询矩阵里还没跑过的检索，再按去重键把命中合并。失败的路留在缓存里，重跑不再试。"""
    cache: dict[str, Any] = read_json(work / "search.json", {})
    tasks = queries.build_tasks(spec, zhipu)
    pending = [task for task in tasks if task.key not in cache]
    with ThreadPoolExecutor(max_workers=spec.concurrency) as pool:
        results = list(pool.map(_run_task, pending))
    for task, result in zip(pending, results, strict=True):
        cache[task.key] = {"label": task.label, "backend": task.backend, "text": task.text, **result}
    write_json(work / "search.json", cache)
    return merge_hits(cache, tasks)


_REDIRECT_HOSTS = ("google.com", "bing.com")
"""搜索引擎返回的不透明跳转链接：不是公告的真实地址，读不出东西。"""


def _is_redirect_wrapper(url: str) -> bool:
    host = url.split("/")[2].lower() if "://" in url else ""
    return any(host == name or host.endswith("." + name) for name in _REDIRECT_HOSTS)


def merge_hits(cache: dict[str, Any], tasks: list[queries.SearchTask]) -> list[dict[str, Any]]:
    """同一页面的多次命中合成一条，记下它被哪些检索路命中、来自哪个入口。"""
    merged: dict[str, dict[str, Any]] = {}
    for task in tasks:
        for hit in cache.get(task.key, {}).get("hits", []):
            if _is_redirect_wrapper(hit["url"]):
                continue
            item = merged.setdefault(contract.dedup_key(hit["url"]), {**hit, "labels": [], "origins": []})
            if task.label not in item["labels"]:
                item["labels"].append(task.label)
            if task.backend not in item["origins"]:
                item["origins"].append(task.backend)
            if task.backend == "ccgp":
                item["source_site"] = SOURCE_SITE
    return list(merged.values())


def search_counts(cache: dict[str, Any]) -> dict[str, Any]:
    """各入口的成功、失败路数。"""
    counts = Counter((entry["backend"], entry["ok"]) for entry in cache.values())
    return {
        backend: {"ok": counts[backend, True], "failed": counts[backend, False]}
        for backend in ("zhipu", "ccgp")
        if counts[backend, True] or counts[backend, False]
    }


def search_summary(work: Path) -> dict[str, Any]:
    """检索情况的汇总，渲染「方法与来源说明」「覆盖范围」时用。"""
    cache: dict[str, Any] = read_json(work / "search.json", {})
    done = [entry for entry in cache.values() if isinstance(entry, dict)]
    return {
        "total": len(done),
        **search_counts(cache),
        "queries": list(
            dict.fromkeys(
                entry["text"] for entry in done if entry["backend"] == "zhipu" and entry.get("text")
            )
        ),
        "keywords": list(
            dict.fromkeys(entry["text"] for entry in done if entry["backend"] == "ccgp" and entry.get("text"))
        ),
    }


# ---- 挑候选 ----


def _monthly_score(spec: CollectSpec, hit: dict[str, Any]) -> float:
    text = f"{hit['title']} {hit.get('snippet', '')}".lower()
    score = 0.0
    if spec.client and spec.client.lower() in text:
        score += 5
    if spec.client_en and spec.client_en.lower() in text:
        score += 4
    score += 2 * sum(1 for word in (spec.industry or "").split("·") if word and word in text)
    return score


def _bid_score(rule: dict[str, Any], hit: dict[str, Any], monitoring: bool) -> float:
    """监控模式偏重招标公告，汇总模式偏重中标公告；政采网直连的命中优先。"""
    wanted = "tender" if monitoring else "award"
    score = 3.0 if rule["in_scope"] and not rule["needs_review"] else 1.0
    if "ccgp" in hit["origins"]:
        score += 1
    if notice_type_of(hit["title"]) == wanted:
        score += 1
    return score


def _new_enough(spec: CollectSpec, hit: dict[str, Any], seen: set[str]) -> bool:
    """监控模式的初筛：已见过的不要；列表自带发布日期的，不晚于基线日的不要。"""
    if contract.dedup_key(hit["url"]) in seen:
        return False
    published = contract.parse_date(hit.get("published_at"))
    return published is None or spec.window_start < published <= spec.window_end


def pick_candidates(spec: CollectSpec, hits: list[dict[str, Any]], seen: set[str]) -> list[dict[str, Any]]:
    """决定读哪些页：月报按与客户、行业的相关度排序；招投标先按关键词规则筛掉无关的。"""
    ranked: list[tuple[float, dict[str, Any]]] = []
    for hit in hits:
        if spec.case == "monthly-report":
            ranked.append((_monthly_score(spec, hit), hit))
            continue
        rule = rule_scope(hit["title"], hit.get("snippet"))
        if rule["topic"] is None and "ccgp" not in hit["origins"]:
            continue
        monitoring = spec.mode == "monitor"
        if monitoring and not _new_enough(spec, hit, seen):
            continue
        known = contract.parse_date(hit.get("published_at"))  # 政采网列表自带日期：窗外的不必读
        if known is not None and not spec.window_start <= known <= spec.window_end:
            continue
        ranked.append((_bid_score(rule, hit, monitoring), hit))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [hit for _, hit in ranked[: spec.page_limit]]


# ---- 抓取 ----


def stage_fetch(work: Path, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    pages = read_jsonl(work / "pages.jsonl")
    pending = [hit["url"] for hit in candidates if hit["url"] not in pages]
    with ThreadPoolExecutor(max_workers=6) as pool:
        fetched = list(pool.map(fetch_page, pending))
    append_jsonl(work / "pages.jsonl", fetched)
    pages.update({page["url"]: page for page in fetched})
    return pages


# ---- 筛选 ----


def _iso(value: object) -> str | None:
    parsed = contract.parse_date(value)
    return parsed.isoformat() if parsed else None


def _in_window(spec: CollectSpec, published: str | None) -> bool:
    parsed = contract.parse_date(published)
    return parsed is not None and spec.window_start <= parsed <= spec.window_end


def _plausible(spec: CollectSpec, published: object) -> bool:
    """日期线索可不可信：比时间窗起始日早一年多的，一般是页面上的无关日期（栏目创建时间之类），不采信。"""
    parsed = contract.parse_date(published)
    return parsed is not None and spec.window_start - timedelta(days=370) <= parsed <= spec.window_end


def _section_from_labels(hit: dict[str, Any]) -> str:
    for part in queries.MONTHLY_PARTS:
        if any(label.startswith(part) for label in hit.get("labels") or []):
            return part
    return "行业新闻与最佳实践"


def _normalize_region(value: object) -> str | None:
    text = str(value or "").strip()
    return next((name for name in PROVINCES if text.startswith(name)), None)


def _monthly_record(
    spec: CollectSpec,
    hit: dict[str, Any],
    page: dict[str, Any],
    picked: dict[str, Any],
    benchmark_query: bool,
) -> tuple[dict[str, Any] | None, list[str]]:
    """把模型的判断整理成一条证据；发布日期、是否落窗、摘录是否出自原文由代码判定。"""
    issues: list[str] = []
    text = page.get("text") or ""
    claim = str(picked.get("claim") or "").strip()
    quote = str(picked.get("quote") or "").strip()
    if not claim or not quote:
        return None, ["模型没有给出结论或摘录"]
    if len(quote) > contract.QUOTE_MAX_CHARS:
        quote = quote[: contract.QUOTE_MAX_CHARS]
        issues.append("摘录超过 50 字，已截到 50 字")
    hint = page.get("date_hint")
    published = _iso(picked.get("published_at")) or (hint if _plausible(spec, hint) else None)
    benchmark = bool(picked.get("is_benchmark")) or benchmark_query
    if published is not None and not _in_window(spec, published) and not benchmark:
        verification = "excluded"
    elif text and contains(text, quote):
        verification = "verified"
    else:
        verification = "summary-only"
        if text:
            issues.append("摘录在所取的正文里找不到，已降为仅见摘要")
    section = (
        picked.get("section")
        if picked.get("section") in prompts.MONTHLY_SECTIONS
        else _section_from_labels(hit)
    )
    if benchmark:
        section = "对标企业动态"
    rule_tier = tier_of(hit["url"])
    tier = rule_tier if rule_tier is not None else (picked["tier"] if picked.get("tier") in (1, 2) else 2)
    record: dict[str, Any] = {
        "id": 0,
        "section": section,
        "claim": claim,
        "url": hit["url"],
        "published_at": published,
        "quote": quote,
        "credibility_tier": int(tier),
        "verification": verification,
    }
    if benchmark:
        record["is_benchmark"] = True
    if verification == "excluded":
        record["excluded_reason"] = str(picked.get("reason") or f"发布日期 {published} 在时间窗外")
    return record, issues


def _bid_record(
    spec: CollectSpec,
    hit: dict[str, Any],
    page: dict[str, Any],
    picked: dict[str, Any],
    rule: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    """把模型抽出的字段整理成一条招标记录；金额换算、主题归一、范围复核由代码把关。"""
    if not isinstance(picked, dict):
        return None, ["模型输出不是对象"]
    issues: list[str] = []
    text = page.get("text") or ""
    in_scope = bool(picked.get("in_scope"))
    notice_type = (
        picked.get("notice_type") if picked.get("notice_type") in _NOTICE_TYPES else rule["notice_type"]
    )
    amount_text = str(picked.get("amount_text") or "").strip() or None
    amount: float | None = None
    if amount_text is not None:
        if text and not contains(text, amount_text):
            issues.append(f"金额写法「{amount_text}」在所取的正文里找不到，金额记为 null")
            amount_text = None
        else:
            amount = parse_amount(amount_text)
            if amount is None:
                issues.append(f"金额写法「{amount_text}」换算不出确定金额，记为 null")
    topic = (
        normalize_topic(picked.get("topic"))
        if in_scope
        else str(picked.get("topic") or rule["topic"] or "其它")[:20]
    )
    if topic is None:
        topic, issues = rule["topic"], [*issues, "判为范围内但主题不在六类里，已按关键词归类"]
    if rule["topic"] is not None and rule["in_scope"] != in_scope:
        issues.append(f"范围判断与关键词规则相反（规则判为{'范围内' if rule['in_scope'] else '边界外'}）")
    if picked.get("needs_review"):
        issues.append("模型对范围或类型拿不准")
    hint = page.get("date_hint")
    published = (
        hit.get("published_at")
        or _iso(picked.get("published_at"))
        or (hint if _plausible(spec, hint) else None)
    )
    purchaser = str(picked["purchaser"]).strip() if picked.get("purchaser") else hit.get("purchaser")
    record: dict[str, Any] = {
        "title": hit["title"],
        "url": hit["url"],
        "notice_type": notice_type,
        "published_at": published,
        "purchaser": purchaser,
        "region": _normalize_region(picked.get("region"))
        or hit.get("region")
        or region_of(purchaser, text[:600]),
        "topic": topic,
        "in_scope": in_scope,
        "amount": amount,
        "amount_text": amount_text,
        "winner": str(picked["winner"]).strip() if picked.get("winner") else None,
        "source_site": hit.get("source_site") or source_site_of(hit["url"]),
        "verification": "verified" if page.get("ok") else "summary-only",
        "purchaser_type": purchaser_type_of(purchaser),
    }
    if published is not None and not _in_window(spec, published):  # 落在时间窗外的公告不进统计
        record["verification"] = "excluded"
        record["excluded_reason"] = f"发布日期 {published} 在时间窗外"
    if spec.mode == "monitor":
        record["deadline"] = str(picked["deadline"]).strip() if picked.get("deadline") else None
        record["summary"] = str(picked["summary"]).strip() if picked.get("summary") else None
    return record, issues


def _select_one(spec: CollectSpec, hit: dict[str, Any], page: dict[str, Any], llm: LLM) -> Entry:
    base = {"url": hit["url"], "title": hit["title"], "record": None}
    if spec.case == "monthly-report":
        benchmark_query = any("对标" in label for label in hit.get("labels") or [])
        published = page.get("date_hint")
        if (
            page.get("text")
            and published
            and not benchmark_query
            and _plausible(spec, published)
            and not _in_window(spec, published)
        ):
            return base | {"path": "date-excluded", "issues": [f"发布日期 {published} 在时间窗外，未送模型"]}
        picked = llm.json(prompts.SELECT_MONTHLY_SYSTEM, prompts.monthly_select(spec, hit, page))
        if not (isinstance(picked, dict) and picked.get("relevant")):
            return base | {"path": "not-relevant", "issues": []}
        record, issues = _monthly_record(spec, hit, page, picked, benchmark_query)
        return base | {"path": "model", "record": record, "issues": issues}
    rule = rule_scope(hit["title"]) | {"notice_type": notice_type_of(hit["title"])}
    picked = llm.json(prompts.SELECT_BID_SYSTEM, prompts.bid_select(spec, hit, page, rule))
    record, issues = _bid_record(spec, hit, page, picked, rule)
    return base | {"path": "model", "record": record, "issues": issues}


def _is_new(spec: CollectSpec, record: dict[str, Any], seen: set[str]) -> bool:
    """监控模式的硬条件：招标公告、发布日期严格晚于基线日且不晚于今天、不在已见清单里。"""
    published = contract.parse_date(record.get("published_at"))
    return (
        record.get("notice_type") == "tender"
        and published is not None
        and spec.window_start < published <= spec.window_end
        and contract.dedup_key(record["url"]) not in seen
    )


def stage_select(
    spec: CollectSpec,
    work: Path,
    candidates: list[dict[str, Any]],
    pages: dict[str, Any],
    llm: LLM,
    seen: set[str],
) -> list[Entry]:
    """逐页筛选：日期明确在窗外的月报页面不送模型，其余交给模型抽取，再由代码把关。"""
    cache = read_jsonl(work / "select.jsonl")

    def one(hit: dict[str, Any]) -> Entry:
        page = pages.get(hit["url"]) or {"url": hit["url"], "ok": False, "text": "", "error": "未抓取"}
        try:
            return _select_one(spec, hit, page, llm)
        except Exception as exc:  # 一次模型调用失败只丢这一页
            return {
                "url": hit["url"],
                "title": hit["title"],
                "record": None,
                "path": "failed",
                "issues": [f"模型调用失败（{type(exc).__name__}）"],
            }

    pending = [hit for hit in candidates if hit["url"] not in cache]
    with ThreadPoolExecutor(max_workers=spec.concurrency) as pool:
        results = list(pool.map(one, pending))
    append_jsonl(work / "select.jsonl", results)
    cache.update({item["url"]: item for item in results})
    entries: list[Entry] = []
    for hit in candidates:
        entry = dict(cache[hit["url"]])
        if (
            spec.mode == "monitor"
            and entry.get("record") is not None
            and not _is_new(spec, entry["record"], seen)
        ):
            entry = entry | {"record": None, "path": "not-new"}
        entries.append(entry)
    return entries


# ---- 汇总成产物 ----


def _evidence_order(record: dict[str, Any]) -> tuple[int, int, int]:
    published = contract.parse_date(record["published_at"])
    return (
        _SECTION_ORDER.get(record["section"], 9),
        record["verification"] == "excluded",
        -(published.toordinal() if published else 0),
    )


def _bid_order(record: dict[str, Any]) -> tuple[int, int, int]:
    published = contract.parse_date(record["published_at"])
    return (
        not record["in_scope"],
        record["notice_type"] != "award",
        -(published.toordinal() if published else 0),
    )


def write_data(out_dir: Path, spec: CollectSpec, entries: list[Entry]) -> dict[str, Any]:
    """把登记下来的记录写成 data.json：月报是证据表（角标从 1 编起），招投标是招标记录。"""
    records = [entry["record"] for entry in entries if entry.get("record")]
    if spec.case == "monthly-report":
        records.sort(key=_evidence_order)
        for index, record in enumerate(records, start=1):
            record["id"] = index
        data: dict[str, Any] = {"evidence": records}
    else:
        records.sort(key=_bid_order)
        data = {"records": records}
    write_json(out_dir / contract.DATA_FILE, data)
    return data


def write_review(out_dir: Path, entries: list[Entry]) -> int:
    """需要复核的条目单列成 review.json，交给智能体判断。"""
    items = [
        {
            "url": entry["url"],
            "title": entry.get("title"),
            "issues": entry["issues"],
            "record": entry.get("record"),
        }
        for entry in entries
        if entry.get("issues")
    ]
    write_json(out_dir / "review.json", items)
    return len(items)


def run(
    spec: CollectSpec, out_dir: Path, *, stages: tuple[str, ...] = ("search", "fetch", "select")
) -> dict[str, Any]:
    """按阶段收集：没被点名的阶段不跑，直接用 work/ 里的缓存。任何阶段失败都不抛出，结果里记明。"""
    started = time.perf_counter()
    work = out_dir / WORK_DIR
    work.mkdir(parents=True, exist_ok=True)
    raw = asdict(spec) | {
        "window_start": spec.window_start.isoformat(),
        "window_end": spec.window_end.isoformat(),
    }
    write_json(work / "spec.json", raw)
    snapshot = (
        snapshot_seen(out_dir, Path(spec.seen_path) if spec.seen_path else None)
        if spec.mode == "monitor"
        else None
    )
    seen = seen_keys(snapshot) if snapshot is not None else set()
    with ZhipuSearch() as zhipu, LLM() as llm:
        tasks = queries.build_tasks(spec, zhipu)
        hits = (
            stage_search(spec, work, zhipu)
            if "search" in stages
            else merge_hits(read_json(work / "search.json", {}), tasks)
        )
        candidates = pick_candidates(spec, hits, seen)
        pages = stage_fetch(work, candidates) if "fetch" in stages else read_jsonl(work / "pages.jsonl")
        if "select" in stages:
            entries = stage_select(spec, work, candidates, pages, llm, seen)
        else:
            cache = read_jsonl(work / "select.jsonl")
            entries = [dict(cache[hit["url"]]) for hit in candidates if hit["url"] in cache]
        usage = llm.usage.as_dict()
    _add_usage(work, usage)
    add_stage_time(work, "collect_s", time.perf_counter() - started)
    data = write_data(out_dir, spec, entries)
    return {
        "stages": list(stages),
        "searches": search_counts(read_json(work / "search.json", {})),
        "hits": len(hits),
        "candidates": len(candidates),
        "pages_fetched": {
            "ok": sum(1 for hit in candidates if pages.get(hit["url"], {}).get("ok")),
            "failed": sum(1 for hit in candidates if hit["url"] in pages and not pages[hit["url"]]["ok"]),
        },
        "paths": dict(Counter(entry.get("path", "pending") for entry in entries)),
        "records": len(data.get("evidence") or data.get("records") or []),
        "needs_review": write_review(out_dir, entries),
        "model_usage": usage,
        "elapsed_s": round(time.perf_counter() - started, 1),
    }


def _add_usage(work: Path, usage: dict[str, int]) -> None:
    """累计各次运行的模型用量（分阶段重跑时不丢）；各阶段的耗时另记在同名文件里。"""
    total = read_json(work / "usage.json", {})
    merged = {
        **total,
        **{
            name: int(total.get(name, 0)) + usage[name] for name in ("calls", "input_tokens", "output_tokens")
        },
    }
    write_json(work / "usage.json", merged)


def add_stage_time(work: Path, stage: str, seconds: float) -> None:
    """给某个阶段累计耗时（秒）；运行记录里的耗时是各阶段之和。"""
    total = read_json(work / "usage.json", {})
    total[stage] = round(float(total.get(stage, 0.0)) + seconds, 1)
    write_json(work / "usage.json", total)

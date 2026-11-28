#!/usr/bin/env python3
"""esgjudge：两版 skill 对比实验的可溯源率核验与 LLM 盲评（单文件）。

三个子命令：

- ``trace`` 可溯源率核验：月报对每条未排除证据核三项（来源可达 / 日期落窗 / 原文支持），
  招投标对范围内记录核前两项；核验结果缓存到运行目录的 ``trace.json``，重跑时同一来源
  与同一摘录不重复联网、不重复调模型。
- ``judge`` 盲评：两份报告只以「报告甲 / 报告乙」交给模型按五项评分表打分，评两遍并交换
  甲乙顺序，每项取两遍均值；模型不接触运行目录名与 run.json。
- ``calibrate`` 校准：同一套评分表评已知优劣的两份报告，好报告总分应当更高，
  方向不对以非零退出码结束。

用法（在 作业二/scripts 下，Python 用 py312）::

    python esgjudge.py trace <运行目录>... --out <json> [--limit 60]
    python esgjudge.py judge <运行目录A> <运行目录B> --out <json> [--limit 60]
    python esgjudge.py calibrate <好报告目录> <差报告目录> [--limit 60]

模型凭据读 邓帅/.env（API_KEY / BASE_URL / BASE_MODEL），任何值都不打印。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI

TOOLS_DIR = Path(__file__).resolve().parent  # 脚本目录，esgtools 与本脚本同级
sys.path.insert(0, str(TOOLS_DIR))

from esgtools.contract import (  # noqa: E402  须在把 tools 加进 sys.path 之后导入
    Verification,
    as_dict,
    load_bid_records,
    load_evidence,
    parse_date,
    raw_window,
)

ENV_PATH = Path(__file__).resolve().parents[3] / ".env"  # 邓帅/.env

MAX_WORKERS = 6  # 并发上限：抓页与调模型合计不超过 6
FETCH_TIMEOUT = 15.0
CACHE_FILE = "trace.json"
CACHE_TEXT_MAX = 20_000  # 缓存里保存的页面正文截断长度
REPORT_MAX_CHARS = 16_000  # 送给盲评模型的单份报告截断长度
DATA_MAX_CHARS = 12_000  # 送给盲评模型的结构化数据截断长度
LLM_TIMEOUT = 180.0
JUDGE_ATTEMPTS = 3  # 盲评首次 + 最多重试 2 次

DIMENSIONS = ("结构完整", "信息覆盖", "来源质量", "洞察深度", "准确性")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
CACHE_NOTE = (
    "esgjudge 的核验缓存：urls 存来源抓取结果（正文截断保存），support 存摘录支持判断；"
    "删除本文件即可全部重算。"
)
RETRY_NOTE = (
    "\n\n注意：上一次输出不是合格的评分 JSON（不是 JSON、缺项或分数越界）。"
    "请严格只输出一个 JSON 对象：含「甲」「乙」两份报告、每份五项齐全、score 为 1-10 的整数。"
)

type FetchFn = Callable[[str], tuple[bool, str | None, str | None]]
"""抓页函数：入参 url，返回 (是否可达, 页面正文, 失败原因)。测试可打桩替换。"""

type CompleteFn = Callable[[str], str]
"""模型补全函数：入参提示词，返回模型输出文本。测试可打桩替换。"""


# ---- 小工具 ----


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(path: Path, data: object) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def clip(text: str, max_chars: int) -> str:
    """截断超长文本，避免提示词无限膨胀。"""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"…（原文超长，仅保留前 {max_chars} 字）"


def squash(text: str) -> str:
    """去掉全部空白字符，供摘录与正文的宽松子串匹配。"""
    return re.sub(r"\s+", "", text)


def mark(ok: bool | None) -> str:
    if ok is None:
        return "—"
    return "✔" if ok else "✘"


def fmt_pct(value: float | None, num: int, den: int) -> str:
    if den == 0 or value is None:
        return "—"
    return f"{value * 100:.1f}%（{num}/{den}）"


# ---- 联网与模型（可替换的边界） ----


def fetch_page(url: str, timeout: float = FETCH_TIMEOUT) -> tuple[bool, str | None, str | None]:
    """抓取 url 的页面正文：返回 (是否可达, 正文文本, 失败原因)。

    可达 = 状态码 < 400 且提取出的正文非空。网络异常也算不可达，但失败原因非空时
    上层不会写入缓存，下次重跑会重试；HTTP 状态与空正文属于定论，会缓存。
    """
    try:
        with httpx.Client(
            timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            resp = client.get(url)
    except Exception as exc:  # 单条来源失败必须降级，绝不中断整次运行
        return False, None, f"网络错误：{type(exc).__name__}"
    if resp.status_code >= 400:
        return False, None, f"HTTP {resp.status_code}"
    soup = BeautifulSoup(resp.content, "html.parser")
    for tag in soup(["script", "style", "noscript", "template", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    text = re.sub(r"\s+", " ", root.get_text(" ", strip=True)).strip()
    if not text:
        return False, None, "正文为空"
    return True, text, None


def make_llm_client() -> tuple[OpenAI, str]:
    """从 邓帅/.env 读凭据建 OpenAI 兼容客户端；缺哪项报哪项的名字，绝不打印值。"""
    load_dotenv(ENV_PATH)
    api_key, base_url, model = os.getenv("API_KEY"), os.getenv("BASE_URL"), os.getenv("BASE_MODEL")
    names = ("API_KEY", api_key), ("BASE_URL", base_url), ("BASE_MODEL", model)
    missing = [name for name, value in names if not value]
    if missing:
        raise SystemExit(f"环境变量缺失：{'、'.join(missing)}（应在 {ENV_PATH} 里配置）")
    return OpenAI(api_key=api_key, base_url=base_url), str(model)


def resolve_model_id(client: OpenAI, name: str) -> str:
    """把配置的模型名解析成接口上的真实 id：对 /models 列表做大小写不敏感匹配。

    .env 里的写法可能与接口 id 大小写不一致（如 qwen3.8-Flash 与 qwen3.8-flash），
    直接用会 404；匹配不到或列表拉不下来时原样返回配置名，让接口自己报错。
    """
    try:
        for item in client.models.list():
            model_id = getattr(item, "id", None)
            if isinstance(model_id, str) and model_id.lower() == name.lower():
                return model_id
    except Exception:
        pass  # 列表拉不下来就按原配置名调用
    return name


def make_completer(model: str | None = None) -> CompleteFn:
    """造一个「提示词 → 模型输出」的函数。

    不传 model 就用 .env 里的 BASE_MODEL；模型名先经 resolve_model_id 纠正大小写，
    端点上确实不存在的名字仍会 404，此时可用 --model 显式指定可用的模型名。
    """
    client, env_model = make_llm_client()
    resolved = resolve_model_id(client, model or env_model)

    def complete(prompt: str) -> str:
        resp = client.chat.completions.create(
            model=resolved,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            timeout=LLM_TIMEOUT,
        )
        return resp.choices[0].message.content or ""

    return complete


# ---- 原文支持：子串直接判，子串外取片段调模型 ----


def relevant_snippet(page_text: str, quote: str, radius: int = 600, max_len: int = 2000) -> str:
    """取正文中与摘录最相关的片段：先定位与摘录开头最像的位置，再向两侧扩展。"""
    compact = re.sub(r"\s+", " ", page_text)
    head = squash(quote)[:6]
    if head:
        # 摘录开头 6 个字之间允许夹少量空白地在正文里定位
        pattern = r"\s{0,2}".join(re.escape(ch) for ch in head)
        found = re.search(pattern, compact)
        if found:
            start = max(0, found.start() - radius)
            return compact[start : start + max_len]
    return compact[:max_len]


def quote_support_prompt(quote: str, snippet: str) -> str:
    return (
        "判断下面这句摘录是否出自页面正文片段，或被正文片段支持（意思一致、或正文有更完整的表述）。\n"
        "只回答 yes 或 no，不要任何解释。\n\n"
        f"摘录：{quote}\n\n"
        f"页面正文片段：{snippet}"
    )


def yes_no(answer: str) -> bool:
    """把模型回答认成是/否；只认 yes（且没有 no）算肯定，其余一律算否。"""
    head = (answer or "").strip().lower()[:40]
    has_yes = "yes" in head
    has_no = re.search(r"\bno\b", head) is not None
    return has_yes and not has_no


def check_quote_supported(quote: str, page_text: str | None, complete: CompleteFn) -> tuple[bool, str]:
    """核一项摘录是否被页面正文支持，返回 (是否支持, 判定方式)。

    quote 去掉空白后是正文的子串 → 直接算支持，不调模型；否则截取正文里最相关的
    片段交给模型判断；页面取不到记不支持。
    """
    if not page_text:
        return False, "no-page"
    if squash(quote) in squash(page_text):
        return True, "substring"
    snippet = relevant_snippet(page_text, quote)
    verdict = yes_no(complete(quote_support_prompt(quote, snippet)))
    return verdict, "model" if verdict else "model-no"


# ---- 抽样：按章节/主题轮流取，尽量覆盖不同主题 ----


def sample_by_group(items: list[dict], group_of: Callable[[dict], str], limit: int) -> list[dict]:
    """条数超过 limit 时按组轮流抽样；limit<=0 表示不限制。"""
    if limit <= 0 or len(items) <= limit:
        return list(items)
    groups: dict[str, list[dict]] = {}
    for item in items:
        groups.setdefault(group_of(item), []).append(item)
    picked: list[dict] = []
    cursor = dict.fromkeys(groups, 0)
    while len(picked) < limit:
        progressed = False
        for group in groups:
            if cursor[group] < len(groups[group]):
                picked.append(groups[group][cursor[group]])
                cursor[group] += 1
                progressed = True
                if len(picked) >= limit:
                    break
        if not progressed:
            break
    return picked


def group_of_monthly(item: dict) -> str:
    return str(item.get("section") or item.get("group") or "未分章节")


def group_of_bids(item: dict) -> str:
    return str(item.get("topic") or item.get("source_site") or "无主题")


# ---- 运行目录读取 ----


def detect_kind(run_dir: Path) -> tuple[str, str, list]:
    """识别运行目录的类型：月报（证据表 evidence）或招投标（招标记录 records）。

    返回 (kind, data_key, data.json 里的记录数组原文)。
    """
    raw = json.loads((run_dir / "data.json").read_text(encoding="utf-8"))
    obj = as_dict(raw)
    if isinstance(obj.get("evidence"), list):
        return "monthly", "evidence", obj["evidence"]
    if isinstance(obj.get("records"), list):
        return "bids", "records", obj["records"]
    raise SystemExit(f"{run_dir}：data.json 既没有 evidence（证据表）也没有 records（招标记录）数组")


def load_window(run_dir: Path) -> tuple[date | None, date | None]:
    """读 run.json 的 time_window；读不到返回 (None, None)，落窗一率按未知计。"""
    try:
        record_raw = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    return raw_window(record_raw)


def monthly_entries(run_dir: Path) -> tuple[list[dict], dict]:
    """读月报证据表：未排除的证据进入核验。返回 (核验条目, 总数计数)。"""
    raw = json.loads((run_dir / "data.json").read_text(encoding="utf-8"))
    table = load_evidence(raw)
    total = len(table.ids)  # 含字段不合规的记录
    parse_failed = total - len(table.records)
    eligible = [record for record in table.records if record.verification is not Verification.EXCLUDED]
    entries = [
        {
            "id": record.id,
            "group": record.section,
            "claim": record.claim,
            "url": record.url,
            "published_at": record.published_at,
            "quote": record.quote,
        }
        for record in eligible
    ]
    counts = {"total": total, "parse_failed": parse_failed, "excluded": total - parse_failed - len(eligible)}
    return entries, counts


def bids_entries(run_dir: Path) -> tuple[list[dict], dict]:
    """读招标记录：范围内（in_scope 为真）的记录进入核验。返回 (核验条目, 总数计数)。"""
    raw = json.loads((run_dir / "data.json").read_text(encoding="utf-8"))
    table = load_bid_records(raw)
    total = len(table.raws)
    parse_failed = sum(1 for entry in table.entries if entry is None)
    entries = []
    for pos, record in enumerate(table.entries):
        if record is None or not record.in_scope:
            continue
        entries.append(
            {
                "id": pos + 1,  # data.json 里的第几条
                "group": record.topic or record.source_site or str(record.notice_type),
                "title": record.title,
                "url": record.url,
                "published_at": record.published_at,
            }
        )
    counts = {
        "total": total,
        "parse_failed": parse_failed,
        "out_of_scope": total - parse_failed - len(entries),
    }
    return entries, counts


# ---- 核验缓存（trace.json） ----


def load_cache(run_dir: Path) -> dict:
    """读运行目录的核验缓存；文件缺失或结构不对就返回空缓存。"""
    path = run_dir / CACHE_FILE
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        ok_shape = (
            isinstance(data, dict)
            and isinstance(data.get("urls"), dict)
            and isinstance(data.get("support"), dict)
        )
        if ok_shape:
            return data
    return {"note": CACHE_NOTE, "urls": {}, "support": {}}


def effective_cache(run_dir: Path) -> dict:
    """读缓存并剔除网络类失败（transient）的条目——它们不算定论，本次要重试。"""
    cache = load_cache(run_dir)
    cache["urls"] = {
        url: entry
        for url, entry in cache["urls"].items()
        if isinstance(entry, dict) and not entry.get("transient")
    }
    return cache


def save_cache(run_dir: Path, cache: dict) -> None:
    text = json.dumps(cache, ensure_ascii=False, indent=1) + "\n"
    (run_dir / CACHE_FILE).write_text(text, encoding="utf-8")


def support_key(url: str, quote: str) -> str:
    """摘录支持判断的缓存键：同一来源同一摘录只判一次。"""
    return f"{url}||{squash(quote)}"


def prefetch_urls(urls: list[str], cache: dict, fetch: FetchFn) -> tuple[int, int]:
    """把缓存里没有的来源并发抓取并写缓存。返回 (缓存命中数, 本次联网数)。"""
    missing = [url for url in urls if url not in cache["urls"]]
    hits = len(urls) - len(missing)
    if not missing:
        return hits, 0

    def fetch_one(url: str) -> None:
        try:
            reachable, text, error = fetch(url)
        except Exception as exc:  # 打桩函数或真实抓取的意外异常一律降级
            reachable, text, error = False, None, f"{type(exc).__name__}: {exc}"
        entry = {
            "reachable": reachable,
            "text": (text or "")[:CACHE_TEXT_MAX] or None,
            "fetched_at": now_iso(),
        }
        if error:
            entry["error"] = error
            entry["transient"] = True  # 网络类失败下次重试，不当定论
        cache["urls"][url] = entry

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        list(pool.map(fetch_one, missing))
    return hits, len(missing)


# ---- 逐条核验 ----


def classify_date(published_at: object, window: tuple[date | None, date | None]) -> str:
    """发布日期归类：in_window / out_of_window / unknown。

    解析不出日期算 unknown，不计入落窗率的分母；运行记录缺时间窗时同样按 unknown 处理。
    """
    parsed = parse_date(published_at)
    start, end = window
    if parsed is None or start is None or end is None:
        return "unknown"
    return "in_window" if start <= parsed <= end else "out_of_window"


def check_item(
    entry: dict,
    kind: str,
    window: tuple[date | None, date | None],
    cache: dict,
    complete: CompleteFn,
) -> dict:
    """核验一条证据/记录，返回逐条结果；任何一步失败都降级记入 error，绝不抛出。"""
    item: dict = {
        "id": entry.get("id"),
        "group": entry.get("group"),
        "title": entry.get("title"),
        "claim": entry.get("claim"),
        "url": entry.get("url"),
        "published_at": entry.get("published_at"),
        "date_status": classify_date(entry.get("published_at"), window),
        "reachable": False,
        "supported": None,  # 仅月报有值；招投标保持 None
        "support_how": None,
        "traceable": False,
        "error": None,
    }
    try:
        url_entry = cache["urls"].get(item["url"]) or {}
        item["reachable"] = bool(url_entry.get("reachable"))
        if url_entry.get("error"):
            item["error"] = url_entry["error"]
        if kind == "monthly":
            quote = str(entry.get("quote") or "")
            key = support_key(str(item["url"]), quote)
            if key in cache["support"]:
                item["supported"] = bool(cache["support"][key])
                item["support_how"] = "cache"
            else:
                supported, how = check_quote_supported(quote, url_entry.get("text"), complete)
                item["supported"], item["support_how"] = supported, how
                cache["support"][key] = supported
        item["traceable"] = (
            item["reachable"] and item["date_status"] == "in_window" and item["supported"] is not False
        )
    except Exception as exc:  # 兜底：单条彻底失败也不中断
        item["error"] = f"{type(exc).__name__}: {exc}"
        item["traceable"] = False
    return item


def summarize(items: list[dict], kind: str, counts: dict) -> tuple[dict, dict]:
    """汇总一组逐条核验结果，返回 (完整计数, 比率)。"""
    n = len(items)
    reachable = sum(1 for item in items if item["reachable"])
    known = [item for item in items if item["date_status"] != "unknown"]
    in_window = sum(1 for item in known if item["date_status"] == "in_window")
    supported = sum(1 for item in items if item["supported"])
    traceable = sum(1 for item in items if item["traceable"])
    full_counts = {
        **counts,
        "window_missing": counts.get("window_missing", False),
        "checked": n,
        "reachable": reachable,
        "date_known": len(known),
        "unknown_date": n - len(known),
        "in_window": in_window,
        "supported": supported if kind == "monthly" else None,
        "traceable": traceable,
    }
    rates = {
        "reachable_rate": rate_of(reachable, n),
        "in_window_rate": rate_of(in_window, len(known)),
        "support_rate": rate_of(supported, n) if kind == "monthly" else None,
        "traceable_rate": rate_of(traceable, n),
    }
    return full_counts, rates


def rate_of(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def trace_one_run(run_dir: Path, limit: int, fetch: FetchFn, complete: CompleteFn) -> dict:
    """核验一个运行目录，返回该目录的汇总与逐条结果。"""
    run_dir = Path(run_dir)
    kind, _, _ = detect_kind(run_dir)
    if kind == "monthly":
        entries, counts = monthly_entries(run_dir)
        group_of = group_of_monthly
    else:
        entries, counts = bids_entries(run_dir)
        group_of = group_of_bids
    window = load_window(run_dir)
    counts["window_missing"] = window[0] is None or window[1] is None

    sampled = sample_by_group(entries, group_of, limit)
    cache = effective_cache(run_dir)
    urls = list(dict.fromkeys(str(entry["url"]) for entry in sampled))
    hits, fetched = prefetch_urls(urls, cache, fetch)
    print(
        f"{run_dir.name}：核验 {len(sampled)} 条"
        f"（{len(urls)} 个来源，缓存命中 {hits}，本次联网 {fetched}）…"
    )

    results: list[dict | None] = [None] * len(sampled)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(check_item, entry, kind, window, cache, complete): idx
            for idx, entry in enumerate(sampled)
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    items = [result or {"error": "核验任务失败"} for result in results]

    save_cache(run_dir, cache)
    full_counts, rates = summarize(items, kind, counts)
    return {
        "run_dir": str(run_dir.resolve()),
        "kind": kind,
        "window": {
            "start": str(window[0]) if window[0] else None,
            "end": str(window[1]) if window[1] else None,
        },
        "counts": full_counts,
        "rates": rates,
        "items": items,
    }


def print_trace_report(runs: list[dict]) -> None:
    """在终端打印每个运行目录的 Markdown 汇总表与逐条简表。"""
    for run in runs:
        kind_label = "月报" if run["kind"] == "monthly" else "招投标"
        counts, rates = run["counts"], run["rates"]
        print(f"\n## 可溯源率：{run['run_dir']}（{kind_label}）\n")
        note = f"核验条数 {counts['checked']} / 总条数 {counts['total']}"
        skipped = counts.get("excluded", 0) + counts.get("out_of_scope", 0) + counts["parse_failed"]
        if skipped:
            note += f"（跳过 {skipped} 条：已排除 / 范围外 / 字段不合规）"
        if counts.get("window_missing"):
            note += "；run.json 缺时间窗，落窗一律按未知计"
        print(note + "\n")
        print("| 指标 | 数值 |")
        print("|---|---|")
        print(f"| 来源可达率 | {fmt_pct(rates['reachable_rate'], counts['reachable'], counts['checked'])} |")
        print(
            f"| 日期落窗率 | {fmt_pct(rates['in_window_rate'], counts['in_window'], counts['date_known'])}"
            f"（日期未知 {counts['unknown_date']} 条不计入分母） |"
        )
        if rates["support_rate"] is not None:
            n_sup, n_chk = counts["supported"], counts["checked"]
            print(f"| 原文支持率 | {fmt_pct(rates['support_rate'], n_sup, n_chk)} |")
        else:
            print("| 原文支持率 | —（招投标不核此项） |")
        print(f"| 可溯源率 | {fmt_pct(rates['traceable_rate'], counts['traceable'], counts['checked'])} |")
        print("\n| 编号 | 章节/主题 | 可达 | 日期 | 支持 | 可溯源 |")
        print("|---|---|---|---|---|---|")
        for item in run["items"]:
            labels = {"in_window": "窗内", "out_of_window": "窗外", "unknown": "未知"}
            label = labels.get(item.get("date_status"), "—")
            support = "—" if item.get("supported") is None else mark(item["supported"])
            group = item.get("group") or item.get("title") or "—"
            print(
                f"| {item.get('id', '—')} | {group} | {mark(item.get('reachable'))} | {label} "
                f"| {support} | {mark(item.get('traceable'))} |"
            )


def cmd_trace(
    run_dirs: list[Path],
    out_path: Path,
    limit: int,
    fetch: FetchFn = fetch_page,
    complete: CompleteFn | None = None,
    model: str | None = None,
) -> int:
    """trace 子命令：核验多个运行目录，写结果 JSON 并打印 Markdown 表。"""
    complete = complete or make_completer(model)
    runs = [trace_one_run(run_dir, limit, fetch, complete) for run_dir in run_dirs]
    result = {"generated_at": now_iso(), "runs": runs}
    write_json(out_path, result)
    print_trace_report(runs)
    print(f"\n结果已写入 {out_path}")
    return 0


# ---- 盲评 ----

JUDGE_RUBRIC = (
    "你是 ESG 情报报告的盲评评委。下面给你两份报告（报告甲、报告乙），以及各自附带的结构化数据。\n"
    "请独立给两份报告打分；不要猜测报告出自哪个版本、哪个系统或哪次运行。\n"
    "\n"
    "评分表（每项 1-10 分，整数）：\n"
    "- 结构完整：章节是否齐全、层次是否清楚，有没有空泛占位或只有标题没有内容的节。\n"
    "- 信息覆盖：对主题的覆盖面与信息量，重要方面有没有遗漏。\n"
    "- 来源质量：来源是否可靠，角标或引用标注是否规范、能否对应到附带的结构化数据。\n"
    "- 洞察深度：是否给出影响分析与可执行建议，而不是只罗列事实。\n"
    "- 准确性：报告中的陈述与其附带的数据是否一致、角标 [n] 能否对上数据记录；\n"
    "  陈述没有数据支撑或与数据矛盾要扣分。\n"
    "\n"
    "要求：每一项都给一句中文理由。只输出一个 JSON 对象，不要输出任何其它文字。\n"
    "格式（键名固定，「甲」「乙」各五项齐全，score 为 1-10 的整数，reason 为一句话）：\n"
    '{"甲": {"结构完整": {"score": 7, "reason": "…"}, "信息覆盖": {"score": 6, "reason": "…"},\n'
    '  "来源质量": {"score": 6, "reason": "…"}, "洞察深度": {"score": 5, "reason": "…"},\n'
    '  "准确性": {"score": 8, "reason": "…"}}, "乙": {…与甲同样结构的五项…}}\n'
)


def judge_prompt(report_a: str, data_a: str, report_b: str, data_b: str) -> str:
    """拼一份盲评提示词：评分表 + 报告甲 + 报告乙（各自附结构化数据）。"""
    return (
        JUDGE_RUBRIC
        + "\n—— 报告甲 ——\n"
        + report_a
        + "\n\n报告甲附带的结构化数据：\n"
        + data_a
        + "\n\n—— 报告乙 ——\n"
        + report_b
        + "\n\n报告乙附带的结构化数据：\n"
        + data_b
        + "\n"
    )


def parse_judge_json(text: str, dims: tuple[str, ...] = DIMENSIONS) -> dict | None:
    """从模型输出解析两份报告的评分；不是 JSON、缺项或分数越界都返回 None。"""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        raw = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    out: dict = {}
    for label in ("甲", "乙"):
        block = as_dict(as_dict(raw).get(label))
        per: dict = {}
        for dim in dims:
            entry = as_dict(block.get(dim))
            score = entry.get("score")
            if isinstance(score, str) and score.strip().isdigit():
                score = int(score)
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not 1 <= score <= 10:
                return None
            per[dim] = {"score": int(score), "reason": str(entry.get("reason", "")).strip()}
        out[label] = per
    return out


def ask_judge(prompt: str, complete: CompleteFn, attempts: int = JUDGE_ATTEMPTS) -> dict:
    """调模型评分；输出解析失败最多重试 2 次（共 attempts 次），仍失败就报错退出。"""
    tail = ""
    for attempt in range(attempts):
        text = complete(prompt if attempt == 0 else prompt + RETRY_NOTE)
        parsed = parse_judge_json(text)
        if parsed is not None:
            return parsed
        tail = clip(text, 200)
    raise SystemExit(f"模型评分输出连续 {attempts} 次解析失败，最后一次输出的开头：{tail}")


def aggregate_scores(first: dict, second: dict, dims: tuple[str, ...] = DIMENSIONS) -> dict:
    """两遍换序评分取均值。

    first 是第一遍（甲=目录 A、乙=目录 B），second 是交换顺序后的第二遍
    （它的「甲」是目录 B、「乙」是目录 A），所以目录 A 取 first.甲 与 second.乙 的均值。
    """
    out: dict = {}
    for key, r1, r2 in (("a", first["甲"], second["乙"]), ("b", first["乙"], second["甲"])):
        scores: dict = {}
        for dim in dims:
            s1, s2 = r1[dim]["score"], r2[dim]["score"]
            scores[dim] = {
                "round1": s1,
                "round2": s2,
                "mean": round((s1 + s2) / 2, 2),
                "reason_r1": r1[dim]["reason"],
                "reason_r2": r2[dim]["reason"],
            }
        total = round(sum(entry["mean"] for entry in scores.values()) / len(dims), 2)
        out[key] = {"scores": scores, "total": total}
    return out


def run_judge(dir_a: Path, dir_b: Path, limit: int, complete: CompleteFn) -> dict:
    """对两份报告跑两遍换序盲评，返回按目录对齐的均值结果（不写文件、不打印）。"""
    payloads: dict[str, tuple[str, str, str]] = {}
    for key, run_dir in (("a", dir_a), ("b", dir_b)):
        run_dir = Path(run_dir)
        kind, data_key, items = detect_kind(run_dir)
        report = clip((run_dir / "report.md").read_text(encoding="utf-8"), REPORT_MAX_CHARS)
        group_of = group_of_monthly if kind == "monthly" else group_of_bids
        sampled = sample_by_group(items, group_of, limit)
        data_text = clip(json.dumps({data_key: sampled}, ensure_ascii=False, indent=1), DATA_MAX_CHARS)
        payloads[key] = (report, data_text, kind)

    report_a, data_a, kind_a = payloads["a"]
    report_b, data_b, kind_b = payloads["b"]
    print(f"第 1 遍盲评（甲={Path(dir_a).name}，乙={Path(dir_b).name}）…")
    first = ask_judge(judge_prompt(report_a, data_a, report_b, data_b), complete)
    print(f"第 2 遍盲评（交换甲乙顺序：甲={Path(dir_b).name}，乙={Path(dir_a).name}）…")
    second = ask_judge(judge_prompt(report_b, data_b, report_a, data_a), complete)

    agg = aggregate_scores(first, second)
    return {
        "generated_at": now_iso(),
        "rubric": list(DIMENSIONS),
        "a": {"run_dir": str(Path(dir_a).resolve()), "kind": kind_a, **agg["a"]},
        "b": {"run_dir": str(Path(dir_b).resolve()), "kind": kind_b, **agg["b"]},
        "rounds": [
            {"round": 1, "甲": str(Path(dir_a).resolve()), "乙": str(Path(dir_b).resolve())},
            {"round": 2, "甲": str(Path(dir_b).resolve()), "乙": str(Path(dir_a).resolve())},
        ],
    }


def print_judge_table(result: dict) -> None:
    """打印按目录对齐的均值对比表（终端给人看，目录名不进模型提示词）。"""
    name_a = Path(result["a"]["run_dir"]).name
    name_b = Path(result["b"]["run_dir"]).name
    print("\n## 盲评对比（两遍换序取均值）\n")
    print(f"报告一：{name_a}　报告二：{name_b}\n")
    print(f"| 维度 | {name_a} | {name_b} |")
    print("|---|---|---|")
    for dim in DIMENSIONS:
        print(f"| {dim} | {result['a']['scores'][dim]['mean']} | {result['b']['scores'][dim]['mean']} |")
    print(f"| **总分（五项均值）** | **{result['a']['total']}** | **{result['b']['total']}** |")
    print("\n每项两遍原始分与理由见结果 JSON。")


def cmd_judge(
    dir_a: Path,
    dir_b: Path,
    out_path: Path,
    limit: int,
    complete: CompleteFn | None = None,
    model: str | None = None,
) -> int:
    """judge 子命令：盲评两份报告，写结果 JSON 并打印对比表。"""
    result = run_judge(dir_a, dir_b, limit, complete or make_completer(model))
    write_json(out_path, result)
    print_judge_table(result)
    print(f"\n结果已写入 {out_path}")
    return 0


# ---- 校准 ----


def direction_ok(good_total: float, bad_total: float) -> bool:
    """校准方向判断：好报告总分应严格高于差报告，持平也算方向不对。"""
    return good_total > bad_total


def cmd_calibrate(
    good_dir: Path,
    bad_dir: Path,
    limit: int,
    complete: CompleteFn | None = None,
    model: str | None = None,
) -> int:
    """calibrate 子命令：评已知优劣的两份报告，检验评分方向；方向不对返回 1。"""
    result = run_judge(good_dir, bad_dir, limit, complete or make_completer(model))
    good_total, bad_total = result["a"]["total"], result["b"]["total"]
    print_judge_table(result)
    diff = round(good_total - bad_total, 2)
    ok = direction_ok(good_total, bad_total)
    print(f"\n好报告总分 {good_total}，差报告总分 {bad_total}，分差 {diff:+}")
    print("校准方向：正确（好的更高）" if ok else "校准方向：不正确（预期好的更高，实际持平或相反）")
    return 0 if ok else 1


# ---- 命令行入口 ----


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="esgjudge",
        description="两版 skill 对比实验：可溯源率核验与 LLM 盲评。",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="子命令")

    p = sub.add_parser("trace", help="可溯源率核验：月报核三项（可达/落窗/原文支持），招投标核前两项")
    p.add_argument("run_dirs", nargs="+", help="运行目录（含 data.json 与 run.json）")
    p.add_argument("--out", required=True, help="结果 JSON 的落点")
    p.add_argument(
        "--limit", type=int, default=60, help="每个目录最多核验的条数，按章节/主题轮流抽样（默认 60）"
    )
    p.add_argument("--model", help="判原文支持所用的模型名（默认用 .env 的 BASE_MODEL；404 时可显式指定）")

    p = sub.add_parser("judge", help="两份报告的 LLM 盲评：五项评分、两遍换序取均值")
    p.add_argument("run_dir_a", help="运行目录 A（第一遍当报告甲）")
    p.add_argument("run_dir_b", help="运行目录 B（第一遍当报告乙）")
    p.add_argument("--out", required=True, help="结果 JSON 的落点")
    p.add_argument("--limit", type=int, default=60, help="送给模型评分的数据条数上限（默认 60）")
    p.add_argument("--model", help="盲评所用模型名（默认用 .env 的 BASE_MODEL；404 时可显式指定）")

    p = sub.add_parser("calibrate", help="用已知优劣的两份报告校准评分方向，方向不对以非零码退出")
    p.add_argument("good_dir", help="已知较好的报告目录")
    p.add_argument("bad_dir", help="已知较差的报告目录")
    p.add_argument("--limit", type=int, default=60, help="送给模型评分的数据条数上限（默认 60）")
    p.add_argument("--model", help="校准评分所用模型名（默认用 .env 的 BASE_MODEL；404 时可显式指定）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "trace":
        return cmd_trace([Path(d) for d in args.run_dirs], Path(args.out), args.limit, model=args.model)
    if args.command == "judge":
        return cmd_judge(
            Path(args.run_dir_a), Path(args.run_dir_b), Path(args.out), args.limit, model=args.model
        )
    if args.command == "calibrate":
        return cmd_calibrate(Path(args.good_dir), Path(args.bad_dir), args.limit, model=args.model)
    return 2


if __name__ == "__main__":
    sys.exit(main())

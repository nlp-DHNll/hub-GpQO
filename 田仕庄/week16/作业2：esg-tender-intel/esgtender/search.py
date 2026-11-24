"""检索层：博查 Web Search provider + 离线 fixture provider。

设计约束
--------
- 只有这一层碰网络；上层拿到的永远是统一的 ``Hit`` 列表。
- 单条 query 失败不向上抛，由 ``run_queries`` 收集为 failure，供报告里的
  「覆盖度声明」使用（README §11.2 无来源不入库 / 部分失败降级）。
- 检索结果按 ``sha1(provider|query|count|freshness)`` 落 cache，重复运行不重复计费。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from .env import load_env  # 配置只从 env.py 读（白名单），不要在本模块再解析 .env

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "cache" / "search"
FIXTURE_PATH = ROOT / "fixtures" / "sample_pages.json"

# 检索结果里的 URL 只允许这两种 scheme。`javascript:` / `data:` 会被模板原样写进
# href——autoescape 转义的是引号与尖括号，`javascript:alert(1)` 一个字符都不用
# 转义就能执行，必须在入库处挡掉。
_URL_SCHEMES = ("http://", "https://")


def _clean_url(value: str) -> str:
    """URL 合法返回原值，否则返回空串（调用方会据此丢记录）。"""
    url = (value or "").strip()
    return url if url.lower().startswith(_URL_SCHEMES) else ""


class SearchError(RuntimeError):
    """单条 query 检索失败。"""


class RateLimitError(SearchError):
    """触发限频（429）：可退避重试，与鉴权失败不同。"""


@dataclass(slots=True)
class Hit:
    title: str
    url: str
    snippet: str
    site: str
    published: str
    query: str
    provider: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Failure:
    query: str
    provider: str
    reason: str


# ------------------------------------------------------------------ cache
def _cache_file(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.json"


def _cache_key(provider: str, query: str, count: int, freshness: str) -> str:
    raw = f"{provider}|{query}|{count}|{freshness}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _read_cache(key: str, ttl_hours: float) -> list[Hit] | None:
    path = _cache_file(key)
    if not path.exists():
        return None
    if ttl_hours > 0 and time.time() - path.stat().st_mtime > ttl_hours * 3600:
        return None
    try:
        return [Hit(**item) for item in json.loads(path.read_text(encoding="utf-8"))]
    except (json.JSONDecodeError, TypeError):
        return None


def _write_cache(key: str, hits: list[Hit]) -> None:
    """原子写：先写 .tmp 再 replace，进程被 kill 也不会留下半截 JSON。"""
    target = _cache_file(key)
    tmp = target.with_suffix(".json.tmp")
    try:
        tmp.write_text(
            json.dumps([h.as_dict() for h in hits], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        os.replace(tmp, target)
    except OSError:
        tmp.unlink(missing_ok=True)
        pass  # 缓存失败不影响主流程


def sweep_cache(ttl_hours: float, *, now: float | None = None) -> int:
    """删除超过 TTL 的缓存文件，返回删除数量。

    TTL 只在读的时候判断，过期的文件本来就不会被用到；但如果不删，两年窗口
    一次就新增 325 个文件，目录里的死文件只会越攒越多（实测曾到 355 个 / 36 MB）。
    """
    if ttl_hours <= 0 or not CACHE_DIR.exists():
        return 0
    cutoff = (now or time.time()) - ttl_hours * 3600
    removed = 0
    for path in CACHE_DIR.glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


# ------------------------------------------------------------------ bocha
def _bocha_once(
    query: str,
    *,
    cfg: dict,
    api_key: str,
    endpoint: str,
    client: httpx.Client,
    freshness: str,
) -> list[Hit]:
    payload = {
        "query": query,
        "summary": True,
        "count": int(cfg.get("count", 50)),
        "freshness": freshness,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    resp = client.post(endpoint, json=payload, headers=headers)
    if resp.status_code in (401, 403):
        raise SearchError("博查鉴权失败：检查 BOCHA_API_KEY 是否有效")
    if resp.status_code == 429:
        raise RateLimitError("博查限频：并发过高或配额用尽")
    # 5xx / 网关错误页必须在这里转成 SearchError：`_bocha_with_retry` 只捕
    # SearchError 与 httpx 传输异常，裸 `raise_for_status()` 抛出的
    # HTTPStatusError 会直接穿过 `run_queries`，让整批已完成的分片结果一起丢。
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise SearchError(f"博查返回 HTTP {resp.status_code}") from exc

    try:
        body = resp.json()
    except ValueError as exc:  # 502 时对端常返回 HTML 错误页
        raise SearchError("博查返回非 JSON（可能是网关错误页）") from exc
    if not isinstance(body, dict):
        raise SearchError("博查返回结构异常：顶层不是对象")
    code = body.get("code")
    if code not in (None, 200, 0):
        raise SearchError(f"博查返回 code={code} msg={body.get('msg')}")

    values = ((body.get("data") or {}).get("webPages") or {}).get("value") or []
    hits: list[Hit] = []
    for item in values:
        snippet = item.get("summary") or item.get("snippet") or ""
        hits.append(
            Hit(
                title=(item.get("name") or "").strip(),
                url=_clean_url(item.get("url") or ""),
                snippet=snippet.strip(),
                site=(item.get("siteName") or "").strip(),
                published=(item.get("datePublished") or "").strip(),
                query=query,
                provider="bocha",
            )
        )
    return [h for h in hits if h.title and h.url]


def _bocha_with_retry(
    client: httpx.Client,
    query: str,
    *,
    cfg: dict,
    api_key: str,
    endpoint: str,
    key: str,
    freshness: str,
    use_cache: bool,
) -> list[Hit]:
    """带退避的重试。撞限频时退避更久（4s、8s），鉴权失败立刻放弃。"""
    retries = int(cfg.get("retry", 2))
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            hits = _bocha_once(
                query,
                cfg=cfg,
                api_key=api_key,
                endpoint=endpoint,
                client=client,
                freshness=freshness,
            )
            if use_cache:
                _write_cache(key, hits)
            return hits
        except RateLimitError as exc:
            last = exc
            if attempt < retries:
                time.sleep(2 ** (attempt + 2))  # 4s、8s：并发下给对端留出恢复时间
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = exc
            if attempt < retries:
                time.sleep(2**attempt)
        except SearchError as exc:
            last = exc
            if "鉴权" in str(exc):
                break  # Key 无效，重试只会把配额浪费在 401 上
            if attempt < retries:
                time.sleep(2**attempt)
    raise SearchError(str(last) if last else "未知检索错误")


def search_bocha(
    query: str,
    *,
    cfg: dict,
    api_key: str,
    endpoint: str,
    use_cache: bool = True,
    freshness: str | None = None,
    client: httpx.Client | None = None,
) -> list[Hit]:
    """单条 query 检索。

    ``client`` 可注入：批量检索必须复用同一个 client，否则每条 query 都要
    重新做 TCP + TLS 握手（两年窗口 325 次请求，光握手就是几十秒）。
    """
    count = int(cfg.get("count", 50))
    freshness = freshness or cfg.get("freshness", "noLimit")
    key = _cache_key("bocha", query, count, freshness)
    if use_cache:
        cached = _read_cache(key, float(cfg.get("cache_ttl_hours", 24)))
        if cached is not None:
            return cached

    owned = client is None
    if owned:
        client = httpx.Client(
            timeout=float(cfg.get("timeout", 20)), follow_redirects=True
        )
    try:
        return _bocha_with_retry(
            client,
            query,
            cfg=cfg,
            api_key=api_key,
            endpoint=endpoint,
            key=key,
            freshness=freshness,
            use_cache=use_cache,
        )
    except SearchError:
        raise
    except Exception as exc:  # 兜底：单条 query 的意外异常不该打掉整批 325 次请求
        raise SearchError(f"{type(exc).__name__}: {exc}") from exc
    finally:
        if owned:
            client.close()


# ------------------------------------------------------------------ fixture
def _fixture_tokens(query: str) -> list[str]:
    return [t for t in query.replace("，", " ").replace(",", " ").split() if t]


def search_fixture(query: str) -> list[Hit]:
    """离线样本 provider：按 query 里的词做包含匹配，用于无 Key 时验证全链路。"""
    if not FIXTURE_PATH.exists():
        raise SearchError(f"离线样本不存在：{FIXTURE_PATH}")
    items = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    tokens = _fixture_tokens(query)
    hits: list[Hit] = []
    for item in items:
        blob = f"{item.get('name','')} {item.get('snippet','')}"
        if tokens and not any(tok in blob for tok in tokens):
            continue
        hits.append(
            Hit(
                title=item.get("name", ""),
                url=_clean_url(item.get("url", "")),
                snippet=item.get("snippet", ""),
                site=item.get("siteName", ""),
                published=item.get("datePublished", ""),
                query=query,
                provider="fixture",
            )
        )
    return hits


# ------------------------------------------------------------------ 统一入口
def run_queries(
    queries: list[str], *, cfg: dict, use_cache: bool = True
) -> tuple[list[Hit], list[Failure]]:
    """跑完所有 (query, 时间切片) 组合。

    两条约束：
    1. **结果顺序必须稳定**。并发完成的先后是随机的，若直接 ``extend``，下游
       的「先到先得」去重与报告排序会跟着抖——同一份输入两次跑出两份报告。
       所以按任务原顺序回落结果（``results[task]``）。
    2. **单条失败不中断**。失败进 ``failures``，报告里要如实写「哪条 query 挂了」。
    """
    provider = str(cfg.get("provider", "bocha")).lower()
    endpoint = str(cfg.get("endpoint", "https://api.bochaai.com/v1/web-search"))
    api_key = ""

    # 顺手清掉过期缓存（与 TTL 同口径），否则目录里只会攒死文件
    sweep_cache(float(cfg.get("cache_ttl_hours", 24)))

    if provider == "bocha":
        credentials = load_env()  # 读一次就够：每次调用都重读文件纯属浪费
        api_key = credentials.get("BOCHA_API_KEY", "")
        if not api_key:
            raise SearchError(
                "未配置 BOCHA_API_KEY。请复制 config/.env.example 为 config/.env 并填入 Key，"
                "或加 --provider fixture 用离线样本验证流程。"
            )
        endpoint = credentials.get("BOCHA_ENDPOINT") or endpoint

    windows = cfg.get("freshness_list") or [cfg.get("freshness", "noLimit")]
    tasks = [(query, window) for query in queries for window in windows]

    if provider == "fixture":
        hits: list[Hit] = []
        for query, _window in tasks:
            hits.extend(search_fixture(query))
        return hits, []

    results: dict[tuple[str, str], list[Hit]] = {}
    errors: dict[tuple[str, str], str] = {}

    concurrency = max(1, int(cfg.get("concurrency", 4)))
    limits = httpx.Limits(
        max_connections=concurrency * 2, max_keepalive_connections=concurrency
    )
    with httpx.Client(
        timeout=float(cfg.get("timeout", 20)), follow_redirects=True, limits=limits
    ) as client:
        if concurrency == 1:
            for task in tasks:
                try:
                    results[task] = search_bocha(
                        task[0],
                        cfg=cfg,
                        api_key=api_key,
                        endpoint=endpoint,
                        use_cache=use_cache,
                        freshness=task[1],
                        client=client,
                    )
                except SearchError as exc:
                    errors[task] = str(exc)
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = {
                    pool.submit(
                        search_bocha,
                        query,
                        cfg=cfg,
                        api_key=api_key,
                        endpoint=endpoint,
                        use_cache=use_cache,
                        freshness=window,
                        client=client,
                    ): (query, window)
                    for query, window in tasks
                }
                for future in as_completed(futures):
                    task = futures[future]
                    try:
                        results[task] = future.result()
                    except SearchError as exc:
                        errors[task] = str(exc)

    ordered_hits: list[Hit] = []
    failures: list[Failure] = []
    for task in tasks:  # 按请求顺序回落，保证同一输入产出同一报告
        ordered_hits.extend(results.get(task, []))
        if task in errors:
            failures.append(
                Failure(query=task[0], provider=provider, reason=errors[task])
            )
    return ordered_hits, failures


def freshness_for(days: int) -> str:
    """把「回溯 N 天」翻译成博查的 freshness 取值。"""
    if days <= 1:
        return "oneDay"
    if days <= 7:
        return "oneWeek"
    if days <= 31:
        return "oneMonth"
    if days <= 365:
        return "oneYear"
    return "noLimit"


def freshness_windows_for(
    days: int,
    *,
    today: date | None = None,
    slice_days: int = 30,
    max_slices: int = 26,
) -> list[str]:
    """把「回溯 N 天」翻译成**一组** freshness 取值（按时间切片检索）。

    博查的 ``freshness`` 同时改变召回池与排序，取值越宽，top-N 越偏向
    「高相关的旧页面」，近期项目会被挤出榜单。实测 ``--days 90`` 单用
    ``oneYear`` 时保留条数是 ``--days 30`` 的严格子集（14 → 7，零新增）；
    整两年塞进一段（``2024-11-23..2026-11-23``）时，返回的 50 条稀疏撒在
    24 个月里，每月才 1–3 条，等于对时间轴均匀采样，完全失去密度。

    但博查的 ``freshness`` **接受日期区间** ``YYYY-MM-DD..YYYY-MM-DD``（闭区间，
    实测单日区间只返回当天页面）。因此宽窗口的正确做法不是放大单次检索的
    范围，而是**切段**：每段 30 天单独检索，段内 top-50 才有足够密度。

    段数上限 ``max_slices`` 用来兜住 ``--days 3650`` 这类请求：段数会超限时
    自动放长每段，而不是无限次计费。返回顺序从**最近**到**最远**。
    """
    if days <= 31:
        return [freshness_for(days)]

    base = today or date.today()
    slice_days = max(1, int(slice_days))
    # 段数会超上限就放长每段（先保证覆盖完整，再谈密度）
    slice_days = max(slice_days, math.ceil(days / max(1, max_slices)))

    windows: list[str] = []
    window_start = base - timedelta(days=max(days, 1) - 1)
    end = base
    while len(windows) < max_slices:
        # 末段裁到窗口起点，否则会多取几天（虽然本地还会过滤，但没必要计费）
        seg_start = max(window_start, end - timedelta(days=slice_days - 1))
        windows.append(f"{seg_start.isoformat()}..{end.isoformat()}")
        if seg_start <= window_start:
            break
        end = seg_start - timedelta(days=1)
    return windows

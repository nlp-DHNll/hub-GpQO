"""源白名单：加载 ``config/sources.yaml``、生成定向 query、分派抓取。

三档模式
--------
- ``api``：该源有独立接口。当前统一走博查，源本身只用于报告里的来源标注。
- ``search_site``：把 ``site:域名`` 追加到检索词后，圈定到白名单站点。零额外
  基础设施，是提高召回性价比最高的一档。
- ``crawl``：抓列表页 HTML。只对静态列表页有效，见 ``crawl.py`` 的边界说明。

默认关闭：多源会让请求数按源数量线性增长。``--sources`` 显式打开时才追加，
成本对使用者可见。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from . import crawl as crawl_mod
from . import search as search_mod

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "config" / "sources.yaml"
MODES = ("api", "search_site", "crawl")


class SourceError(ValueError):
    """配置非法（模式未知、缺域名、id 重复等）。"""


def load(path: Path | str | None = None) -> dict[str, Any]:
    path = Path(path) if path else DEFAULT_PATH
    if not path.exists():
        return {"version": 1, "defaults": {"enabled": False}, "sources": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    _validate(data)
    data["_path"] = str(path)
    return data


def _validate(cfg: dict[str, Any]) -> None:
    sources = cfg.get("sources") or []
    if not isinstance(sources, list):
        raise SourceError("sources 必须是列表")
    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            raise SourceError("sources 的每一项必须是字典")
        sid = str(source.get("id") or "").strip()
        if not sid:
            raise SourceError("源缺少 id")
        if sid in seen:
            raise SourceError(f"源 id 重复：{sid}")
        seen.add(sid)
        mode = str(source.get("mode") or "").strip()
        if mode not in MODES:
            raise SourceError(f"源 {sid} 的 mode={mode!r} 非法，可选：{' / '.join(MODES)}")
        if mode == "search_site" and not (source.get("domains") or []):
            raise SourceError(f"源 {sid} 是 search_site 模式，必须配 domains")
        if mode == "crawl" and not source.get("list_url"):
            raise SourceError(f"源 {sid} 是 crawl 模式，必须配 list_url")


def enabled(
    cfg: dict[str, Any], *, include_crawl: bool = False, force: bool = False
) -> list[dict[str, Any]]:
    """返回启用的源。

    ``force=True`` 对应命令行的 ``--sources``：忽略 ``defaults.enabled: false``
    这个全局默认值，但不覆盖源自己的 ``enabled: false``——那是「明确不要这个源」
    的意思（比如尚未实测的抓取源）。
    """
    defaults = cfg.get("defaults") or {}
    global_on = bool(defaults.get("enabled"))
    out: list[dict[str, Any]] = []
    for source in cfg.get("sources") or []:
        flag = source.get("enabled")
        if flag is None:
            active = global_on or force
        else:
            active = bool(flag)
        if not active:
            continue
        if source.get("mode") == "crawl" and not include_crawl:
            continue
        out.append(source)
    return out


def site_queries(
    cfg: dict[str, Any],
    *,
    fallback_keywords: list[str],
    suffix: str = "",
    limit: int | None = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    """为 ``search_site`` 源生成定向 query。

    每个源最多取 2 个关键词、每个域名一条。按 ``weight`` 降序截断到
    ``max_site_queries``——权重代表这个源的历史召回质量，先花在好源上。
    """
    defaults = cfg.get("defaults") or {}
    cap = int(limit if limit is not None else defaults.get("max_site_queries", 4))
    candidates: list[dict[str, Any]] = []
    for source in enabled(cfg, include_crawl=False, force=force):
        if source.get("mode") != "search_site":
            continue
        words = [w for w in (source.get("keywords") or fallback_keywords) if w][:2]
        domains = [d for d in (source.get("domains") or []) if d]
        for word_index, word in enumerate(words):
            for domain in domains:
                query = " ".join(f"{word} {suffix} site:{domain}".split())
                candidates.append(
                    {
                        "query": query,
                        "source_id": source.get("id"),
                        "source_name": source.get("name") or source.get("id"),
                        "weight": float(source.get("weight") or 0),
                        "order": word_index,
                    }
                )
    candidates.sort(key=lambda c: (-c["weight"], c["order"]))
    return candidates[: max(0, cap)]


def crawl_all(
    cfg: dict[str, Any],
    *,
    fallback_keywords: list[str],
    max_pages: int | None = None,
    delay: float | None = None,
    fetcher: Any = None,
    force: bool = False,
) -> tuple[list[search_mod.Hit], list[search_mod.Failure], list[dict[str, Any]]]:
    """跑所有启用的 crawl 源。单个源失败不影响其它源，失败进 failures。"""
    defaults = cfg.get("defaults") or {}
    pages = int(max_pages if max_pages is not None else defaults.get("max_pages", 1))
    pause = float(delay if delay is not None else defaults.get("crawl_delay_seconds", 1))
    hits: list[search_mod.Hit] = []
    failures: list[search_mod.Failure] = []
    used: list[dict[str, Any]] = []
    for source in enabled(cfg, include_crawl=True, force=force):
        if source.get("mode") != "crawl":
            continue
        keywords = [w for w in (source.get("keywords") or fallback_keywords) if w]
        try:
            got = crawl_mod.crawl_source(
                source,
                keywords=keywords,
                max_pages=pages,
                delay=pause,
                fetcher=fetcher,
            )
        except crawl_mod.CrawlError as exc:
            failures.append(
                search_mod.Failure(
                    query=f"crawl:{source.get('id')}", provider="crawl", reason=str(exc)
                )
            )
            continue
        hits.extend(got)
        used.append(
            {
                "id": source.get("id"),
                "name": source.get("name") or source.get("id"),
                "mode": "crawl",
                "hits": len(got),
            }
        )
    return hits, failures, used


def describe(
    cfg: dict[str, Any], *, used: list[dict[str, Any]] | None = None, force: bool = False
) -> dict[str, Any]:
    """给 ``run_meta.json`` 用的来源画像。"""
    sources = cfg.get("sources") or []
    by_mode: dict[str, int] = {}
    for source in sources:
        mode = str(source.get("mode") or "?")
        by_mode[mode] = by_mode.get(mode, 0) + 1
    return {
        "path": cfg.get("_path"),
        "configured": len(sources),
        "enabled": len(enabled(cfg, include_crawl=True, force=force)),
        "by_mode": by_mode,
        "used": used or [],
    }

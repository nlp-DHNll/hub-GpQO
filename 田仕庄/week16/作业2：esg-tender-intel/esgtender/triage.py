"""赛道归类与相关度打分（关键词规则，可解释、可复算）。

刻意不用 LLM：这一层必须确定性、零成本。灰区结果只标记 ``needs_review``，
不静默改变结论。

打分公式（配置在 ``scope.yaml`` 的 ``relevance.weights``）::

    title_score = 0.65 + 0.30 × min(1, 标题命中数 - 1)   # 1 个 = 0.65，≥2 个 = 0.95
    body_score  = 0.30 × min(1, 正文命中数 / 3)          # 正文最多贡献 0.30
    relevance   = min(1.0, title_score + body_score)

典型取值：标题 1 命中 = 0.65；再加 1 个正文命中 = 0.75；正文命中 3 个 = 0.95；
标题 2 命中且正文命中 3 个 = 1.00；只有正文命中 3 个 = 0.30（灰区）。

含义：核心/扩展赛道阈值 0.6/0.65，**必须标题命中**才能过线；只命中正文的
记录落在灰区（0.3 ~ 阈值），保留并标记待复核，避免静默丢召回。

边缘赛道是另一套逻辑：它已经要求 A 组与 B 组关键词**同时**命中，判定本身
就是强信号，因此分数直接给 0.75 起（标题再命中则 1.0），对应阈值 0.75。
"""

from __future__ import annotations

from typing import Any

DECISION_ACCEPT = "accept"
DECISION_GRAY = "gray"
DECISION_DROP = "drop"
DECISION_NOT_TENDER = "not_tender"  # 主题相关但不是采购公告（研报/债券上市/新闻）

DEFAULT_WEIGHTS = {
    "title_base": 0.65,
    "title_extra": 0.30,
    "body_bonus": 0.30,
    "body_saturate": 3,
}
EDGE_FLOOR = 0.75


def _count_hits(text: str, keywords: list[str]) -> list[str]:
    return [kw for kw in keywords if kw and kw in text]


def _score(
    title_hits: list[str], body_hits: list[str], weights: dict[str, float]
) -> float:
    """标题定档、正文微调。这样同一赛道内仍有 0.65 / 0.75 / 0.85 / 0.95 的区分度。"""
    n_title, n_body = len(title_hits), len(body_hits)
    if n_title == 0 and n_body == 0:
        return 0.0
    title_score = 0.0
    if n_title:
        title_score = float(weights.get("title_base", 0.65)) + float(
            weights.get("title_extra", 0.30)
        ) * min(1.0, n_title - 1)
    saturate = max(float(weights.get("body_saturate", 3)), 1e-9)
    body_score = float(weights.get("body_bonus", 0.30)) * min(1.0, n_body / saturate)
    return round(min(1.0, title_score + body_score), 2)


def _pick_sub(track_def: dict, text: str) -> str | None:
    """T5 这类带子类的赛道，按命中数挑子类；并列取配置顺序靠前的。"""
    subs: dict[str, list[str]] = track_def.get("sub") or {}
    if not subs:
        return None
    best_name: str | None = None
    best_hits = 0
    for name, keywords in subs.items():
        hits = len(_count_hits(text, keywords))
        if hits > best_hits:
            best_name, best_hits = name, hits
    return best_name


def _decide(relevance: float, threshold: float, gray_low: float) -> str:
    if relevance >= threshold:
        return DECISION_ACCEPT
    if relevance >= gray_low:
        return DECISION_GRAY
    return DECISION_DROP


def _candidate(
    group: str,
    track_id: str,
    name: str,
    sub: str | None,
    relevance: float,
    title_hits: list[str],
    body_hits: list[str],
) -> dict[str, Any]:
    first_hit = title_hits[0] if title_hits else body_hits[0]
    return {
        "group": group,
        "id": track_id,
        "name": name,
        "sub": sub,
        "relevance": relevance,
        "rule": f"kw:{first_hit}",
        "hits": {"title": title_hits, "body": body_hits},
    }


def _track_keywords(scope: dict) -> list[str]:
    """收集全部赛道关键词，供意图闸门判断「标题是否在讲这件事」。

    结果缓存在 scope 自己身上：``classify`` 是逐条记录调用的，2000 条记录 ×
    上百个关键词 = 几十万次字符串拼接，纯属白花时间。scope 在一次运行里只加载
    一次、之后不再改（改了 tracks 又复用同一个 dict 的场景不存在），所以缓存安全。
    """
    cached = scope.get("_track_keywords_cache")
    if isinstance(cached, list):
        return cached
    tracks = scope.get("tracks") or {}
    words: list[str] = []
    for group in ("core", "extended"):
        for track_def in (tracks.get(group) or {}).values():
            if isinstance(track_def, dict):
                words.extend(track_def.get("keywords") or [])
                for sub_keywords in (track_def.get("sub") or {}).values():
                    words.extend(sub_keywords or [])
            elif isinstance(track_def, list):
                words.extend(track_def)
    edge = tracks.get("edge") or {}
    words.extend(edge.get("require_any") or [])
    words.extend(edge.get("also_require_any") or [])
    unique = [word for word in words if word]
    scope["_track_keywords_cache"] = unique
    return unique


def is_tender_intent(title: str, body: str, scope: dict) -> tuple[bool, str]:
    """判断「这是不是一条采购/招标类公告」。

    赛道关键词只能判断主题相关，判断不了体裁。真实检索里「东吴证券：绿色债券
    周度数据跟踪｜研报」「上交所发布绿色债券清单」「行业快讯｜碳达峰试点方案」
    都能命中赛道关键词，但它们不是招标，市场调研人员拿去没用。

    规则（按优先级）：

    1. 标题命中 ``deny_any`` → 否。体裁词只有出现在标题才可信，正文里出现
       「政策」「解读」太常见，据此误杀太多。
    2. 标题命中 ``require_any`` → 是。
    3. 标题无采购词时，**只有标题本身在讲赛道主题**（含赛道关键词）才看正文兜底。

    第 3 条是真实数据逼出来的：某公司官网首页「登康口腔-为大众带来自信美丽
    笑容」的导航区里就有「招标采购」字样，不加这个约束会被当成采购公告。
    """
    intent = scope.get("intent") or {}
    deny = [kw for kw in (intent.get("deny_any") or []) if kw]
    require = [kw for kw in (intent.get("require_any") or []) if kw]

    title_text = title or ""
    for keyword in deny:
        if keyword in title_text:
            return False, f"deny:{keyword}"
    if not require:
        return True, "no-config"
    for keyword in require:
        if keyword in title_text:
            return True, f"require:{keyword}"

    # 正文兜底：标题必须先证明自己在讲这件事，否则站点导航里的「招标采购」会放行一切
    body_text = body or ""
    if not body_text or not any(kw in title_text for kw in _track_keywords(scope)):
        return False, "no-intent"
    for keyword in require:
        if keyword in body_text:
            return True, f"require-body:{keyword}"
    return False, "no-intent"


def classify(title: str, body: str, scope: dict) -> dict[str, Any]:
    """返回赛道、相关度、命中规则与处置决定。"""
    tracks = scope.get("tracks") or {}
    relevance_cfg = scope.get("relevance") or {}
    thresholds: dict[str, float] = relevance_cfg.get("threshold") or {}
    gray_low = float(relevance_cfg.get("gray_low", 0.3))
    weights = {**DEFAULT_WEIGHTS, **(relevance_cfg.get("weights") or {})}

    text_title = title or ""
    text_body = body or ""

    tender_ok, intent_reason = is_tender_intent(text_title, text_body, scope)
    if not tender_ok:
        return {
            "group": "none",
            "id": "none",
            "name": "非采购公告",
            "sub": None,
            "relevance": 0.0,
            "rule": f"intent:{intent_reason}",
            "hits": {"title": [], "body": []},
            "threshold": float(thresholds.get("core", 0.6)),
            "decision": DECISION_NOT_TENDER,
        }

    # 1) 核心赛道：取加权命中最高者；同分保留配置顺序靠前的
    best: dict[str, Any] | None = None
    for track_id, track_def in (tracks.get("core") or {}).items():
        keywords = list(track_def.get("keywords") or [])
        title_hits = _count_hits(text_title, keywords)
        body_hits = _count_hits(text_body, keywords)
        relevance = _score(title_hits, body_hits, weights)
        if relevance <= 0:
            continue
        candidate = _candidate(
            "core",
            track_id,
            track_def.get("name", track_id),
            _pick_sub(track_def, f"{text_title} {text_body}"),
            relevance,
            title_hits,
            body_hits,
        )
        if best is None or relevance > best["relevance"]:
            best = candidate

    # 2) 扩展赛道：仅在没有核心命中时判定，避免抢走核心记录
    if best is None:
        for name, keywords in (tracks.get("extended") or {}).items():
            title_hits = _count_hits(text_title, list(keywords))
            body_hits = _count_hits(text_body, list(keywords))
            relevance = _score(title_hits, body_hits, weights)
            if relevance <= 0:
                continue
            candidate = _candidate(
                "extended", name, name, None, relevance, title_hits, body_hits
            )
            if best is None or relevance > best["relevance"]:
                best = candidate

    # 3) 边缘：A 组与 B 组必须同时命中，否则不属于本 skill 的范围
    if best is None:
        edge = tracks.get("edge") or {}
        require_any = list(edge.get("require_any") or [])
        also_require = list(edge.get("also_require_any") or [])
        blob = f"{text_title} {text_body}"
        hit_a = _count_hits(blob, require_any)
        hit_b = _count_hits(blob, also_require)
        if hit_a and hit_b:
            title_hits = [k for k in hit_a + hit_b if k in text_title]
            relevance = 1.0 if title_hits else EDGE_FLOOR
            best = _candidate(
                "edge",
                "edge",
                "边缘-关联",
                None,
                relevance,
                title_hits,
                hit_a + hit_b,
            )
            best["rule"] = f"edge:{hit_a[0]}+{hit_b[0]}"

    if best is None:
        return {
            "group": "none",
            "id": "none",
            "name": "未命中",
            "sub": None,
            "relevance": 0.0,
            "rule": "no-hit",
            "hits": {"title": [], "body": []},
            "threshold": float(thresholds.get("core", 0.6)),
            "decision": DECISION_DROP,
        }

    threshold = float(thresholds.get(best["group"], thresholds.get("core", 0.6)))
    best["threshold"] = threshold
    best["decision"] = _decide(best["relevance"], threshold, gray_low)
    return best

# -*- coding: utf-8 -*-
"""Deterministic search, fetch, and extractive summary.

Summaries are sentences copied from the page. This module does not paraphrase
and does not call a language model.
"""

from __future__ import annotations

import base64
import html
import re
import ssl
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
TIER_A = (
    "gov.cn",
    "cninfo.com.cn",
    "sse.com.cn",
    "szse.cn",
    "bse.cn",
    "hkexnews.hk",
    "ifrs.org",
    "globalreporting.org",
    "msci.com",
    "csec.com",
    "shenhuachina.com",
    "shenhuachina.com.cn",
    "chnenergy.com.cn",
)
TIER_B = (
    "xinhuanet.com",
    "news.cn",
    "people.com.cn",
    "stcn.com",
    "cs.com.cn",
    "cnstock.com",
    "caixin.com",
    "yicai.com",
    "thepaper.cn",
    "jiemian.com",
)
ESG_TERMS = (
    "esg",
    "可持续发展",
    "碳",
    "气候",
    "环境",
    "绿色",
    "披露",
    "安全",
    "双碳",
)
MAJOR_TERMS = ("处罚", "事故", "指引", "评级", "强制", "披露", "碳排放", "中标", "绿电", "整改", "停产", "准则")
ACTION_TERMS = ("应当", "必须", "截止", "披露义务", "整改", "纳入", "前完成")
DATE_FULL = re.compile(r"(20\d{2})[年\-.](\d{1,2})[月\-.](\d{1,2})")
DATE_MONTH = re.compile(r"(20\d{2})年(\d{1,2})月")


def canon_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = urlencode(
        [(key, value) for key, value in parse_qsl(parts.query) if not key.lower().startswith("utm_")]
    )
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), host, path, query, ""))


def domain_of(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host.split(":")[0]


def tier_of(url: str) -> str:
    host = domain_of(url)
    if any(host == item or host.endswith("." + item) for item in TIER_A):
        return "A"
    if any(host == item or host.endswith("." + item) for item in TIER_B):
        return "B"
    return "C"


def unwrap_bing(url: str) -> str:
    parts = urlsplit(url)
    if "bing.com" not in parts.netloc:
        return url
    token = dict(parse_qsl(parts.query)).get("u", "")
    if token.startswith("a1"):
        payload = token[2:]
        payload += "=" * (-len(payload) % 4)
        try:
            decoded = base64.b64decode(payload).decode("utf-8", "ignore")
        except (ValueError, UnicodeError):
            return url
        if decoded.startswith("http"):
            return decoded
    return url


def strip_tags(value: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return html.unescape(text)


def html_to_text(value: str) -> str:
    text = strip_tags(value)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def sentences_of(text: str) -> list[str]:
    found = []
    for part in re.split(r"[。！？\n]", text):
        sentence = re.sub(r"\s+", " ", part).strip(" \t-—|")
        if 18 <= len(sentence) <= 180:
            found.append(sentence)
    return found


def pdf_to_text(raw: bytes) -> str:
    try:
        import io

        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(io.BytesIO(raw))
    except Exception:
        return ""
    pages = []
    for page in reader.pages[:6]:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(pages)


def _fetch(url: str, timeout: float, limit: int) -> tuple[bytes, str]:
    request = Request(
        url,
        headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            return response.read(limit), content_type
    except URLError:
        context = ssl._create_unverified_context()
        with urlopen(request, timeout=timeout, context=context) as response:
            content_type = response.headers.get("Content-Type", "")
            return response.read(limit), content_type + "; tls-unverified"


def decode_body(raw: bytes, content_type: str) -> str:
    match = re.search(r"charset=[\"']?([\w-]+)", content_type or "", re.I)
    if not match:
        match = re.search(br"charset=[\"']?([\w-]+)", raw[:5000], re.I)
        encoding = match.group(1).decode() if match else ""
    else:
        encoding = match.group(1)
    if encoding:
        try:
            return raw.decode(encoding, "replace")
        except LookupError:
            pass
    text = raw.decode("utf-8", "replace")
    if text.count("\ufffd") > 30:
        return raw.decode("gb18030", "replace")
    return text


def content_terms(query: str) -> list[str]:
    raw = re.sub(r"\bOR\b", " ", query, flags=re.I)
    terms = []
    for piece in re.split(r"\s+", raw.strip()):
        if len(piece) < 2 or re.fullmatch(r"20\d{2}(?:年\d{0,2}月?)?", piece):
            continue
        terms.append(piece)
    return terms


def on_topic(title: str, snippet: str, terms: list[str]) -> bool:
    if not terms:
        return True
    blob = f"{title} {snippet}".lower()
    return any(term.lower() in blob for term in terms)


def bing_search(query: str, count: int, timeout: float) -> list[dict]:
    url = "https://www.bing.com/search?format=rss&q=" + quote(query)
    raw, _ = _fetch(url, timeout, 400_000)
    root = ET.fromstring(raw)
    hits = []
    for node in root.findall(".//item"):
        title = html_to_text("".join(node.findtext("title") or ""))
        link = unwrap_bing((node.findtext("link") or "").strip())
        snippet = html_to_text("".join(node.findtext("description") or ""))
        if not title or not link.startswith("http"):
            continue
        if "bing.com" in domain_of(link):
            continue
        hits.append({"query": query, "title": title, "url": link, "snippet": snippet[:300]})
        if len(hits) >= count:
            break
    return hits


def classify_dates(text: str, since: datetime, until: datetime) -> str:
    full = []
    for year, month, day in DATE_FULL.findall(text):
        try:
            full.append(datetime(int(year), int(month), int(day)))
        except ValueError:
            continue
    if any(since <= item <= until for item in full):
        return "in"
    months = []
    for year, month in DATE_MONTH.findall(text):
        try:
            months.append(datetime(int(year), int(month), 1))
        except ValueError:
            continue
    if any(since.replace(day=1) <= item <= until for item in months):
        return "in"
    if full or months:
        return "out"
    return "unknown"


def _has_any(text: str, words: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(word.lower() in lowered for word in words)


def score_item(item: dict, client_terms: tuple[str, ...]) -> dict:
    blob = " ".join((item.get("title") or "", item.get("excerpt") or "", item.get("snippet") or ""))
    authority = 2 if item.get("opened") and item.get("tier") == "A" else 1 if item.get("opened") and item.get("tier") == "B" else 0
    if any(term in blob for term in client_terms):
        relevance = 2
    elif _has_any(blob, ESG_TERMS):
        relevance = 1
    else:
        relevance = 0
    freshness = {"in": 2, "unknown": 1, "out": 0}[item.get("date_status", "unknown")]
    if _has_any(blob, MAJOR_TERMS):
        materiality = 2
    elif re.search(r"\d", blob):
        materiality = 1
    else:
        materiality = 0
    if _has_any(blob, ACTION_TERMS):
        actionable = 2
    elif any(term in blob for term in client_terms):
        actionable = 1
    else:
        actionable = 0
    total = authority + relevance + freshness + materiality + actionable
    return {
        "权威": authority,
        "相关": relevance,
        "新颖": freshness,
        "重大": materiality,
        "可行动": actionable,
        "总分": total,
    }


def extract_excerpt(text: str, client_terms: tuple[str, ...], limit: int = 3) -> str:
    ranked = []
    for sentence in sentences_of(text):
        score = 0
        lowered = sentence.lower()
        if any(term in sentence for term in client_terms):
            score += 3
        score += sum(1 for term in ESG_TERMS if term.lower() in lowered)
        if DATE_FULL.search(sentence) or DATE_MONTH.search(sentence):
            score += 2
        if re.search(r"\d", sentence):
            score += 1
        if score > 0:
            ranked.append((score, sentence))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]))
    chosen = []
    for _, sentence in ranked:
        if sentence not in chosen:
            chosen.append(sentence)
        if len(chosen) >= limit:
            break
    return "。".join(chosen)


def collect(
    queries: list[str],
    since: datetime,
    until: datetime,
    client_terms: tuple[str, ...],
    per_query: int = 5,
    max_pages: int = 8,
    timeout: float = 12,
    deadline_sec: float = 90,
    seed_urls: list[str] | None = None,
) -> dict:
    started = time.perf_counter()
    deadline = time.time() + deadline_sec
    hits = []
    errors = []
    if seed_urls:
        hits = [{"query": "given-url", "title": "", "url": url, "snippet": ""} for url in seed_urls]
    else:
        for query in queries:
            if time.time() > deadline:
                errors.append(f"超过 {int(deadline_sec)} 秒，剩余查询未执行")
                break
            try:
                found = bing_search(query, per_query, timeout)
            except (HTTPError, URLError, ET.ParseError, TimeoutError, OSError) as exc:
                errors.append(f"查询失败 {query}: {exc.__class__.__name__}")
                continue
            terms = content_terms(query)
            matched = [hit for hit in found if on_topic(hit["title"], hit["snippet"], terms)]
            if found and not matched:
                errors.append(f"接口返回了 {len(found)} 条，但没有一条标题或摘要含查询词：{query}")
            hits.extend(matched)
    deduped = []
    seen = set()
    for hit in hits:
        key = canon_url(hit["url"])
        if not key or key in seen:
            continue
        seen.add(key)
        hit["url"] = hit["url"].split("#")[0]
        hit["domain"] = domain_of(hit["url"])
        hit["tier"] = tier_of(hit["url"])
        deduped.append(hit)
    deduped.sort(key=lambda hit: {"A": 0, "B": 1, "C": 2}[hit["tier"]])
    items = []
    opened = 0
    for hit in deduped:
        item = dict(hit)
        item["opened"] = False
        item["excerpt"] = ""
        item["date_status"] = classify_dates(hit["snippet"] + hit["title"], since, until)
        if opened < max_pages and time.time() < deadline:
            try:
                raw, content_type = _fetch(hit["url"], timeout, 1_200_000)
                if "pdf" in content_type.lower() or raw[:5] == b"%PDF-" or hit["url"].lower().endswith(".pdf"):
                    text = html_to_text(pdf_to_text(raw))
                    if not text:
                        errors.append(f"PDF未抽出文字 {hit['url']}")
                    else:
                        item["opened"] = True
                        item["excerpt"] = extract_excerpt(text, client_terms)
                        item["date_status"] = classify_dates(text[:8000], since, until)
                        item["lead_date_status"] = classify_dates(text[:600], since, until)
                        item["excerpt_in_page"] = bool(item["excerpt"]) and all(
                            part in text for part in item["excerpt"].split("。") if part
                        )
                        opened += 1
                else:
                    text = html_to_text(decode_body(raw, content_type))
                    item["opened"] = True
                    item["excerpt"] = extract_excerpt(text, client_terms)
                    item["date_status"] = classify_dates(text[:8000], since, until)
                    item["lead_date_status"] = classify_dates(text[:600], since, until)
                    item["excerpt_in_page"] = bool(item["excerpt"]) and all(
                        part in text for part in item["excerpt"].split("。") if part
                    )
                    opened += 1
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                errors.append(f"打开失败 {hit['url']}: {exc.__class__.__name__}")
        if not item["excerpt"]:
            item["excerpt_in_page"] = False
        item["scores"] = score_item(item, client_terms)
        lead = item.get("lead_date_status", item.get("date_status", "unknown"))
        item["kept"] = bool(
            item["opened"]
            and item["excerpt"]
            and item["scores"]["总分"] >= 5
            and (lead == "in" or (lead == "unknown" and item.get("date_status") == "in"))
        )
        items.append(item)
    return {
        "elapsed_sec": round(time.perf_counter() - started, 2),
        "queries": queries,
        "hit_count": len(hits),
        "unique_count": len(deduped),
        "opened_count": opened,
        "errors": errors,
        "items": items,
    }


def self_test() -> int:
    page = "<p>中国神华在2026年10月15日披露ESG报告，碳排放强度下降。</p><script>skip</script>"
    text = html_to_text(page)
    excerpt = extract_excerpt(text, ("中国神华",))
    if "中国神华" not in excerpt or "skip" in excerpt:
        print("excerpt failed", excerpt)
        return 1
    if classify_dates("发布时间2026年10月", datetime(2026, 10, 1), datetime(2026, 10, 31)) != "in":
        print("month classify failed")
        return 1
    if classify_dates("2026-09-02", datetime(2026, 10, 1), datetime(2026, 10, 31)) != "out":
        print("full date classify failed")
        return 1
    if tier_of("https://www.cninfo.com.cn/a") != "A":
        print("tier failed")
        return 1
    item = {
        "title": "中国神华ESG",
        "excerpt": "公司必须在截止日前完成碳排放披露",
        "snippet": "",
        "opened": True,
        "tier": "A",
        "date_status": "in",
    }
    scores = score_item(item, ("中国神华",))
    if scores["总分"] < 5:
        print("score failed", scores)
        return 1
    print("OK")
    return 0

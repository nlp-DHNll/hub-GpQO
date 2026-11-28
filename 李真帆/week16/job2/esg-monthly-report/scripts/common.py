"""公共部分：读取 .env、带磁盘缓存的 HTTP、标题正文与日期抽取、大模型结构化输出。"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
CACHE_DIR = Path(os.environ.get("ESG_CACHE_DIR", "cache"))
ENV_KEYS = ("DEEPSEEK_API_KEY", "BOCHA_API_KEY", "TAVILY_API_KEY", "SERPER_API_KEY")
DATE_RE = re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})")
META_DATE_KEYS = (
    "article:published_time", "og:release_date", "og:article:published_time", "publishdate", "pubdate",
    "publish_date", "publication_date", "datepublication", "weibo: article:create_at", "apub:time",
    "column:date",
)
LABEL_RE = re.compile(
    r"(?:发布时间|发布日期|发表时间|刊发日期|成文日期|成文时间|更新时间)\s*[：:]\s*(20\d{2}[-/年.]\d{1,2}[-/月.]\d{1,2})"
)
URL_DATE_PATTERNS = (
    r"t(20\d{2})(\d{2})(\d{2})_", r"_(20\d{2})(\d{2})(\d{2})_", r"/(20\d{2})(\d{2})(\d{2})[/.]",
    r"/(20\d{2})[-_.](\d{2})[-_.](\d{2})",
)
_DROP_TAGS = ("script", "style", "noscript", "template", "svg", "iframe", "nav", "header", "footer",
              "form", "button")
_DROP_PARAMS = ("utm", "spm", "from", "share", "source", "src", "refer", "pvid", "scm", "scene",
                "isappinstalled", "wfr", "_h")
T = TypeVar("T", bound=BaseModel)
_local = threading.local()
_PARSER = "lxml" if importlib.util.find_spec("lxml") else "html.parser"
_json_mode = True
_client = None
_client_lock = threading.Lock()


def init() -> None:
    """以 UTF-8 输出，并把 .env 里的配置读进环境变量（已存在的不覆盖）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    for f in env_files():
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
        return


def env_files() -> list[Path]:
    """从当前目录和脚本目录各自向上找 .env，只认含有所需配置键的那一个。"""
    found, seen = [], set()
    for start in (Path.cwd(), Path(__file__).resolve().parent):
        for folder in (start, *start.parents):
            f = folder / ".env"
            if f in seen or not f.is_file():
                continue
            seen.add(f)
            text = f.read_text(encoding="utf-8", errors="replace")
            if any(key + "=" in text for key in ENV_KEYS):
                found.append(f)
    return found


def session() -> requests.Session:
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update({
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        _local.session = s
    return s


def http_get(url: str, referer: str | None = None, timeout: int = 20, max_bytes: int = 4_000_000,
             cache: bool = True) -> dict[str, Any]:
    """GET 一个地址，结果写入 cache/http/。同一地址只请求一次；失败的记录隔天重试。"""
    path = CACHE_DIR / "http" / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".json")
    if cache and path.is_file():
        rec = json.loads(path.read_text(encoding="utf-8"))
        age = datetime.now() - datetime.fromisoformat(rec["fetched_at"])
        if rec.get("ok") or age < timedelta(days=1):
            return rec
    rec: dict[str, Any] = {"url": url, "ok": False, "fetched_at": datetime.now().isoformat(timespec="seconds")}
    try:
        with session().get(url, headers={"Referer": referer} if referer else {}, timeout=timeout,
                           stream=True) as r:
            raw = b""
            for chunk in r.iter_content(65536):
                raw += chunk
                if len(raw) >= max_bytes:
                    break
            rec["status"] = r.status_code
            rec["final_url"] = r.url
            rec["html"] = decode_bytes(raw, r.encoding)
            rec["ok"] = r.status_code == 200
    except requests.RequestException as e:
        rec["error"] = type(e).__name__
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    return rec


def decode_bytes(raw: bytes, hint: str | None) -> str:
    meta = re.search(rb'charset=["\']?([A-Za-z0-9_-]+)', raw[:5000], re.I)
    for enc in ("utf-8", hint, meta.group(1).decode("ascii") if meta else None, "gb18030"):
        if not enc:
            continue
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, _PARSER)


def page_title(html: str) -> str:
    soup = soup_of(html)
    for m in soup.find_all("meta"):
        key = (m.get("property") or m.get("name") or "").lower()
        if key in ("og:title", "title") and m.get("content"):
            return m["content"].strip()
    return re.sub(r"\s+", " ", soup.title.get_text(strip=True)) if soup.title else ""


def extract_main(html: str, max_chars: int = 6000) -> tuple[str, dict]:
    """抽正文并给出段落统计。优先取较长的段落，段落太少时退回整页可见文本。"""
    soup = soup_of(html)
    links = [a.get_text(strip=True) for a in soup.find_all("a")]
    for tag in soup(_DROP_TAGS):
        tag.decompose()
    paras = [re.sub(r"\s+", " ", p.get_text(" ", strip=True)) for p in soup.find_all(["p", "h1", "h2", "h3"])]
    paras = [p for p in paras if len(p) >= 12]
    mode = "paragraph"
    if sum(len(p) for p in paras) < 300:
        paras = [ln.strip() for ln in soup.get_text("\n").splitlines() if len(ln.strip()) >= 15]
        mode = "lines"
    total = len(soup.get_text())
    stats = {"para_count": len(paras), "avg_para_len": sum(map(len, paras)) // len(paras) if paras else 0,
             "text_mode": mode, "link_count": sum(1 for t in links if len(t) >= 8),
             "link_ratio": round(sum(map(len, links)) / total, 2) if total else 0.0}
    return "\n".join(paras)[:max_chars], stats


def main_text(html: str, max_chars: int = 6000) -> str:
    return extract_main(html, max_chars)[0]


def _iso(y: Any, m: Any, d: Any) -> str:
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except (TypeError, ValueError):
        return ""


def find_date_in(text: str | None) -> str:
    m = DATE_RE.search(text or "")
    return _iso(*m.groups()) if m else ""


def extract_dates(html: str, url: str) -> dict[str, str]:
    """返回 {日期依据: YYYY-MM-DD}，依据按可信度排列：meta、label、text、url。"""
    out: dict[str, str] = {}
    for m in soup_of(html).find_all("meta"):
        key = (m.get("property") or m.get("name") or "").lower()
        if key in META_DATE_KEYS:
            d = find_date_in(m.get("content"))
            if d:
                out.setdefault("meta", d)
    if "meta" not in out:
        m = re.search(r'"datePublished"\s*:\s*"[^"]*?(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})', html)
        if m:
            out["meta"] = find_date_in(m.group(1))
    if not out:
        m = LABEL_RE.search(html)
        if m:
            out["label"] = find_date_in(m.group(1))
    if not out:
        d = find_date_in(main_text(html, 800))
        if d:
            out["text"] = d
    if not out:
        for pattern in URL_DATE_PATTERNS:
            m = re.search(pattern, url)
            if m:
                out["url"] = _iso(*m.groups())
                break
    return {k: v for k, v in out.items() if v}


def normalize_date(value: Any, today: date | None = None) -> str:
    """把搜索结果里的各种日期写法归一成 YYYY-MM-DD，认不出返回空串。"""
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    d = find_date_in(s)
    if d:
        return d
    if re.fullmatch(r"\d{13}|\d{10}", s):
        ts = int(s) / (1000 if len(s) == 13 else 1)
        return datetime.fromtimestamp(ts).date().isoformat()
    today = today or date.today()
    m = re.search(r"(\d+)\s*(天|日|小时|周)(?:以?[前内])?", s)
    if m and ("前" in s or "内" in s):
        n, unit = int(m.group(1)), m.group(2)
        days = {"天": n, "日": n, "小时": n // 24, "周": n * 7}[unit]
        return (today - timedelta(days=days)).isoformat()
    if "昨天" in s:
        return (today - timedelta(days=1)).isoformat()
    if "今天" in s or "刚刚" in s or "小时前" in s:
        return today.isoformat()
    m = re.fullmatch(r"(\d{1,2})月(\d{1,2})日?", s)
    if m:
        try:
            d = date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return ""
        return (d if d <= today else d.replace(year=today.year - 1)).isoformat()
    return ""


def to_date(value: str) -> date | None:
    d = normalize_date(value)
    return date.fromisoformat(d) if d else None


def host(url: str) -> str:
    h = urlparse(url or "").netloc.lower()
    return h[2:] if h.startswith("m.") else (h[4:] if h.startswith("www.") else h)


def canonical_url(url: str) -> str:
    """去掉协议、移动端前缀和跟踪参数，用来判断两个链接是否指向同一页面。"""
    p = urlparse((url or "").strip())
    if not p.netloc:
        return ""
    params = sorted(kv for kv in p.query.split("&")
                    if kv and not kv.lower().startswith(_DROP_PARAMS))
    return f"{host(url)}{p.path.rstrip('/')}" + (f"?{'&'.join(params)}" if params else "")


def norm_title(title: str | None) -> str:
    return re.sub(r"[\W_]+", "", (title or "").lower())


def similar(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if min(len(a), len(b)) >= 8 and (a in b or b in a):
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def read_jsonl(path: str | Path) -> list[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: str | Path, rows: Iterable[dict]) -> int:
    rows = list(rows)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return len(rows)


def load_yaml(path: str | Path) -> dict:
    import yaml
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def guard(name: str, fn: Callable[[], int]) -> int:
    """脚本入口：把异常压成一行错误信息。设置 ESG_DEBUG=1 时保留完整堆栈。"""
    init()
    try:
        return fn() or 0
    except SystemExit:
        raise
    except Exception as e:
        if os.environ.get("ESG_DEBUG"):
            raise
        print(f"[{name}] 失败：{type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        return 1


def pmap(items: list, fn: Callable, workers: int = 4) -> list:
    if workers <= 1:
        return [fn(i) for i in items]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))


def llm_configured() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY"))


def parse_json_object(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    try:
        return json.loads(text[text.find("{"): text.rfind("}") + 1])
    except (ValueError, TypeError) as e:
        raise ValueError("不是合法的 JSON") from e


def llm_json(system: str, user: str, schema: type[T], retries: int = 2) -> tuple[T, dict[str, int]]:
    """调用 OpenAI 兼容接口，要求输出 JSON 并按 schema 校验。重试仍失败时抛 RuntimeError。"""
    global _client, _json_mode
    with _client_lock:
        if _client is None:
            from openai import OpenAI
            _client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"],
                             base_url=os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
                             max_retries=2, timeout=120)
    model = os.environ.get("CHAT_MODEL", "deepseek-chat")
    last = "unknown"
    for attempt in range(retries + 1):
        try:
            extra = {"response_format": {"type": "json_object"}} if _json_mode else {}
            resp = _client.chat.completions.create(
                model=model, temperature=0.1, messages=[
                    {"role": "system", "content": system}, {"role": "user", "content": user}],
                **extra)
            obj = schema.model_validate(parse_json_object(resp.choices[0].message.content or ""))
            u = resp.usage.model_dump() if resp.usage else {}
            return obj, {"prompt_tokens": u.get("prompt_tokens", 0), "completion_tokens": u.get("completion_tokens", 0)}
        except Exception as e:  # 接口报错、JSON 不合法、字段不符都走这里
            last = f"{type(e).__name__}: {str(e)[:160]}"
            if _json_mode and "response_format" in last:
                _json_mode = False
                continue
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"大模型输出解析失败（{last}）")

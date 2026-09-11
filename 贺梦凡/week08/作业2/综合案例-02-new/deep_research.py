#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度研究助手 —— 输入一个研究主题，自动完成：规划 → 多轮检索 → 阅读抽取 → 补检判断 → 综合报告。

用法:
    python deep_research.py "研究主题"            # 打印研究计划后按回车确认
    python deep_research.py "研究主题" --yes      # 跳过确认，全自动执行
    可选参数: --llm-key / --search-key / --freshness / --no-fetch

密钥: 优先环境变量 DEEPSEEK_API_KEY / BOCHA_API_KEY，其次命令行参数，最后脚本内默认值。
依赖: 仅 Python 3.10+ 标准库。
"""

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# ---------- 基础配置 ----------
if hasattr(sys.stdout, "reconfigure"):  # Windows 控制台统一 UTF-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BOCHA_API = "https://api.bocha.cn/v1/web-search"
LLM_API = "https://api.deepseek.com/chat/completions"
LLM_MODEL = "deepseek-chat"

DEFAULT_BOCHA_KEY = "sk-3d2293ad83aa4823a7c7ce8dd5ff8c72"  # README.md 提供
DEFAULT_LLM_KEY = "sk-69381217d01846b88d08594246eb12a0"  # 可被环境变量/参数覆盖

TIMEOUT = 15          # 单次 HTTP 超时（秒）
MAX_ROUNDS = 3        # 检索轮数上限
MAX_SEARCHES = 12     # 搜索次数总预算
MAX_PAGES = 15        # 抓取网页正文总数上限
PAGE_CHARS = 3000     # 每页正文截断字符数
SUMMARY_CHARS = 700   # 每条摘要进入抽取的截断长度
TOP_PAGES = 3         # 每个子问题每轮抓正文的条数
REPLAN_LIMIT = 3      # 计划重排次数上限

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

BOCHA_KEY = DEFAULT_BOCHA_KEY
LLM_KEY = DEFAULT_LLM_KEY

SOURCES = {}  # url -> {"n": 编号, "title": 标题, "site": 站点}


# ---------- 通用 HTTP / LLM ----------
def http_post_json(url, payload, headers, retries=1):
    """POST JSON 请求，失败自动重试 1 次（间隔 2s）。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = resp.read().decode("utf-8", "replace")
            return json.loads(body)
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(2)
    raise RuntimeError("请求失败 {}：{}".format(url, last_err))


def llm(messages, max_tokens=2000, temperature=0.3):
    """调用 DeepSeek Chat Completions，返回助手文本。"""
    payload = {"model": LLM_MODEL, "messages": messages,
               "max_tokens": max_tokens, "temperature": temperature}
    resp = http_post_json(LLM_API, payload, {
        "Authorization": "Bearer " + LLM_KEY,
        "Content-Type": "application/json"})
    choices = resp.get("choices")
    if not choices:
        raise RuntimeError("LLM 响应异常：" + json.dumps(resp, ensure_ascii=False)[:300])
    return (choices[0].get("message") or {}).get("content") or ""


def extract_json(text, default=None):
    """容错解析 LLM 输出的 JSON（容忍代码围栏与前后缀噪音）。"""
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```\s*$", "", t)
    try:
        return json.loads(t)
    except Exception:
        pass
    m = re.search(r"(\{.*\}|\[.*\])", t, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return default


# ---------- 搜索与网页正文 ----------
def bocha_search(query, freshness="oneYear", count=10):
    """调用 Bocha web-search，返回标准化结果列表。"""
    payload = {"query": query, "summary": True, "count": count, "freshness": freshness}
    resp = http_post_json(BOCHA_API, payload, {
        "Authorization": "Bearer " + BOCHA_KEY,
        "Content-Type": "application/json"})
    if resp.get("code") != 200:
        raise RuntimeError("搜索失败（{}）：{}".format(query, resp.get("msg")))
    pages = ((resp.get("data") or {}).get("webPages") or {}).get("value") or []
    out = []
    for p in pages:
        url = (p.get("url") or "").strip()
        if not url:
            continue
        out.append({
            "title": (p.get("name") or "").strip(),
            "url": url,
            "display": (p.get("displayUrl") or "").strip(),
            "snippet": (p.get("snippet") or "").strip(),
            "summary": (p.get("summary") or "").strip(),
            "site": (p.get("siteName") or "").strip(),
            "date": (p.get("datePublished") or "").strip(),
        })
    return out


def strip_html(text):
    """去脚本/样式/标签，转实体，压空白，得到纯文本。"""
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_page_text(url):
    """抓取网页正文；非 HTML（如 PDF）或失败返回 None。"""
    if url.lower().split("?")[0].endswith(
            (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip")):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
            ctype = resp.headers.get("Content-Type", "")
    except Exception:
        return None
    if ctype and "html" not in ctype.lower() and not ctype.lower().startswith("text"):
        return None
    text = None
    for enc in ("utf-8", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except Exception:
            continue
    if text is None:
        text = raw.decode("utf-8", "replace")
    return strip_html(text)[:PAGE_CHARS]


def register_source(url, title="", site=""):
    """把 URL 登记进全局来源表，分配引用编号。"""
    if url not in SOURCES:
        SOURCES[url] = {"n": len(SOURCES) + 1, "title": title or url[:80], "site": site}


def match_source(claimed, known_urls):
    """把 LLM 抄写的来源字符串容错映射到已知 URL（容忍句号/斜杠/截断）。"""
    s = (claimed or "").strip().rstrip("。，；、,;.…/")
    if s in known_urls:
        return s
    for u in known_urls:
        if u.startswith(s) or s.startswith(u):
            return u
    return None


# ---------- 规划 ----------
PLAN_PROMPT = (
    "你是一名资深研究助理。请把研究主题拆解为 3~5 个相互独立、覆盖全面的子问题，"
    "并为每个子问题给出 1~2 个适合网络搜索的中文检索词。\n"
    "只输出 JSON，不要输出任何其他内容，格式：\n"
    '{"sub_questions":[{"question":"子问题1","queries":["检索词A","检索词B"]}]}'
)


def plan(topic, feedback=""):
    """LLM 把主题拆解为子问题 + 检索词。"""
    user = "研究主题：" + topic
    if feedback:
        user += "\n补充要求：" + feedback
    user += "\n" + PLAN_PROMPT
    content = llm([{"role": "system", "content": "你只输出合法 JSON。"},
                   {"role": "user", "content": user}], max_tokens=1200, temperature=0.2)
    data = extract_json(content) or {}
    items = data.get("sub_questions") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise RuntimeError("规划失败：LLM 未返回合法计划 JSON")
    sqs = []
    for it in items:
        q = (it.get("question") if isinstance(it, dict) else None) or ""
        qs = it.get("queries") if isinstance(it, dict) else None
        if isinstance(qs, str):
            qs = [qs]
        qs = [x for x in (qs or []) if isinstance(x, str) and x.strip()]
        if q and qs:
            sqs.append({"question": q, "queries": qs[:2]})
    if not sqs:
        raise RuntimeError("规划失败：计划为空")
    return sqs[:5]


# ---------- 阅读抽取 ----------
def extract_facts(question, materials, prev_facts):
    """从新材料中抽取带来源的事实，并列出仍未回答的问题。"""
    lines = ["子问题：" + question, "", "已确认事实（只补充新信息，勿重复）："]
    if prev_facts:
        for f in prev_facts[-12:]:
            lines.append("- " + f["claim"][:200] + "（来源：" + "、".join(f["sources"]) + "）")
    else:
        lines.append("（无）")
    lines.append("")
    lines.append("本轮新材料：")
    for i, m in enumerate(materials):
        lines.append("[材料{}] {} · {} · {}".format(i, m["kind"], m["title"][:60], m["url"]))
        lines.append(m["text"])
    lines.append("")
    lines.append(
        "请从材料中抽取与子问题直接相关、有明确出处的事实。要求：\n"
        "1. 每条事实的 sources 必须填材料里的来源 URL，凭空推断的内容不要写；\n"
        "2. 材料回答不了的部分逐条写入 unanswered；\n"
        "只输出 JSON："
        '{"facts":[{"claim":"事实","sources":["URL"]}],"unanswered":["问题"]}'
    )
    content = llm([{"role": "system", "content": "你只输出合法 JSON。"},
                   {"role": "user", "content": "\n".join(lines)}], max_tokens=2000, temperature=0.2)
    data = extract_json(content)
    if data is None:
        print("[抽取] 警告：LLM 输出无法解析，本轮抽取为空")
        data = {}
    known = {m["url"] for m in materials}
    facts = []
    for f in data.get("facts") or []:
        claim = (f.get("claim") or "").strip()
        srcs = []
        for s in f.get("sources") or []:
            u = match_source(s, known)
            if u and u not in srcs:
                srcs.append(u)
        if claim and srcs:
            facts.append({"claim": claim, "sources": srcs})
    un = [u for u in (data.get("unanswered") or []) if u and isinstance(u, str)]
    return {"facts": facts, "unanswered": un}


# ---------- 补检判断 ----------
def judge_gap(unanswered, round_no, searches_done):
    """LLM 判断是否需要补充检索，返回 [(检索词, 子问题序号)]。

    用字母编号（A/B/C…）而非数字序号让 LLM 指明子问题归属，
    数字索引对 LLM 来说极易数错。
    """
    ids = {i: chr(65 + i) for i in sorted(unanswered)}  # 0->A, 1->B, ...
    rev = {v: k for k, v in ids.items()}
    lines = ["尚有未回答的问题（每个子问题有唯一字母编号，输出时务必使用该编号）："]
    for i, qs in sorted(unanswered.items()):
        for q in qs[:3]:
            lines.append("- 子问题{}：{}".format(ids[i], q))
    lines.append("")
    lines.append("已用轮次 {}/{}，已用搜索次数 {}/{}。".format(
        round_no, MAX_ROUNDS, searches_done, MAX_SEARCHES))
    lines.append(
        "若确有必要补检，输出新的中文检索词，sub_question_id 必须填上面列表里对应的字母编号"
        "（如 A、B）；若现有材料已足够、或问题属于纯推断（无需检索），输出空数组。\n"
        '只输出 JSON：{"queries":[{"query":"检索词","sub_question_id":"A"}]}'
    )
    content = llm([{"role": "system", "content": "你只输出合法 JSON。"},
                   {"role": "user", "content": "\n".join(lines)}], max_tokens=600, temperature=0.2)
    data = extract_json(content)
    if data is None:
        print("[判断] 警告：LLM 输出无法解析，视为无需补检")
        return []
    out = []
    for q in data.get("queries") or []:
        query = (q.get("query") or "").strip() if isinstance(q, dict) else ""
        qid = q.get("sub_question_id") if isinstance(q, dict) else None
        qid = str(qid or "").strip().upper()
        idx = rev.get(qid, -1)
        if query:
            out.append((query, idx))
    return out


# ---------- 写作 ----------
def write_section(question, facts, source_map):
    """为一个子问题撰写报告小节（带 [编号] 引用）。"""
    if not facts:
        return "（本节未检索到足够有出处的结论支撑，请见“遗留问题”。）"
    lines = ["子问题：" + question, "引用编号映射（编号: URL）："]
    for url, n in source_map.items():
        lines.append("  [{}] {}".format(n, url))
    lines.append("事实清单：")
    for f in facts[:15]:
        srcs = "、".join("[" + str(source_map[u]) + "]" for u in f["sources"] if u in source_map)
        lines.append("- " + f["claim"][:400] + ("（来源 " + srcs + "）" if srcs else ""))
    lines.append("")
    lines.append(
        "请为上述子问题撰写研究报告小节（Markdown，不含一级标题，300~600 字）。"
        "只写有来源支撑的内容，在相关句子后以 [编号] 标注引用。只输出正文，不要输出其他说明。"
    )
    content = llm([{"role": "system", "content": "你是严谨的研究报告撰稿人。"},
                   {"role": "user", "content": "\n".join(lines)}], max_tokens=2500, temperature=0.4)
    return re.sub(r"^#{1,6}\s*", "", content.strip(), count=1)


def assemble(topic, sections, source_map):
    """汇总摘要、关键结论、遗留问题与置信度说明。"""
    lines = ["研究主题：" + topic, "各小节要点："]
    for i, sec in enumerate(sections):
        lines.append("第{}节 {}：{}".format(i + 1, sec["question"], sec["body"][:600]))
    lines.append("引用编号映射（编号: URL）：")
    for url, n in source_map.items():
        lines.append("  [{}] {}".format(n, url))
    lines.append("")
    lines.append(
        "请输出研究报告的收尾部分，只输出 JSON：\n"
        '{"abstract":"200 字以内的摘要",'
        '"key_findings":[{"finding":"关键结论","refs":[编号]}],'
        '"open_questions":["遗留问题"],'
        '"confidence_notes":"对整体可靠性的两句话说明"}\n'
        "key_findings 中每条结论的 refs 必须填上面映射表里的引用编号（可空数组表示无来源）。"
    )
    content = llm([{"role": "system", "content": "你只输出合法 JSON。"},
                   {"role": "user", "content": "\n".join(lines)}], max_tokens=2500, temperature=0.3)
    data = extract_json(content) or {}
    known = set(source_map)
    rev = {n: u for u, n in source_map.items()}
    kfs = []
    for f in data.get("key_findings") or []:
        finding = (f.get("finding") or "").strip()
        srcs = []
        for s in f.get("refs") or f.get("sources") or []:
            try:
                u = rev.get(int(str(s).strip()))
            except (TypeError, ValueError):
                u = match_source(s, known)
            if u and u not in srcs:
                srcs.append(u)
        if finding:
            kfs.append({"finding": finding, "sources": srcs})
    oq = [q for q in (data.get("open_questions") or []) if q and isinstance(q, str)]
    return {
        "abstract": (data.get("abstract") or "").strip(),
        "key_findings": kfs,
        "open_questions": oq,
        "confidence_notes": (data.get("confidence_notes") or "").strip(),
    }


# ---------- 报告组装与落盘 ----------
def confidence_tag(sources):
    if len(sources) >= 2:
        return "高", "≥2 个独立来源且一致"
    if len(sources) == 1:
        return "中", "单一来源"
    return "低", "无来源支撑"


def build_report(topic, sqs, sections, summ, log_entries, pages_read, searches_done, freshness):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    L = ["# 研究报告：" + topic, "",
         "> 生成时间：{} ｜ 信息截止时间：{} ｜ 检索时效过滤：{} ｜ 总搜索 {} 次 / 抓取正文 {} 页".format(
             now, now, freshness, searches_done, len(pages_read)), "",
         "## 摘要", "", summ["abstract"] or "（未生成）", ""]
    for i, sec in enumerate(sections):
        L += ["## {}. {}".format(i + 1, sec["question"]), "", sec["body"], ""]
    L += ["## 关键结论", ""]
    if summ["key_findings"]:
        for f in summ["key_findings"]:
            tag, why = confidence_tag(f["sources"])
            refs = "、".join("[{}]".format(SOURCES[u]["n"]) for u in f["sources"])
            src_text = ("，来源 " + refs) if refs else "，⚠ 无来源，标记为“模型推断”"
            L.append("- {}（置信度：{}——{}）{}".format(f["finding"], tag, why, src_text))
    else:
        L.append("（无）")
    L += ["", "## 遗留问题", ""]
    if summ["open_questions"]:
        for q in summ["open_questions"]:
            L.append("- " + q)
    else:
        L.append("（无）")
    L += ["", "## 置信度说明", "",
          "- 高：结论有 ≥2 个独立来源且相互一致；中：单一来源；低：无来源支撑，标注为“模型推断”。"]
    if summ["confidence_notes"]:
        L.append("- 总体评价：" + summ["confidence_notes"])
    L.append("- 信息截止时间：{}（个别来源发布时间可能更早，见来源列表）。".format(now))
    L += ["", "## 来源列表", ""]
    for u, s in sorted(SOURCES.items(), key=lambda kv: kv[1]["n"]):
        site = (" · " + s["site"]) if s["site"] else ""
        L.append("- [{}] {}｜{}{}".format(s["n"], s["title"][:80], u, site))
    L += ["", "## 附录：研究过程记录", ""]
    for e in log_entries:
        L.append("### 第 {} 轮".format(e["round"]))
        for s in e["searches"]:
            L.append("- 检索“{}”（子问题 {}）→ 新增 {} 条结果".format(
                s["query"], s["sub_question"] + 1, s["results"]))
        for u in e["pages"]:
            L.append("- 阅读：" + u)
        L.append("- 本轮决策：" + e["decision"])
        L.append("")
    L.append("共迭代 {} 轮，检索 {} 次，阅读 {} 页。".format(
        len(log_entries), searches_done, len(pages_read)))
    return "\n".join(L)


def slugify(topic):
    s = re.sub(r"[^\w一-鿿]+", "", topic)
    return s[:12] or "研究"


def save_report(topic, markdown):
    out_dir = Path(__file__).resolve().parent / "reports"
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / "{}_{}.md".format(ts, slugify(topic))
    path.write_text(markdown, encoding="utf-8")
    return path


# ---------- 主流程 ----------
def print_plan(sqs):
    print("研究计划：")
    for i, sq in enumerate(sqs):
        print("  {}. {}".format(i + 1, sq["question"]))
        print("     检索词：" + " / ".join(sq["queries"]))


def pick_materials(materials):
    """进入抽取的材料：摘要最多 6 条 + 正文最多 3 页。"""
    sums = [m for m in materials if m["kind"] == "摘要"][:6]
    pages = [m for m in materials if m["kind"] == "正文"][:3]
    return sums + pages


def run_research(topic, freshness="oneYear", fetch=True, auto=False):
    global SOURCES
    SOURCES = {}
    print("=" * 60)
    print("深度研究助手 ｜ 主题：" + topic)
    print("模型：{} ｜ 时效过滤：{} ｜ 正文抓取：{}".format(
        LLM_MODEL, freshness, "开" if fetch else "关"))
    print("=" * 60)

    # 1) 规划 + 人工确认
    print("[规划] LLM 拆解子问题...")
    sqs = plan(topic)
    replans = 0
    while True:
        print_plan(sqs)
        if auto:
            break
        try:
            inp = input("回车继续 / 输入补充要求重新规划 / q 退出：").strip()
        except (EOFError, KeyboardInterrupt):
            print("已取消。")
            return None
        if inp.lower() == "q":
            print("已取消。")
            return None
        if not inp:
            break
        if replans >= REPLAN_LIMIT:
            print("已达重排上限（{}次），按当前计划继续。".format(REPLAN_LIMIT))
            break
        replans += 1
        print("[规划] 按补充要求重新规划（{}/{}）：{}".format(replans, REPLAN_LIMIT, inp))
        sqs = plan(topic, inp)

    facts = [[] for _ in sqs]
    all_materials = [[] for _ in sqs]
    pages_read = []
    searches_done = 0
    seen_urls = set()
    fetched_urls = set()
    log_entries = []
    gap_queries = []

    for rnd in range(1, MAX_ROUNDS + 1):
        if rnd == 1:
            queries = [(q, i) for i, sq in enumerate(sqs) for q in sq["queries"][:1]]
        else:
            queries = gap_queries
        if not queries:
            print("[流程] 没有待执行的检索，结束。")
            break
        round_log = {"round": rnd, "searches": [], "pages": [], "decision": ""}
        new_materials = [[] for _ in sqs]

        # 2) 检索
        for q, i in queries:
            if searches_done >= MAX_SEARCHES:
                print("[搜索] 预算用尽，跳过：“{}”".format(q))
                continue
            try:
                results = bocha_search(q, freshness=freshness)
            except RuntimeError as e:
                print("[搜索] " + str(e))
                continue
            searches_done += 1
            fresh = [r for r in results if r["url"] not in seen_urls]
            for r in fresh:
                seen_urls.add(r["url"])
                register_source(r["url"], r["title"], r["site"])
            round_log["searches"].append({"query": q, "sub_question": i, "results": len(fresh)})
            print("[搜索] 子问题{} “{}” → 新增 {} 条".format(i + 1, q, len(fresh)))
            for r in fresh[:6]:
                text = (r["summary"] or r["snippet"])[:SUMMARY_CHARS]
                m = {"kind": "摘要", "title": r["title"], "url": r["url"],
                     "site": r["site"], "text": text}
                new_materials[i].append(m)
                all_materials[i].append(m)

        # 首轮结果过少的子问题，用备用检索词补一次
        if rnd == 1:
            for i, sq in enumerate(sqs):
                if len(new_materials[i]) >= 3 or searches_done >= MAX_SEARCHES:
                    continue
                if len(sq["queries"]) < 2:
                    continue
                q = sq["queries"][1]
                try:
                    results = bocha_search(q, freshness=freshness)
                except RuntimeError as e:
                    print("[搜索] " + str(e))
                    continue
                searches_done += 1
                fresh = [r for r in results if r["url"] not in seen_urls]
                for r in fresh:
                    seen_urls.add(r["url"])
                    register_source(r["url"], r["title"], r["site"])
                round_log["searches"].append({"query": q, "sub_question": i, "results": len(fresh)})
                print("[搜索] 子问题{} 备用检索 “{}” → 新增 {} 条".format(i + 1, q, len(fresh)))
                for r in fresh[:6]:
                    text = (r["summary"] or r["snippet"])[:SUMMARY_CHARS]
                    m = {"kind": "摘要", "title": r["title"], "url": r["url"],
                         "site": r["site"], "text": text}
                    new_materials[i].append(m)
                    all_materials[i].append(m)

        # 3) 抓取正文（阅读）
        if fetch:
            for i in range(len(sqs)):
                pool = [m for m in new_materials[i] if m["url"] not in fetched_urls]
                for m in pool[:TOP_PAGES]:
                    if len(pages_read) >= MAX_PAGES:
                        break
                    fetched_urls.add(m["url"])
                    text = fetch_page_text(m["url"])
                    if text:
                        pages_read.append({"url": m["url"], "title": m["title"]})
                        round_log["pages"].append(m["url"])
                        page = {"kind": "正文", "title": m["title"], "url": m["url"],
                                "site": m["site"], "text": text}
                        new_materials[i].append(page)
                        all_materials[i].append(page)
                        print("[阅读] " + m["url"][:90])
                    else:
                        print("[阅读] 失败/非HTML，跳过：" + m["url"][:60])

        # 4) 阅读抽取
        unanswered = {}
        for i, sq in enumerate(sqs):
            if not new_materials[i]:
                continue
            res = extract_facts(sq["question"], pick_materials(new_materials[i]), facts[i])
            facts[i].extend(res["facts"])
            if res["unanswered"]:
                unanswered[i] = res["unanswered"]
            tail = "，遗留 {} 问".format(len(res["unanswered"])) if res["unanswered"] else ""
            print("[抽取] 子问题{}：+{} 条事实{}".format(i + 1, len(res["facts"]), tail))
        # 尚无任何事实的子问题，强制进入补检视野
        for i in range(len(sqs)):
            if not facts[i]:
                unanswered.setdefault(i, []).append("该子问题尚未获得任何有来源支撑的事实，需要补充检索")

        # 5) 补检判断
        if rnd < MAX_ROUNDS and searches_done < MAX_SEARCHES and unanswered:
            gap_queries = judge_gap(unanswered, rnd, searches_done)
            if gap_queries:
                fallback_i = max(unanswered, key=lambda k: len(unanswered[k]))
                gap_queries = [(q, i if 0 <= i < len(sqs) else fallback_i) for q, i in gap_queries]
            round_log["decision"] = ("补检 {} 个查询".format(len(gap_queries))
                                     if gap_queries else "材料已足够，结束检索")
        else:
            gap_queries = []
            round_log["decision"] = "预算用尽或最后一轮，结束检索"
        print("[判断] " + round_log["decision"])
        log_entries.append(round_log)
        if not gap_queries:
            break

    # 6) 写作与落盘
    print("[写作] 逐节撰写...")
    sections = []
    for i, sq in enumerate(sqs):
        source_map = {u: SOURCES[u]["n"] for f in facts[i] for u in f["sources"]}
        body = write_section(sq["question"], facts[i], source_map)
        sections.append({"question": sq["question"], "body": body})
        print("[写作] 第 {}/{} 节完成".format(i + 1, len(sqs)))
    print("[写作] 汇总摘要、关键结论、遗留问题与置信度...")
    summ = assemble(topic, sections, {u: s["n"] for u, s in SOURCES.items()})
    report = build_report(topic, sqs, sections, summ, log_entries, pages_read,
                          searches_done, freshness)
    path = save_report(topic, report)
    print("-" * 60)
    print("报告已生成：" + str(path))
    print("摘要：" + (summ["abstract"][:200] or "（无）"))
    return str(path)


def main():
    ap = argparse.ArgumentParser(
        description="深度研究助手：输入主题，自动检索、阅读、综合，产出带来源引用的研究报告。")
    ap.add_argument("topic", nargs="*", help="研究主题（可含空格）；缺省时交互输入")
    ap.add_argument("--llm-key", help="LLM API key（缺省：环境变量 DEEPSEEK_API_KEY，再缺省：内置默认）")
    ap.add_argument("--search-key", help="搜索 API key（缺省：环境变量 BOCHA_API_KEY，再缺省：内置默认）")
    ap.add_argument("--freshness", default="oneYear",
                    help="搜索时效过滤：noLimit/oneDay/oneWeek/oneMonth/oneYear（默认 oneYear）")
    ap.add_argument("--no-fetch", action="store_true", help="不抓取来源网页正文，仅用搜索摘要")
    ap.add_argument("--yes", action="store_true", help="跳过计划确认，全自动执行")
    args = ap.parse_args()

    global BOCHA_KEY, LLM_KEY
    BOCHA_KEY = args.search_key or os.environ.get("BOCHA_API_KEY") or DEFAULT_BOCHA_KEY
    LLM_KEY = args.llm_key or os.environ.get("DEEPSEEK_API_KEY") or DEFAULT_LLM_KEY

    topic = " ".join(args.topic).strip()
    if not topic:
        topic = input("请输入研究主题：").strip()
        if not topic:
            print("主题为空，退出。")
            return
    try:
        run_research(topic, args.freshness, fetch=not args.no_fetch, auto=args.yes)
    except KeyboardInterrupt:
        print("\n已中断。")


if __name__ == "__main__":
    main()

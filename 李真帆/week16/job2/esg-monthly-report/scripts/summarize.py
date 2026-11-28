"""逐篇调用大模型，把候选线索提炼成固定结构的卡片，在 agent 上下文之外完成。

用法：
  python summarize.py --schema evidence --in candidates.jsonl --out cards.jsonl
                     --context "客户=中国神华；行业=煤炭；对标=中煤能源、兖矿能源、陕西煤业；时间窗=2026-10-27 至 2026-11-26"
  python summarize.py --schema bid --in bid_candidates.jsonl --out bids.jsonl
选项：--limit 最多处理条数；--concurrency 并发数；--min-score 只处理关键词分数不低于该值的线索
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, field_validator

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

SYSTEM = ("你是{role}。只能使用给定材料里出现的事实，材料里没有的信息留空，不要推测，不要补充材料以外的知识。"
          "日期一律写成 YYYY-MM-DD。只输出一个 JSON 对象。")

EVIDENCE_SPEC = """字段：
- title：网页标题，保留原文
- publisher：发布机构，判断不出留空
- published：网页正文里写明的发布日期 YYYY-MM-DD；没有写明就照抄"搜索日期"，也没有就留空
- key_points：3 到 5 条事实要点，保留数字、机构名、文件名，不评论
- section：六选一。policy（ESG 相关政策法规与监管动态）、rating（ESG 评级、指数、披露标准的变化）、industry（客户所在行业的新闻与最佳实践）、company（客户自身的动态）、peer（对标企业的动态）、irrelevant（与以上都无关）
- topics：涉及的 ESG 议题数组，如 "E-碳排放"、"S-安全生产"、"G-合规"
- relevance：四选一。high（直接关系到客户或其所处行业）、medium（有参考价值）、low（关系很弱）、irrelevant
- impact：对客户的影响等级，高、中、低 三选一；与客户无关填低
- impact_reason：一句话说明对客户的影响及理由；与客户无关留空"""

BID_SPEC = """字段：
- is_esg：true 或 false。标题和材料是否表明这是 ESG、可持续发展、双碳相关的服务类项目（报告编制、咨询规划、核查核算、培训、平台等）；采购物质、设备、耗材，或与 ESG 无关的工程为 false
- notice_type：三选一。award（中标、成交、中选结果或候选人公示）、tender（招标公告、磋商、询价等未出结果）、other
- project：项目名称
- purchaser：采购人或招标人
- winner：中标人或成交供应商；未出结果留空
- amount_wan：中标或成交金额，单位万元，填数字；材料里没有明确写出金额则为 null。不要用预算代替，不要换算推测
- amount_text：金额的原文写法，如 "26.34万元"；没有留空
- budget_text：预算或最高限价的原文写法；没有留空
- deadline：投标或响应截止时间；没有留空
- notice_date：公告日期 YYYY-MM-DD；材料里没有就照抄"搜索日期"，也没有留空
- province：省份或直辖市简称，如 "福建"；判断不出留空
- project_type：九选一。ESG报告编制、ESG咨询与体系、碳核查与盘查、双碳规划、碳资产与交易、数字化平台、绿色认证、能源与节能、其他
- purchaser_type：五选一。政府机关、事业单位、国企、金融机构、企业
- reason：一句话说明判断依据"""


class Evidence(BaseModel):
    title: str = ""
    publisher: str = ""
    published: str = ""
    key_points: list[str] = []
    section: str = "irrelevant"
    topics: list[str] = []
    relevance: str = "low"
    impact: str = "低"
    impact_reason: str = ""


class Bid(BaseModel):
    is_esg: bool = False
    notice_type: str = "other"
    project: str = ""
    purchaser: str = ""
    winner: str = ""
    amount_wan: float | None = None
    amount_text: str = ""
    budget_text: str = ""
    deadline: str = ""
    notice_date: str = ""
    province: str = ""
    project_type: str = "其他"
    purchaser_type: str = "企业"
    reason: str = ""

    @field_validator("amount_wan", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        return None if v in ("", "null", "None", "暂无", "-", "无") else v


SECTION_CODES = {"政策": "policy", "评级": "rating", "标准": "rating", "行业": "industry", "公司": "company",
                 "客户": "company", "对标": "peer", "无关": "irrelevant"}
PROJECT_TYPES = ("ESG报告编制", "ESG咨询与体系", "碳核查与盘查", "双碳规划", "碳资产与交易", "数字化平台",
                "绿色认证", "能源与节能", "其他")


NOTICE_CODES = {"award": "award", "中标": "award", "成交": "award", "中选": "award", "tender": "tender",
                "招标": "tender", "磋商": "tender", "询价": "tender"}


def _pick(value: str, allowed: tuple, default: str) -> str:
    value = (value or "").strip()
    for a in allowed:
        if value and (value in a or a in value):
            return a
    return default


def coerce_evidence(card: dict) -> dict:
    section = (card.get("section") or "").strip().lower()
    if section not in ("policy", "rating", "industry", "company", "peer", "irrelevant"):
        section = next((code for key, code in SECTION_CODES.items() if key in section), "irrelevant")
    card["section"] = section
    card["relevance"] = _pick(card.get("relevance", "").lower(), ("high", "medium", "low", "irrelevant"), "low")
    card["impact"] = _pick(card.get("impact", ""), ("高", "中", "低"), "低")
    card["published"] = c.normalize_date(card.get("published", ""))
    card["key_points"] = [str(p).strip() for p in card.get("key_points") or [] if str(p).strip()][:6]
    return card


def coerce_bid(card: dict) -> dict:
    text = card.get("notice_type", "").lower()
    card["notice_type"] = next((code for key, code in NOTICE_CODES.items() if key in text), "other")
    card["project_type"] = _pick(card.get("project_type", ""), PROJECT_TYPES, "其他")
    card["purchaser_type"] = _pick(card.get("purchaser_type", ""), ("政府机关", "事业单位", "国企", "金融机构", "企业"), "企业")
    card["notice_date"] = c.normalize_date(card.get("notice_date", ""))
    if card.get("amount_wan") is not None and card["amount_wan"] <= 0:
        card["amount_wan"] = None
    return card


def build_input(rec: dict) -> str:
    text = (rec.get("text") or rec.get("snippet") or "")[:4000]
    head = (f"【背景】{CONTEXT}\n【页面】标题：{rec.get('title', '')}\n网站：{rec.get('site', '')}\n"
            f"搜索日期：{rec.get('published', '')}\n链接：{rec.get('url', '')}\n【材料】\n{text}")
    return head


CONTEXT = ""


def _cache_path(rec: dict, schema: str) -> Path:
    key = hashlib.sha1((schema + "|" + (rec.get("url") or "") + "|" + (rec.get("text") or "")[:2000]).encode()).hexdigest()
    p = c.CACHE_DIR / "summarize"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{key}.json"


def cache_get(rec: dict, schema: str) -> dict | None:
    p = _cache_path(rec, schema)
    if p.is_file():
        out = json.loads(p.read_text(encoding="utf-8"))
        out["cached"] = True
        return out
    return None


def cache_put(rec: dict, schema: str, out: dict) -> None:
    _cache_path(rec, schema).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")


def work(rec: dict, schema: str) -> dict:
    cached = cache_get(rec, schema)
    if cached:
        return cached
    base = {"url": rec.get("url"), "title": rec.get("title"), "site": rec.get("site"), "score": rec.get("score", 0),
            "queries": rec.get("queries") or [rec.get("query", "")],
            "basis": "fulltext" if rec.get("text") else "snippet"}
    if schema == "evidence":
        role = "ESG 研究员，负责把网页内容整理成一张证据卡"
        obj, usage = c.llm_json(SYSTEM.format(role=role) + "\n" + EVIDENCE_SPEC, build_input(rec), Evidence)
        card = coerce_evidence(obj.model_dump())
        published = rec.get("published") or card.get("published", "")
        out = base | {"published": published, "card": card, "usage": usage, "error": ""}
    else:
        role = "招投标分析师，负责从招标或中标公告里提取结构化信息"
        obj, usage = c.llm_json(SYSTEM.format(role=role) + "\n" + BID_SPEC, build_input(rec), Bid)
        card = coerce_bid(obj.model_dump())
        out = base | {"published": card.get("notice_date") or rec.get("published", ""), "card": card,
                      "usage": usage, "error": ""}
    cache_put(rec, schema, out)
    return out


def main() -> int:
    c.init()
    global CONTEXT
    ap = argparse.ArgumentParser(description="逐篇调用大模型，把线索提炼成固定结构的卡片")
    ap.add_argument("--schema", choices=["evidence", "bid"], required=True)
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--context", default="", help="客户、行业、对标企业、时间窗等背景，evidence 模式建议提供")
    ap.add_argument("--limit", type=int, default=100, help="最多处理条数")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--min-score", type=int, help="只处理关键词分数不低于该值的线索")
    args = ap.parse_args()
    if not c.llm_configured():
        sys.exit("未配置 DEEPSEEK_API_KEY：在 .env 里填写后重试")
    CONTEXT = args.context

    rows = c.read_jsonl(args.inp)
    if args.min_score is not None:
        skipped = [r for r in rows if (r.get("score") or 0) < args.min_score]
        rows = [r for r in rows if (r.get("score") or 0) >= args.min_score]
    else:
        skipped = []
    rest = rows[args.limit:]
    rows = rows[: args.limit]

    def safe(rec: dict) -> dict:
        try:
            return work(rec, args.schema)
        except Exception as e:
            return {"url": rec.get("url"), "title": rec.get("title"), "site": rec.get("site"),
                    "card": None, "usage": {}, "error": f"{type(e).__name__}: {str(e)[:160]}"}

    out = c.pmap(rows, safe, args.concurrency)
    for r in skipped + rest:
        out.append({"url": r.get("url"), "title": r.get("title"), "site": r.get("site"), "card": None, "usage": {},
                    "error": "未处理：分数低于下限" if skipped and r in skipped else "未处理：超出条数上限"})
    n = c.write_jsonl(args.out, out)

    done = [r for r in out if r.get("card")]
    failed = [r for r in out if r.get("error")]
    tokens = Counter()
    for r in done:
        tokens.update(r.get("usage") or {})
    print(f"[summarize] schema={args.schema} 输入={len(rows)} 成功={len(done)} 失败={len(failed)} "
          f"token（输入 {tokens.get('prompt_tokens', 0)}，输出 {tokens.get('completion_tokens', 0)}）输出={args.out}")
    if done and args.schema == "evidence":
        sections = Counter(r["card"]["section"] for r in done)
        relevance = Counter(r["card"]["relevance"] for r in done)
        print("[summarize] 章节分布：" + "，".join(f"{k} {v}" for k, v in sections.most_common()))
        print("[summarize] 相关性分布：" + "，".join(f"{k} {v}" for k, v in relevance.most_common()))
    if done and args.schema == "bid":
        cards = [r["card"] for r in done]
        esg = [k for k in cards if k["is_esg"]]
        award = [k for k in esg if k["notice_type"] == "award"]
        print(f"[summarize] 判定为 ESG 项目 {len(esg)} 条，其中中标类 {len(award)} 条，"
              f"披露金额 {sum(1 for k in award if k.get('amount_wan') is not None)} 条")
    for r in failed[:5]:
        print(f"[summarize] 失败示例 {r.get('url')}: {r.get('error')}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(c.guard("summarize", main))

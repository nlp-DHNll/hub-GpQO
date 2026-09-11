"""深度研究主流程编排：规划 → 多轮检索 → 判缺补检 → 报告生成。

数据流：
  plan(topic) -> SubQuestion[]
  对每个 sub：
      第 1 轮跑主检索(直接用其 query_kw)
      rounds 2..max_rounds：判缺 suggest_supplement，若需补检则再搜一轮，否则标 done
  汇总全部 SourceRef -> 去重 -> 编号
  report = llm 综合成 摘要/分节/结论/遗留 文本（让其引用 [n]）
  Report 交 report.render_full() 渲染并溯源标注
"""
from __future__ import annotations

import datetime
from typing import Optional

from .llm import LLM
from .schemas import (ProcessLog, Report, ReportSection, SourceRef, SubQuestion)
from .search import Searcher


_SYS_DECOMPOSE = """你是一个「深度研究助手」的规划器。给定一个研究主题，把它拆成适合检索与写作的若干子问题。
要求：每个子问题应能独立支撑调研（竞品、趋势、技术选型、政策解读、市场等角度都可以），并给出一条最可能命中高质量结果的检索关键词（用中文或英文皆可，尽量具体）。
输出严格 JSON，不要多余文本：
{"questions":[{"text":"子问题表述","keyword":"检索词"}]}
3~5 个为宜。"""

_SYS_SUPPLEMENT = """你是深度研究助手的内容评估器。以下已为本子问题检索到若干网页来源。判断现有材料对回答够不够。
若已足够写成有据可依的一节，回答 done=true；否则 done=false 并给出 1~2 条能补盲的新检索词。
输出严格 JSON：{"done":true} 或 {"done":false,"new_keywords":["...","..."]}。"""

_SYS_REPORT = """你是一个研究报告撰写者。下面是针对一个主题检索到的全部网页来源（编号即文末来源序号），以及拆解的子问题。
请综合写一份结构化中文报告，正文对每条来自来源的断言显式标注 [n]（n 为来源序号）；无法归因到任何来源的表述不加下标（会被系统标为模型推断）。
按以下结构输出，每节内容用markdown；不要输出除报告正文之外的说明文字。

【报告】
## 摘要
…2~3句总览…

## 正文
对拆解的每个子问题给出 ### 小节标题与要点…

## 关键结论
- 结论1（尽量带 [n]）

## 遗留问题
- 未能从来源确证的开放问题…

只输出上面四段 markdown。"""


def _utc_cn() -> str:
    try:
        return (datetime.datetime.now(datetime.timezone.utc)
                .astimezone(datetime.timezone(datetime.timedelta(hours=8)))
                .strftime("%Y-%m-%d %H:%M"))
    except Exception:
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


class ResearchAgent:
    """把 LLM 与 Searcher 串成『深度研究』闭环。"""

    def __init__(self, llm: Optional[LLM] = None, searcher: Optional[Searcher] = None,
                 max_rounds: int = 3, count_per_round: int = 5,
                 question_limit: int = 5) -> None:
        self.llm = llm if llm is not None else LLM.from_env()
        self.searcher = searcher if searcher is not None else Searcher.from_env()
        self.max_rounds = max_rounds
        self.count = count_per_round
        self.question_limit = question_limit

    # ---------- 规划 ----------
    def _plan(self, topic: str) -> list[SubQuestion]:
        if self.llm.is_stub():
            # 桩演示：给一个通用子问题，后台照常走一轮检索（若配了搜索 key 仍有真实线索）
            return [SubQuestion(text=topic, query_kw=self._default_kw(topic))]
        user = f"研究主题：{topic}\n请 JSON 拆子问题。"
        d = self.llm.chat_json(_SYS_DECOMPOSE, user)
        if isinstance(d, dict) and isinstance(d.get("questions"), list):
            subs = [q for q in d["questions"] if isinstance(q, dict)
                    and (q.get("text") or q.get("keyword"))]
            out = [SubQuestion(text=str(q.get("text") or q.get("keyword")),
                               query_kw=str(q.get("keyword") or "")) for q in subs]
            # 过滤空检索词/超限
            out = [s for s in out if s.query_kw.strip()][: self.question_limit]
            if out:
                return out
        return [SubQuestion(text=topic, query_kw=self._default_kw(topic))]

    @staticmethod
    def _default_kw(topic: str) -> str:
        """无 LLM 时的兜底检索词：取「：」之后、单词上限内最前一段，避免整句过长。"""
        raw = topic.split("：")[-1] if "：" in topic else topic
        raw = raw.strip() or topic
        # 截到约 30 字内的自然断点，避免检索词过长
        return raw[:90].strip().rstrip("，。,。") or topic[:120]

    # ---------- 检索 ----------
    def _search_sub(self, kw: str, round_no: int) -> list[SourceRef]:
        urls: list[str] = []
        srcs = self.searcher.search(kw, count=self.count)
        srcs = srcs[: max(1, self.count)]
        for s in srcs:
            s.query = kw
            if s.url and s.url not in urls:
                urls.append(s.url)
        # 记录进过程日志（即便 NoSearch 返回空也记录一次检索动作）
        self.process.add_step(round_no, kw, urls)
        return srcs

    # ---------- 判缺/补检 ----------
    def _supplement_kws(self, sub: SubQuestion, blurb: str) -> list[str]:
        if self.llm.is_stub():
            return []  # 桩不做二次检索决策，避免无限追加
        user = (f"子问题：{sub.text}\n现有材料(截断)如下：\n{blurb}\n"
                "请告诉我是否需要补检？输出 JSON 决策。")
        d = self.llm.chat_json(_SYS_SUPPLEMENT, user)
        if isinstance(d, dict) and d.get("done") is True:
            return []
        kws = d.get("new_keywords") if isinstance(d, dict) else None
        return [str(k) for k in (kws or []) if str(k).strip()][:3]

    # ---------- 入口 ----------
    def run(self, topic: str) -> Report:
        self.process = ProcessLog(topic=topic)
        subs = self._plan(topic)

        # 多轮检索：按轮推进每个未 done 的子问题。exhausted 用于搜索全空的桩/空库情形，
        # 避免在只有桩结果时白跑满 max_rounds 但有意义的分轮记录仍保留。
        exhausted = False
        for round_no in range(1, self.max_rounds + 1):
            progressed = False
            for sub in subs:
                if sub.done:
                    continue
                if round_no > 1:
                    extra = self._supplement_kws(sub, self._evidence_blurb(sub))
                    if not extra:
                        sub.done = True
                        continue
                    kws = extra
                else:
                    kws = [sub.query_kw] if sub.query_kw.strip() else []
                for kw in kws:
                    new = self._search_sub(kw, round_no)
                    merged = self._merge(sub, new)
                    progressed = progressed or merged
            if not progressed:
                # 桩/Search 全空：不再无意义叠轮次
                exhausted = True
            if all(s.done for s in subs) or (exhausted and round_no >= 1):
                break
        return self._write(topic, subs)

    @staticmethod
    def _merge(sub: SubQuestion, new: list[SourceRef]) -> bool:
        """合并新来源进子问题，返回是否有新增。按 url（或标题+摘要）去重。"""
        added = 0
        for s in new:
            key = s.url or (s.title + s.summary)
            if any(x.url and x.url == s.url for x in sub.relevant):
                continue
            if any(not s.url and (x.title + x.summary) == key for x in sub.relevant):
                continue
            sub.relevant.append(s)
            added += 1
        return added > 0

    # ---------- 报告 ----------
    def _all_sources(self, subs: list[SubQuestion]) -> list[SourceRef]:
        merged: dict[str, SourceRef] = {}
        for sub in subs:
            for s in sub.relevant:
                key = s.url or (s.title + s.summary)
                if key and key not in merged:
                    if s.url:
                        merged[key] = s
                    elif "None" not in key:  # 无 url 的做尽力保留
                        merged[key] = s
        return list(merged.values())

    def _evidence_blurb(self, sub: SubQuestion, limit: int = 6) -> str:
        lines = []
        for i, s in enumerate(sub.relevant[:limit], 1):
            lines.append(f"{i}. {s.title}｜{s.snippet or s.summary or ''}".strip())
        return "\n".join(lines) if lines else "(暂无材料)"

    def _write(self, topic: str, subs: list[SubQuestion]) -> Report:
        sources = self._all_sources(subs)
        # 全部有据来源的截断摘要喂给撰写器
        context_snippets = []
        for idx, s in enumerate(sources, 1):
            snippet = (s.title + "：" + (s.snippet or s.summary))[:900]
            context_snippets.append(f"[{idx}] {snippet}（{s.url}）")
        context_str = "\n".join(context_snippets) if context_snippets else "(无检索到来源)"

        gen_at = _utc_cn()
        # 桩：无 deepseek → 构造一份清晰的可展示模板报告
        if self.llm.is_stub():
            return self._demo_report(topic, subs, sources, gen_at, context_snippets)

        sub_questions_txt = "\n".join(f"- {s.text}" for s in subs)
        user = (f"研究主题：{topic}\n\n拆解的子问题：\n{sub_questions_txt}\n\n"
                f"检索到的来源（[n]=来源序号）：\n{context_str}\n请按系统要求输出报告正文。")
        body = self.llm.chat(_SYS_REPORT, user)
        if not body:
            return self._demo_report(topic, subs, sources, gen_at, [])
        # 把体按四段粗切（容错，缺失也无妨交由渲染器兜底）
        return self._parse_report(topic, body, sources, gen_at)

    def _parse_report(self, topic, body, sources, gen_at) -> Report:
        """从 LLM 正文里尽力抽出 摘要/小节/结论/遗留；缺就放空由渲染器兜底。"""
        sec_marker = {"## 摘要": None, "## 正文": None, "## 关键结论": None,
                      "## 遗留问题": None}
        blocks: dict[str, str] = {}
        cur = None
        buf = []
        for ln in body.splitlines():
            bare = ln.strip()
            if bare in sec_marker:
                if cur:
                    blocks[cur] = "\n".join(buf).strip()
                cur = bare; buf = []
            else:
                if cur:
                    buf.append(ln)
        if cur:
            blocks[cur] = "\n".join(buf).strip()

        def sectionless(name):
            start = body.find(name)
            if start < 0:
                return ""
            end = body.find("## ", start + 1)
            return body[start + len(name): end if end > 0 else len(body)].strip()

        summary = blocks.get("## 摘要") or sectionless("## 摘要")
        body_txt = blocks.get("## 正文") or sectionless("## 正文")
        concl = blocks.get("## 关键结论") or sectionless("## 关键结论")
        open_q = blocks.get("## 遗留问题") or sectionless("## 遗留问题")
        sections = _split_body_sections(body_txt)

        report = Report(
            topic=topic,
            summary=summary,
            sections=sections,
            conclusions=[c.strip(" -") for c in concl.splitlines() if c.strip(" -")] if concl else [],
            open_questions=[q.strip(" -") for q in open_q.splitlines() if q.strip(" -")] if open_q else [],
            sources=sources,
            generated_at=gen_at,
            process=self.process,
        )
        return report

    def _demo_report(self, topic, subs, sources, gen_at, snippets) -> Report:
        """无 LLM key 时的可运行演示报告（主体明确标注为桩输出）。"""
        src_txt = "\n".join(f"- {s}" for s in snippets) if snippets else "（无）"
        sections = [ReportSection(
            heading="说明（未配置 LLM 的桩演示）",
            body=("本报告由演示桩生成：未检测到 DEEPSEEK_API_KEY。"
                  "以下各节为桩模板文本，不含真实联网检索推理与权威结论，"
                  "*(模型推断)* 处尤其不要直接用作业务结论。\n\n"
                  f"拟调研子问题：\n{chr(10).join('- ' + s.text for s in subs)}"),
        )]
        if sources:
            sections.append(ReportSection(heading="本次真实检索到的来源示例",
                                          body=src_txt))
        report = Report(
            topic=topic,
            summary=("（桩演示）本摘要为模板文本。配置 DEEPSEEK_API_KEY 与 BOCHA_API_KEY "
                     "后运行，将产出真实深度研究。"),
            sections=sections,
            conclusions=[],
            open_questions=["如何配置真实 API key 并跑通联网研究？"],
            sources=sources,
            generated_at=gen_at,
            process=self.process,
        )
        return report


def _split_body_sections(body: str) -> list[ReportSection]:
    """把『### 小节…』文本切成 ReportSection 列表；无子标题则整体给一节。"""
    if not body:
        return []
    lines = body.splitlines()
    out: list[ReportSection] = []
    cur_head = ""
    cur_buf: list[str] = []
    for ln in lines:
        if ln.strip().startswith("###"):
            if cur_head or cur_buf:
                out.append(ReportSection(heading=cur_head, body="\n".join(cur_buf).strip()))
            cur_head = ln.strip().lstrip("#").strip()
            cur_buf = []
        else:
            cur_buf.append(ln)
    out.append(ReportSection(heading=cur_head, body="\n".join(cur_buf).strip()))
    # 丢弃全空节
    return [s for s in out if s.heading or s.body]

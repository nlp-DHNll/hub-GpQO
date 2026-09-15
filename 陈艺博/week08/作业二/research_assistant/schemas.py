"""共用数据结构：来源、子问题、过程记录、报告。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SourceRef:
    """一次检索返回的单条网页来源（可追溯）。"""

    url: str = ""
    title: str = ""
    summary: str = ""
    snippet: str = ""  # Bocha webpages 里无 summary 时的正文片段
    source: str = ""
    publish_time: str = ""
    query: str = ""  # 由哪个检索词命中的，便于溯源

    def describe(self) -> str:
        title = self.title or self.url or "(未命名来源)"
        return f"{title}（{self.source}）" if self.source else title


@dataclass
class SubQuestion:
    """规划阶段拆出的一个子问题及其检索词。"""

    text: str
    query_kw: str  # 南向检索关键词（贴合竞品/趋势/选型/政策调研）

    # 运行期由 agent 填充
    relevant: list[SourceRef] = field(default_factory=list)
    done: bool = False


@dataclass
class SearchStep:
    """一轮检索的记录（用于过程日志）。"""

    round_no: int
    kw: str
    urls: list[str] = field(default_factory=list)
    hits: int = 0


@dataclass
class ProcessLog:
    """研究过程记录：检索词 / url / 迭代轮次。"""

    topic: str = ""
    rounds: int = 0
    steps: list[SearchStep] = field(default_factory=list)

    def add_step(self, round_no: int, kw: str, urls: list[str]) -> None:
        self.rounds = max(self.rounds, round_no)
        if not any(s.kw == kw and s.round_no == round_no for s in self.steps):
            self.steps.append(SearchStep(round_no, kw, list(urls), len(urls)))


@dataclass
class ReportSection:
    """报告正文的一节。"""

    heading: str
    body: str  # markdown，可含数字来源标注 [n]


@dataclass
class Report:
    """Agent 的最终产出。"""

    topic: str
    summary: str
    sections: list[ReportSection]
    conclusions: list[str]  # 关键结论（结论正文可带 [n]）
    open_questions: list[str]
    sources: list[SourceRef]  # 全部来源（报告内 url 可追溯）
    generated_at: str = ""
    note_lines: list[str] = field(default_factory=list)  # 置信度说明等备注
    process: ProcessLog = field(default_factory=ProcessLog)

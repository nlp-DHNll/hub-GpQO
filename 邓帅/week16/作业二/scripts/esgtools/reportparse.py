"""报告正文（Markdown）的读取：切章节、找角标、读报告开头的声明。

验收器的章节、角标与开头声明三条规则都建立在这里；只做确定性的文本解析，不猜。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")
_CITATION = re.compile(r"(?<!\^)\[(\d{1,4})\](?![:(])")
"""角标：方括号里一个编号。排除脚注 [^n]、链接 [1](…) 与引用定义 [1]: …"""

_OFF_SPEC_CITATION = re.compile(r"\[\^\d{1,4}\]|【\d{1,4}】|<sup>\[\d{1,4}\]</sup>")
"""常见的几种非约定角标写法，查出来提示改法。"""


@dataclass
class Section:
    """报告里的一节：一个标题，连同它到下一个同级或更高级标题之前的全部内容（含小节）。

    记下行区间（``start_line`` 是标题行，``end_line`` 不含），这样取正文时直接用原文的行，
    不会因为二级节已包含三级小节而把小节算两遍。
    """

    title: str
    level: int
    content: str
    start_line: int
    end_line: int

    def has_table(self) -> bool:
        """本节内是否至少有一张 Markdown 表格（表头行后跟分隔行）。"""
        lines = self.content.splitlines()
        return any(
            line.lstrip().startswith("|")
            and number + 1 < len(lines)
            and _TABLE_SEPARATOR.match(lines[number + 1])
            for number, line in enumerate(lines)
        )


@dataclass
class Report:
    """切好的报告：原文各行与各节。取正文时用行区间从原文里取，不另行拼接。"""

    lines: list[str]
    sections: list[Section]

    def find(self, predicate: Callable[[str], bool]) -> Section | None:
        """第一个标题满足 ``predicate`` 的节。"""
        return next((section for section in self.sections if predicate(section.title)), None)

    def text_excluding(self, dropped: Sequence[Section]) -> str:
        """去掉若干节（连同标题）之后的全文。"""
        spans = [(section.start_line, section.end_line) for section in dropped]
        return "\n".join(
            line
            for number, line in enumerate(self.lines)
            if not any(start <= number < end for start, end in spans)
        )

    def text_before(self, section: Section) -> str:
        """某一节标题之前的全文。"""
        return "\n".join(self.lines[: section.start_line])


def split_sections(report: str) -> Report:
    """按 ATX 标题（``#`` 开头的行）切分报告；围栏代码块里的井号行不算标题。"""
    lines = report.splitlines()
    starts: list[tuple[int, int, str]] = []
    in_fence = False
    for number, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        matched = _HEADING.match(line) if not in_fence else None
        if matched:
            starts.append((number, len(matched[1]), matched[2]))

    sections: list[Section] = []
    for index, (line_no, level, title) in enumerate(starts):
        end = len(lines)
        for later_no, later_level, _ in starts[index + 1 :]:
            if later_level <= level:
                end = later_no
                break
        sections.append(Section(title, level, "\n".join(lines[line_no + 1 : end]), line_no, end))
    return Report(lines, sections)


def find_citations(body: str) -> list[int]:
    """一段正文里出现的全部角标编号，重复出现重复计数。"""
    return [int(matched[1]) for matched in _CITATION.finditer(body)]


def find_off_spec_citations(body: str) -> list[str]:
    """一段正文里不符合 [n] 约定的角标写法，原样返回，用来提示改法。"""
    return _OFF_SPEC_CITATION.findall(body)


def first_cell_ints(section: Section) -> list[int]:
    """本节表格里每一行第一列中的整数；证据表附录的第一列就是角标编号。"""
    found: list[int] = []
    for line in section.content.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = line.strip().strip("|").split("|")
        matched = re.search(r"\d{1,4}", cells[0]) if cells else None
        if matched:
            found.append(int(matched[0]))
    return found


_URL = re.compile(r"https?://[^\s<>\[\]\"'`|]+")
_URL_TAIL_PUNCTUATION = ".,;:!?、。，；：）)]}"


def find_urls(text: str) -> list[str]:
    """一段文字里的全部网页地址，按出现顺序；去掉紧贴在地址尾部的标点。"""
    return [found.rstrip(_URL_TAIL_PUNCTUATION) for found in _URL.findall(text)]


# ---- 报告开头的声明 ----

_LABEL_LINE = re.compile(r"^\s*(?:>\s*)*(?:[-*+]\s+)?[*`]*\s*([^:*`：:|｜；;]+?)[*`]*\s*[：:]\s*(.*?)\s*$")
"""行首的「标签：值」；行首的项目符号、引用符号与强调符号都不算标签的一部分。"""

_NEXT_LABEL = re.compile(r"[|｜;；]\s*[*`]{0,2}\s*([^:*`：:|｜；;\s]{1,12})\s*[*`]{0,2}\s*[：:](?=\s*\S)")
"""同一行里接着出现的下一个标签：分隔符 + 一个不带空格的短标签 + 冒号。"""

_PLACEHOLDERS = {"", "无", "暂无", "待定", "待补", "未知", "略", "-", "—", "n/a", "na", "tbd"}


def _labeled_segments(line: str) -> list[tuple[str, str]]:
    """把一行拆成若干 (标签, 值)：行首一个，之后每遇到「分隔符 + 短标签 + 冒号」再起一个。

    值里出现分隔符但后面不是「短标签 + 冒号」的不拆，例如「覆盖范围：…；关键词「A」「B」」。
    """
    matched = _LABEL_LINE.match(line)
    if matched is None:
        return []
    label, rest = matched[1], matched[2]
    segments: list[tuple[str, str]] = []
    while True:
        following = _NEXT_LABEL.search(rest)
        if following is None:
            segments.append((label.strip(), rest.strip().strip("*`")))
            return segments
        segments.append((label.strip(), rest[: following.start()].strip().strip("*`")))
        label, rest = following[1], rest[following.end() :]


def declared_values(opening: str) -> dict[str, str]:
    """读出报告开头声明里的标签与值。

    接受三种写法：一行 ``- 标签：值``（项目符号与引用符号可省）、同一行用 ｜ 或 ; 并排几个标签、
    或表格行 ``| 标签 | 值 |``。同一标签出现多次时取第一处。
    """
    values: dict[str, str] = {}
    for line in opening.splitlines():
        if line.lstrip().startswith("|"):
            cells = [cell.strip().strip("*`") for cell in line.strip().strip("|").split("|")]
            for label, value in zip(cells, cells[1:], strict=False):
                values.setdefault(label, value)
            continue
        for label, value in _labeled_segments(line):
            values.setdefault(label, value)
    return values


def is_declared(value: str | None) -> bool:
    """这个值算不算「写明了」：有内容，且不是「待定」「未知」之类的占位词。"""
    return value is not None and value.strip().strip("*`").lower() not in _PLACEHOLDERS


_VISIBLE_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_DECORATION = re.compile(r"(?m)^\s*(?:#{1,6}|>|[-*+])\s+")


def visible_chars(text: str) -> int:
    """一段 Markdown 渲染后可见的非空白字符数，用来数正文字数。

    不计：标题井号、列表符号、表格竖线与分隔行、角标 [n]、强调与代码符号、链接地址。
    """
    lines = [line for line in text.splitlines() if not _TABLE_SEPARATOR.match(line)]
    plain = _VISIBLE_LINK.sub(r"\1", "\n".join(lines))
    plain = _CITATION.sub("", plain)
    plain = _DECORATION.sub("", plain)
    plain = re.sub(r"[*`|]", "", plain)
    return len(re.sub(r"\s", "", plain))

"""报告渲染(report.md)+ 过程记录(process.json)+ 任务状态文件的落盘。"""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import WEEK08_DIR, settings

if TYPE_CHECKING:
    from app.graph.state import ResearchState

REPORTS_DIR = WEEK08_DIR / "reports"

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def source_index(state: "ResearchState") -> dict[str, int]:
    """来源编号:url → [n](按 findings 首次出现顺序,渲染与角标共用)。"""
    index: dict[str, int] = {}
    for f in state.get("findings", []):
        url = f.get("url", "")
        if url and url not in index:
            index[url] = len(index) + 1
    return index


def latest_info_date(state: "ResearchState") -> str:
    """信息最新截至:来源最新发布日期;均无日期时取检索日期(当天)。"""
    dates = [
        m.group(0)
        for meta in state.get("sources", {}).values()
        if (m := _DATE_RE.search(meta.get("date_published", "")))
    ]
    return max(dates) if dates else datetime.now().strftime("%Y-%m-%d")


def render_report(state: "ResearchState", body_md: str) -> str:
    """组装完整报告:头部信息行 + LLM 正文 + 程序渲染的来源列表与置信度说明。"""
    topic = state["topic"]
    rounds = len(state.get("rounds", []))
    index = source_index(state)
    latest = latest_info_date(state)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"# {topic} 研究报告",
        "",
        f"> 生成时间:{now} | 迭代 {rounds} 轮 | 引用 {len(index)} 个来源 | 信息最新截至 {latest}",
        "",
    ]
    if state.get("degraded"):
        lines += [
            "> ⚠️ **不完整报告**:研究过程部分环节异常降级,本报告基于已有发现生成,信息覆盖可能不全。",
            "",
        ]
    lines += [body_md.strip(), ""]

    # 来源列表
    sources = state.get("sources", {})
    lines += ["## 来源列表", ""]
    for url, n in index.items():
        meta = sources.get(url, {})
        mark = "(基于摘要)" if meta.get("from_summary") else ""
        lines += [
            f"- [{n}] {meta.get('title', '(无标题)')} {mark}",
            f"  - URL:{url}",
        ]
        if meta.get("summary"):
            lines.append(f"  - 摘要:{meta['summary']}")
    lines.append("")

    # 置信度说明
    lines += [
        "## 置信度说明",
        "",
        "- 带 [n] 角标的结论均可溯源:抽取时保留了来源原文摘录(quote)作为佐证;",
        "- 标注「(模型推断)」的论断无来源支撑,系模型推理,请注意甄别;",
        f"- 信息最新截至 {latest}:取所有来源中最新的发布日期,来源无日期时以检索日期为准;",
        "- 本报告由 LLM 生成并自动综合,可能存在错误,重要决策请点击来源核对原文。",
        "",
    ]
    return "\n".join(lines)


def build_process(state: "ResearchState", status: str) -> dict:
    """过程记录:检索了什么、读了什么、迭代几轮。"""
    rounds = state.get("rounds", [])
    return {
        "task_id": state.get("task_id", ""),
        "topic": state.get("topic", ""),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "plan": state.get("plan", []),
        "rounds": rounds,
        "stats": {
            "searches": state.get("search_count", 0),
            "pages_read": sum(len(r.get("read_urls", [])) for r in rounds),
            "rounds": len(rounds),
        },
        "sources": state.get("sources", {}),
        "model": settings.base_model,
        "status": status,
    }


def _task_dir(task_id: str) -> Path:
    return REPORTS_DIR / task_id


def save_outputs(state: "ResearchState", report_md: str, status: str) -> Path:
    """report.md + process.json 写入 reports/{task_id}/。"""
    d = _task_dir(state["task_id"])
    d.mkdir(parents=True, exist_ok=True)
    (d / "report.md").write_text(report_md, encoding="utf-8")
    (d / "process.json").write_text(
        json.dumps(build_process(state, status), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return d


def write_status(task_id: str, status_obj: dict) -> None:
    """任务状态文件(生命周期标记:running/terminal),供取消与惰性恢复使用。"""
    d = _task_dir(task_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "status.json").write_text(
        json.dumps(status_obj, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_status(task_id: str) -> dict | None:
    p = _task_dir(task_id) / "status.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

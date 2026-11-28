"""无头运行器：在会话内启动一个干净的子会话执行任务，并把结果归入新的运行目录。

子会话的启动与会话记录的查找是两处外部边界，收在 HeadlessBackend 里，测试时换成替身；
其余步骤（拼提示词、把子会话输出转成运行记录、数搜索次数）都是确定性的。
"""

from __future__ import annotations

import calendar
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from esgtools.contract import (
    DATA_FILE,
    REPORT_FILE,
    RUN_RECORD_FILE,
    SEEN_SNAPSHOT_FILE,
    Case,
    Mode,
    Version,
    as_dict,
    mode_mismatch_message,
)

TOOLS_DIR = Path(__file__).resolve().parents[1]
"""脚本目录（作业二/scripts）：``python -m esgtools`` 须在这里执行。"""

WEEK16_DIR = TOOLS_DIR.parents[1]
"""子会话的工作目录：规格规定官方运行以 week16 为工作目录。"""

DEFAULT_ALLOWED_TOOLS = (
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "Skill",
    "WebSearch",
    "Agent",
    "mcp__web-search-prime",
    "mcp__web-reader",
)
"""默认的工具白名单：读写文件、加载 skill、内置网页搜索与子代理，加智谱的搜索与读页。

MCP 工具按服务器名整台放行（`mcp__web-search-prime` 即该服务器的全部工具），比写具体工具名稳妥。
内置网页搜索与子代理是规格允许的补充手段（「内置网页搜索仅作补充」「如用子代理分担检索，并发不超过 3」），
不放进来，说明文里写了也一用就被拒。不在名单里的工具子会话用不了——前提是权限模式为 dontAsk，见下。
"""

MEMORY_DIR_DENY = "Read(~/.claude/projects/*/memory/**)"
"""禁读各项目的记忆目录。

子会话与主会话共用记忆目录，读了会把设计背景带进报告。只拦 memory 子目录，不拦整个 projects 目录：
子会话有时要读自己的会话记录（大网页的内容在工具结果里）。
"""

SCRATCH_DIR_DENY = f"Read(//{str(WEEK16_DIR / '.scratch').lstrip('/')}/**)"
"""禁读规格与工单所在的 `.scratch/`：里面写着质量线和实施者的迭代笔记，子会话读了等于看了答案。

按路径拒绝要写成 `//` 前缀的绝对路径，裸绝对路径不生效；`Read` 的拒绝规则会一并拦住相对路径、Grep 与 Glob
（2026-11-26 探针实测）。拒绝规则优先于放行规则。
"""

DEFAULT_DENIED_TOOLS = ("WebFetch", MEMORY_DIR_DENY, SCRATCH_DIR_DENY)
"""默认禁用的工具与路径：内置网页抓取（规格写明它对中国域名不可用）、记忆目录、规格与工单。"""


class PermissionMode(StrEnum):
    """运行器允许的权限模式；全放行的 bypassPermissions 与 auto 不在其中。"""

    DONT_ASK = "dontAsk"
    """不询问，白名单外的工具一律拒绝。"""

    DEFAULT = "default"
    """本机的常规模式（无头运行下表现为需要权限的调用被拒）。"""


DEFAULT_PERMISSION_MODE = PermissionMode.DONT_ASK
"""默认权限模式。

不能沿用本机默认：本机设的是 auto 模式，由分类器放行「安全」的命令，白名单外的 Bash 照样能跑
（2026-11-26 对照运行实测），白名单就名存实亡了。dontAsk 下只读的 `ls` 一类命令仍被内置豁免。
"""

SESSION_OUTPUT_FILE = "session_output.json"
"""子会话 JSON 输出的原件，留在运行目录里供核对运行记录。"""

FAILED_OUTPUT_FILE = "session_output.txt"
"""子会话输出不是 JSON 时，把原始 stdout / stderr 留在这里。"""

_TIMEOUT_RETURN_CODE = 124
_LAUNCH_FAILED_RETURN_CODE = 127


@dataclass(frozen=True)
class ProcessResult:
    """一次子进程调用的结果。"""

    returncode: int
    stdout: str
    stderr: str


class HeadlessBackend(Protocol):
    """运行器依赖的外部边界：启动哪个程序、怎么等它结束、去哪里找会话记录。"""

    claude_bin: str
    """要启动的程序，命令行的第一项。"""

    def launch(
        self, command: list[str], *, cwd: Path, env: dict[str, str], timeout: float | None
    ) -> ProcessResult:
        """启动子进程并等它结束。"""
        ...

    def find_session_log(self, session_id: str) -> Path | None:
        """按会话 ID 找到子会话的记录文件；找不到返回 None。"""
        ...


class LocalClaudeCli:
    """本机的 claude 命令行。会话记录在 ~/.claude/projects/<项目>/<session_id>.jsonl。"""

    claude_bin: str

    def __init__(self, claude_bin: str = "claude", projects_dir: Path | None = None) -> None:
        self.claude_bin = claude_bin
        self.projects_dir = projects_dir if projects_dir is not None else Path.home() / ".claude" / "projects"

    def launch(
        self, command: list[str], *, cwd: Path, env: dict[str, str], timeout: float | None
    ) -> ProcessResult:
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return ProcessResult(
                _TIMEOUT_RETURN_CODE, _as_text(exc.stdout), f"子会话超过 {timeout:g} 秒未结束，已终止"
            )
        except OSError as exc:
            return ProcessResult(_LAUNCH_FAILED_RETURN_CODE, "", f"无法启动 {command[0]}：{exc}")
        return ProcessResult(completed.returncode, completed.stdout, completed.stderr)

    def find_session_log(self, session_id: str) -> Path | None:
        if re.fullmatch(r"[0-9a-fA-F-]{36}", session_id) is None:
            return None
        return next(iter(sorted(self.projects_dir.glob(f"*/{session_id}.jsonl"))), None)


def _as_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


# ---- 运行规格 ----


@dataclass(frozen=True)
class RunSpec:
    """一次无头运行的输入：跑什么、以什么权限跑、时间窗是哪段。"""

    case: Case
    mode: Mode
    version: Version
    skill_version: str
    task: str
    """交给子会话的一句话任务。"""

    window_start: date
    window_end: date
    client: str | None = None
    industry: str | None = None
    allowed_tools: tuple[str, ...] = DEFAULT_ALLOWED_TOOLS
    denied_tools: tuple[str, ...] = DEFAULT_DENIED_TOOLS
    permission_mode: PermissionMode = DEFAULT_PERMISSION_MODE
    model: str | None = None
    timeout_seconds: float = 3600.0

    def __post_init__(self) -> None:
        """启动之前先挡住不成立的输入：案例与运行模式对不上、时间窗自相矛盾、权限模式全放行，都不该启动子会话。"""
        if message := mode_mismatch_message(self.case, self.mode):
            raise ValueError(message)
        if self.window_start > self.window_end:
            raise ValueError(f"时间窗起始日期 {self.window_start} 晚于结束日期 {self.window_end}")
        if not isinstance(self.permission_mode, PermissionMode):
            names = " / ".join(mode.value for mode in PermissionMode)
            raise ValueError(f"权限模式须为 {names} 之一，收到 {self.permission_mode!r}；不允许全放行")


@dataclass
class RunOutcome:
    """一次无头运行的结果。"""

    run_dir: Path
    record: dict[str, Any] | None
    """写进 run.json 的运行记录；子会话没给出可用输出时为 None。"""

    ok: bool
    problems: list[str]
    """导致这次运行不成立的问题。"""

    warnings: list[str]
    """不影响成立、但使用者应当知道的事。"""


def default_run_name(case: Case, version: Version, mode: Mode, now: datetime) -> str:
    """默认的运行目录名：开始时间、案例、版本，招投标情报再带运行模式。"""
    name = f"{now:%Y%m%d-%H%M%S}_{case.value}_{version.value}"
    return f"{name}_{mode.value}" if case is Case.BID_RADAR else name


def build_prompt(spec: RunSpec, run_dir: Path) -> str:
    """交给子会话的完整提示词：使用者的一句话任务，加上产物落点与运行参数。"""
    lines = [
        spec.task,
        "",
        "【本次运行约定】",
        f"运行目录：{run_dir}",
        f"请把报告正文写入 {run_dir / REPORT_FILE}，把结构化数据写入 {run_dir / DATA_FILE}。",
        "运行记录 run.json 由运行器生成，不要自己写。",
        f"案例：{spec.case.value}",
        f"运行模式：{spec.mode.value}",
        f"版本：{spec.version.value}",
        f"客户：{spec.client or '（不适用）'}",
        f"行业：{spec.industry or '（不适用）'}",
        f"时间窗：{spec.window_start.isoformat()} 至 {spec.window_end.isoformat()}",
        "报告开头的声明须按上面的客户、行业、时间窗原样写明。",
    ]
    if spec.mode is Mode.MONITOR:
        lines += [
            f"监控模式：时间窗的起始日 {spec.window_start.isoformat()} 是基线，"
            "只保留发布日期严格晚于基线的招标公告。",
            f"开始检索之前，先把当前的已见清单原样复制为 {run_dir / SEEN_SNAPSHOT_FILE}"
            "（运行前快照），验收器据此判定去重。",
        ]
    return "\n".join(lines)


def run_headless(
    spec: RunSpec,
    backend: HeadlessBackend,
    *,
    workdir: Path,
    out_root: Path,
    now: datetime,
    run_id: str | None = None,
) -> RunOutcome:
    """启动子会话执行 ``spec.task``，把它的输出转成运行记录，连同产物归入新的运行目录。

    ``workdir`` 是子会话的工作目录（week16）；``now`` 是这次运行的开始时间。
    运行目录先建后跑：启动失败或子会话没写产物时目录会留着，便于事后查看，重跑须换 ``run_id`` 或删掉它。
    """
    name = run_id or default_run_name(spec.case, spec.version, spec.mode, now)
    run_dir = out_root / name
    if run_dir.exists():
        return RunOutcome(run_dir, None, False, [f"运行目录已存在，不覆盖：{run_dir}"], [])
    run_dir.mkdir(parents=True)

    command = [backend.claude_bin, "-p", build_prompt(spec, run_dir), "--output-format", "json"]
    command += ["--permission-mode", spec.permission_mode]
    command += ["--allowedTools", ",".join(spec.allowed_tools)]
    if spec.denied_tools:
        command += ["--disallowedTools", ",".join(spec.denied_tools)]
    if spec.model:
        command += ["--model", spec.model]
    # 嵌套在 Claude Code 会话里启动时，CLAUDECODE 环境变量会让子会话被拦，须去掉。
    env = {key: value for key, value in os.environ.items() if key != "CLAUDECODE"}
    # 关掉子会话的自动记忆：它与主会话共用记忆目录，不关会把自己的运行笔记写进主会话的进度记录。
    env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    result = backend.launch(command, cwd=workdir, env=env, timeout=spec.timeout_seconds)

    raw = _parse_json_object(result.stdout)
    if raw is None:
        (run_dir / FAILED_OUTPUT_FILE).write_text(
            f"[returncode]\n{result.returncode}\n\n[stdout]\n{result.stdout}\n\n[stderr]\n{result.stderr}",
            encoding="utf-8",
        )
        return RunOutcome(
            run_dir,
            None,
            False,
            [f"子会话的输出不是 JSON（退出码 {result.returncode}），原始输出见 {FAILED_OUTPUT_FILE}"],
            [],
        )
    (run_dir / SESSION_OUTPUT_FILE).write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    problems: list[str] = []
    warnings: list[str] = []
    if result.returncode != 0:
        problems.append(f"子会话退出码 {result.returncode}（{raw.get('subtype', '无 subtype')}）")
    if raw.get("is_error"):
        problems.append(f"子会话报告出错：{raw.get('subtype', '未说明原因')}")
    if denials := _as_list(raw.get("permission_denials")):
        names = sorted({str(as_dict(item).get("tool_name") or "?") for item in denials})
        warnings.append(f"子会话有 {len(denials)} 次工具调用被权限拒绝（不在白名单里）：{'、'.join(names)}")

    session_id = str(raw.get("session_id") or "")
    log = backend.find_session_log(session_id) if session_id else None
    if log is None:
        warnings.append(f"未找到会话记录（session_id={session_id or '无'}），搜索次数记为 null")
        search_count = None
    else:
        search_count = count_searches(log)

    record = build_record(spec, name, now, raw, search_count)
    (run_dir / RUN_RECORD_FILE).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    # 产物缺不缺由验收器判定（它是唯一说了算的程序）；运行器只在这里提醒一句，省得白跑一趟验收。
    if unwritten := [name for name in (REPORT_FILE, DATA_FILE) if not (run_dir / name).is_file()]:
        warnings.append(f"子会话没有写出 {'、'.join(unwritten)}，验收时 artifacts 规则不会通过")
    return RunOutcome(run_dir, record, not problems, problems, warnings)


def build_record(
    spec: RunSpec, run_id: str, now: datetime, output: dict[str, Any], search_count: int | None
) -> dict[str, Any]:
    """把子会话的 JSON 输出与运行规格合成运行记录。

    输入 token 取提示词总量：未命中缓存 + 写入缓存 + 读取缓存三段之和；
    三段的原始数值另存在 ``usage`` 里，可与子会话输出逐项核对。
    """
    usage = as_dict(output.get("usage"))
    usage_keys = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
    return {
        "schema_version": 1,
        "run_id": run_id,
        "case": spec.case.value,
        "mode": spec.mode.value,
        "version": spec.version.value,
        "skill_version": spec.skill_version,
        "client": spec.client,
        "industry": spec.industry,
        "time_window": {"start": spec.window_start.isoformat(), "end": spec.window_end.isoformat()},
        "model": _model_of(output, spec.model),
        "started_at": now.isoformat(timespec="seconds"),
        "duration_ms": output.get("duration_ms"),
        "input_tokens": sum(_as_int(usage.get(key)) for key in usage_keys[:3]),
        "output_tokens": _as_int(usage.get("output_tokens")),
        "cost_usd": output.get("total_cost_usd"),
        "search_count": search_count,
        "invocation": "headless",
        "session_id": output.get("session_id"),
        "num_turns": output.get("num_turns"),
        "usage": {key: usage.get(key) for key in usage_keys},
    }


def _model_of(output: dict[str, Any], fallback: str | None) -> str:
    declared = output.get("model")
    if isinstance(declared, str) and declared:
        return declared
    used = output.get("modelUsage")
    if isinstance(used, dict) and used:
        return "、".join(str(name) for name in used)
    return fallback or "unknown"


def _as_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _parse_json_object(text: str) -> dict[str, Any] | None:
    """从子会话输出里取出 JSON 对象；输出前面可能夹着提示文字，所以从第一个花括号开始解析。"""
    start = text.find("{")
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text, start)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


# ---- 搜索次数 ----


def count_searches(log_path: Path) -> int:
    """会话记录里工具名含 search 的调用次数，子代理里的也算；读页、写文件不算。"""
    count = 0
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if as_dict(entry).get("type") != "assistant":
            continue
        content = as_dict(as_dict(entry).get("message")).get("content")
        if not isinstance(content, list):
            continue
        count += sum(
            1
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "tool_use"
            and "search" in str(block.get("name", "")).lower()
        )
    return count


# ---- 时间窗 ----


def window_from(
    *,
    today: date,
    start: date | None = None,
    end: date | None = None,
    days: int | None = None,
    months: int | None = None,
) -> tuple[date, date]:
    """定时间窗。

    给了起始日期就用它（没给结束日期时取今天）；否则到今天为止往前取 ``days`` 天（含今天）
    或 ``months`` 个月。只给结束日期不行。
    """
    if start is not None:
        return start, end if end is not None else today
    if end is not None:
        raise ValueError("给了结束日期 --end 就须同时给起始日期 --start")
    if days is not None:
        if days < 1:
            raise ValueError(f"天数 --days 须为正数，收到 {days}")
        return today - timedelta(days=days - 1), today
    if months is not None:
        if months < 1:
            raise ValueError(f"月数 --months 须为正数，收到 {months}")
        return _shift_months(today, months), today
    raise ValueError("须给出起始日期（--start）、天数（--days）或月数（--months）之一")


def _shift_months(day: date, months: int) -> date:
    """``day`` 往前推 ``months`` 个月；落在不存在的日子上就取当月最后一天。"""
    year, month_index = divmod(day.year * 12 + day.month - 1 - months, 12)
    month = month_index + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))

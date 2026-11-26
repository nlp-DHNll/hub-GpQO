"""把 agent 写好的正文与来源清单合成最终报告，并转成带样式的 HTML。

正文里不要写来源附录：这里会按 sources.jsonl 自动生成，保证附录与引用一一对应。

用法：
  python render.py --body body.md --sources sources.jsonl --out report.md --html report.html
                 [--title "中国神华 ESG 月度动态报告"] [--stats stats.json] [--generated-by esg-monthly-report]
"""
from __future__ import annotations

import argparse
import base64
import html as html_lib
import json
import mimetypes
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

LABELS = {
    "records": "中标记录数", "with_amount": "其中披露金额的条数", "amount_total": "金额合计（万元）",
    "amount_mean": "金额均值（万元）", "amount_median": "金额中位数（万元）", "amount_max": "最大单笔（万元）",
    "tender_records": "进行中的招标记录数", "new_tender": "新增招标", "new_award": "新增中标",
}

CSS = """
body{margin:0;background:#f4f6f8;color:#1f2933;font-family:"Microsoft YaHei","PingFang SC","Noto Sans CJK SC",sans-serif;line-height:1.75}
main{max-width:960px;margin:0 auto;padding:40px 48px 56px;background:#fff;box-shadow:0 0 12px rgba(0,0,0,.06)}
h1{font-size:26px;color:#1f3a5f;border-bottom:2px solid #1f3a5f;padding-bottom:10px;margin:0 0 6px}
h2{font-size:19px;color:#1f3a5f;margin:34px 0 10px;padding-left:10px;border-left:4px solid #2f6fa9}
h3{font-size:16px;color:#2f6f55;margin:22px 0 8px}
p{margin:8px 0}
blockquote{margin:14px 0;padding:12px 16px;background:#eef4fb;border-left:4px solid #2f6fa9;color:#1f3a5f}
table{border-collapse:collapse;width:100%;margin:10px 0 16px;font-size:13.5px}
th,td{border:1px solid #d5dbe1;padding:6px 9px;vertical-align:top;text-align:left}
th{background:#eef2f6;color:#1f3a5f;font-weight:600}
tr:nth-child(even) td{background:#fafbfc}
code{background:#f1f3f5;padding:1px 5px;border-radius:3px;font-size:13px}
pre code{display:block;padding:12px;overflow:auto}
img{max-width:100%;display:block;margin:12px auto}
a{color:#2f6fa9;text-decoration:none}
a:hover{text-decoration:underline}
hr{border:0;border-top:1px solid #d5dbe1;margin:28px 0}
.meta{color:#616e7c;font-size:13.5px}
"""


def cell(value) -> str:
    return (str(value or "")).replace("|", "／").replace("\n", " ").strip() or "—"


def appendix(sources: list[dict], stats: dict | None, generated_by: str) -> str:
    lines = ["## 附录", "", "### A. 信息来源", "",
             "| 编号 | 标题 | 发布机构 | 发布日期 | 链接 |", "|---|---|---|---|---|"]
    for s in sorted(sources, key=lambda x: int(re.sub(r"\D", "", x.get("id") or "0") or 0)):
        lines.append(f"| {cell(s.get('id'))} | {cell(s.get('title'))} | {cell(s.get('publisher'))} | "
                     f"{cell(s.get('published'))} | [打开]({s.get('url', '')}) |")
    if stats:
        lines += ["", "### B. 数据核对表", "",
                  "下表由脚本基于结构化数据计算，正文引用的统计数字应与此一致。", "", "| 指标 | 数值 |", "|---|---|"]
        for k, v in stats.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            num = f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else f"{v:,}"
            lines.append(f"| {LABELS.get(k, k)} | {num} |")
    lines += ["", f"生成信息：{generated_by or 'skill'} 生成于 {date.today().isoformat()}；来源 {len(sources)} 条；"
                  "报告由自动检索生成，用于决策前需人工复核。", ""]
    return "\n".join(lines)


def to_html(md_text: str, title: str, base_dir: Path, out: Path) -> None:
    import markdown
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists", "attr_list"])

    def embed(m: re.Match) -> str:
        src = m.group(1)
        if src.startswith(("http://", "https://", "data:")):
            return m.group(0)
        p = (base_dir / src).resolve()
        if p.is_file():
            mime = mimetypes.guess_type(p.name)[0] or "image/png"
            return f'src="data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"'
        return m.group(0)

    body = re.sub(r'src="([^"]+)"', embed, body)
    doc = (f"<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
           f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
           f"<title>{html_lib.escape(title)}</title><style>{CSS}</style></head>"
           f"<body><main>{body}</main></body></html>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")


def main() -> int:
    c.init()
    ap = argparse.ArgumentParser(description="合成最终报告并转成 HTML")
    ap.add_argument("--body", required=True, help="agent 写好的正文 Markdown")
    ap.add_argument("--sources", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--html", dest="html_out", help="同时输出的 HTML 文件")
    ap.add_argument("--title", default="报告")
    ap.add_argument("--stats", help="stats.py 输出的统计 JSON，给出时附上数据核对表")
    ap.add_argument("--generated-by", default="")
    args = ap.parse_args()

    body = Path(args.body).read_text(encoding="utf-8-sig").rstrip() + "\n"
    sources = c.read_jsonl(args.sources)
    stats = json.loads(Path(args.stats).read_text(encoding="utf-8")) if args.stats else None
    if re.search(r"^#{1,3}\s*附录", body, re.M):
        print("[render] 正文已含附录，未重复追加")
        report = body
    else:
        report = body + "\n" + appendix(sources, stats, args.generated_by)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    note = ""
    if args.html_out:
        to_html(report, args.title, out.parent.resolve(), Path(args.html_out))
        note = f"，HTML={args.html_out}"
    print(f"[render] 来源 {len(sources)} 条，报告={args.out}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(c.guard("render", main))

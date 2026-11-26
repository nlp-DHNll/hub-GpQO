"""盲评两份报告：去掉版本标识后交给大模型，按固定维度打分，用于"有 script 对比没有 script"的对比实验。

评审看不到报告的附录和生成方式说明；A、B 的先后顺序每轮互换，避免位置偏差。

用法：
  python judge.py --a <报告A.md> --b <报告B.md> --out judge.json [--repeat 2]
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent / "esg-monthly-report" / "scripts"))
import common as c  # noqa: E402

DIMENSIONS = ("结构完整性", "事实可追溯", "分析深度", "建议可操作性", "数据准确性", "可读性")
SYSTEM = ("你是一位严格的行业评审，负责给报告打分。只依据给出的材料，不猜测报告的生成方法，不补充材料以外的事实。"
          "只输出一个 JSON 对象。")
SPEC = """输出一个 JSON 对象：
{"A": {"结构完整性": 分数, "事实可追溯": 分数, "分析深度": 分数, "建议可操作性": 分数, "数据准确性": 分数, "可读性": 分数},
 "B": {同样六个维度},
 "A的理由": {"维度": "一句话"},
 "B的理由": {"维度": "一句话"}}
分数是 1 到 5 的整数，可以为半分留空，不要小数。各维度的含义：
- 结构完整性：该有的部分是否齐全，是否有空泛或缺失的章节
- 事实可追溯：事实是否带来源，来源是否具体
- 分析深度：是否说清了"为什么"和"意味着什么"，而不是罗列
- 建议可操作性：建议是否有责任方、时间、具体动作
- 数据准确性：数字前后是否一致，统计口径是否说清，样本局限是否交代
- 可读性：结论是否先行，表格和段落是否清楚"""


class Scores(BaseModel):
    A: dict[str, int]
    B: dict[str, int]


def strip(text: str) -> str:
    m = re.search(r"^#{1,3}\s*附录", text, re.M)
    return text[: m.start()].rstrip() if m else text.rstrip()


def main() -> int:
    c.init()
    ap = argparse.ArgumentParser(description="盲评两份报告")
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--topic", default="同一客户、同一时间窗的 ESG 月报", help="一句话说明两份报告的主题，供评审理解")
    args = ap.parse_args()
    if not c.llm_configured():
        sys.exit("未配置 DEEPSEEK_API_KEY：在 .env 里填写后重试")

    a, b = strip(Path(args.a).read_text(encoding="utf-8-sig")), strip(Path(args.b).read_text(encoding="utf-8-sig"))
    runs = []
    for i in range(args.repeat):
        first, second, swapped = (b, a, True) if i % 2 else (a, b, False)
        user = (f"下面是两份关于{args.topic}的报告，正文部分如下。\n\n【报告 A】\n{first}\n\n【报告 B】\n{second}\n\n"
                f"请按六个维度给两份报告打分。")
        obj, usage = c.llm_json(SYSTEM + "\n" + SPEC, user, Scores)
        left, right = (obj.B, obj.A) if swapped else (obj.A, obj.B)
        runs.append({"A": left, "B": right, "usage": usage})
        print(f"[judge] 第 {i + 1} 轮：A={sum(left.values())} 分，B={sum(right.values())} 分")

    def avg(side: str) -> dict[str, float]:
        return {d: round(sum(r[side].get(d, 0) for r in runs) / len(runs), 2) for d in DIMENSIONS}

    result = {"A": str(args.a), "B": str(args.b), "repeat": args.repeat, "runs": runs, "average": {"A": avg("A"), "B": avg("B")}}
    import json
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[judge] 均分  A：" + "，".join(f"{d} {v}" for d, v in result["average"]["A"].items()))
    print("[judge] 均分  B：" + "，".join(f"{d} {v}" for d, v in result["average"]["B"].items()))
    print(f"[judge] 输出={args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(c.guard("judge", main))

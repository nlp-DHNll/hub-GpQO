"""招投标统计：对 bids.jsonl 里判定为 ESG 的记录做聚合并画图。数字由代码算，报告只引用这里的结果。

用法：
  python stats.py --in bids.jsonl --out stats.json --charts-dir charts
"""
from __future__ import annotations

import argparse
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

BUCKETS = (("10 万以下", 0, 10), ("10–50 万", 10, 50), ("50–100 万", 50, 100),
           ("100–500 万", 100, 500), ("500 万以上", 500, float("inf")))
FONT = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "PingFang SC", "Arial Unicode MS"]


def quarter(day: str) -> str:
    try:
        y, m = day.split("-")[:2]
        return f"{y}Q{(int(m) - 1) // 3 + 1}"
    except (ValueError, AttributeError):
        return "日期未知"


def bucket(amount: float) -> str:
    return next(name for name, low, high in BUCKETS if low <= amount < high)


def compute(rows: list[dict]) -> dict:
    cards = [r["card"] for r in rows if r.get("card") and r["card"].get("is_esg")]
    award = [k for k in cards if k["notice_type"] == "award"]
    tender = [k for k in cards if k["notice_type"] == "tender"]
    amounts = [k["amount_wan"] for k in award if k.get("amount_wan")]
    by_quarter: dict[str, dict] = defaultdict(lambda: {"count": 0, "amount_total": 0.0})
    by_type: dict[str, dict] = defaultdict(lambda: {"count": 0, "with_amount": 0, "amount_total": 0.0,
                                                   "amount_min": None, "amount_max": None})
    for k in award:
        q = by_quarter[quarter(k.get("notice_date") or "")]
        t = by_type[k.get("project_type") or "其他"]
        a = k.get("amount_wan")
        for group in (q, t):
            group["count"] += 1
            group["amount_total"] += a or 0
        if a:
            t["with_amount"] += 1
            t["amount_min"] = a if t["amount_min"] is None else min(t["amount_min"], a)
            t["amount_max"] = a if t["amount_max"] is None else max(t["amount_max"], a)
    biggest = max((k for k in award if k.get("amount_wan")), key=lambda k: k["amount_wan"], default=None)
    rank = lambda d: [{"name": n, "count": v} for n, v in Counter(d).most_common(10)]
    return {
        "records": len(award), "with_amount": len(amounts),
        "amount_total": round(sum(amounts), 2),
        "amount_mean": round(statistics.fmean(amounts), 2) if amounts else 0,
        "amount_median": round(statistics.median(amounts), 2) if amounts else 0,
        "amount_max": biggest["amount_wan"] if biggest else 0,
        "amount_max_project": biggest.get("project", "") if biggest else "",
        "tender_records": len(tender),
        "by_quarter": dict(sorted(by_quarter.items())),
        "by_bucket": {name: sum(1 for a in amounts if low <= a < high) for name, low, high in BUCKETS},
        "by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1]["count"])),
        "by_province": rank(k["province"] for k in award if k.get("province")),
        "by_purchaser_type": rank(k["purchaser_type"] for k in award),
        "top_winners": rank(k["winner"] for k in award if k.get("winner")),
    }


def chart(path: Path, labels: list[str], values: list[float], title: str, horizontal: bool = False) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = FONT
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(8, 4.2))
    pos = range(len(values))
    if horizontal:
        ax.barh(list(pos), values, color="#2f6fa9")
        ax.set_yticks(list(pos), labels)
        ax.invert_yaxis()
        for i, v in enumerate(values):
            ax.text(v, i, f" {v:g}", va="center", fontsize=9)
        ax.set_xlabel("条数")
    else:
        ax.bar(list(pos), values, color="#2f6fa9")
        ax.set_xticks(list(pos), labels, rotation=0 if len(labels) <= 8 else 35,
                      ha="center" if len(labels) <= 8 else "right")
        for i, v in enumerate(values):
            ax.text(i, v, f"{v:g}", ha="center", va="bottom", fontsize=9)
        ax.set_ylabel("条数")
    ax.set_title(title)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> int:
    c.init()
    ap = argparse.ArgumentParser(description="招投标统计与画图")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--charts-dir", help="给了就输出图表 PNG")
    args = ap.parse_args()

    stats = compute(c.read_jsonl(args.inp))
    charts = []
    if args.charts_dir:
        out = Path(args.charts_dir)
        if stats["by_quarter"]:
            labels = list(stats["by_quarter"])
            chart(out / "quarterly.png", labels, [stats["by_quarter"][k]["count"] for k in labels], "按季度的中标条数")
            charts.append("quarterly.png")
        if stats["records"]:
            labels = list(stats["by_bucket"])
            chart(out / "amount_buckets.png", labels, [stats["by_bucket"][k] for k in labels], "中标金额分布（按条数）")
            charts.append("amount_buckets.png")
            labels = list(stats["by_type"])
            chart(out / "project_types.png", labels, [stats["by_type"][k]["count"] for k in labels], "项目类型分布", True)
            charts.append("project_types.png")
            if stats["by_province"]:
                chart(out / "provinces.png", [p["name"] for p in stats["by_province"]],
                      [p["count"] for p in stats["by_province"]], "地域分布（前 10）", True)
                charts.append("provinces.png")
    stats["charts"] = charts
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    import json
    Path(args.out).write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[stats] ESG 项目里中标 {stats['records']} 条、招标中 {stats['tender_records']} 条；披露金额 {stats['with_amount']} 条，"
          f"合计 {stats['amount_total']:,.2f} 万元，中位数 {stats['amount_median']:,.2f} 万元；图表 {len(charts)} 张；输出={args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(c.guard("stats", main))

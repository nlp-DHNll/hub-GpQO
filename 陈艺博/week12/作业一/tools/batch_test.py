"""
批量识别 / 离线评测：把整个文件夹的图片跑一遍，输出 CSV 与分级统计。

    python tools/batch_test.py 图片目录
    python tools/batch_test.py 图片目录 --model qwen-vl-plus
    python tools/batch_test.py 图片目录 --mock          # 不调模型，只验证流程

输出：results/batch_<时间戳>.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import config as cfg  # noqa: E402
import llm  # noqa: E402

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="图片所在目录")
    ap.add_argument("--model", default=cfg.DEFAULT_MODEL)
    ap.add_argument("--mock", action="store_true", help="不调用模型，用演示数据跑通流程")
    ap.add_argument("--save", action="store_true", help="把压缩后的图片另存到 uploads/")
    args = ap.parse_args()

    folder = Path(args.folder)
    if not folder.exists():
        print(f"目录不存在：{folder}")
        return

    files = sorted(p for p in folder.rglob("*") if p.suffix.lower() in EXTS)
    if not files:
        print(f"{folder} 下没有找到图片")
        return

    print(f"共 {len(files)} 张图片，模型 = {args.model}{'（演示模式）' if args.mock else ''}\n")

    out_csv = cfg.RESULT_DIR / f"batch_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    counter: Counter = Counter()
    t_all = time.perf_counter()

    with out_csv.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["file", "risk_level", "risk_score", "scene", "hazards", "blocked_passage",
             "flammable_material", "confidence", "elapsed_ms", "evidence", "suggestion"]
        )

        for i, f in enumerate(files, 1):
            try:
                if args.mock:
                    r = llm.mock_result()
                else:
                    r = llm.analyze(f.read_bytes(), args.model)
                counter[r["risk_level"]] += 1
                hz = " / ".join(f"{h['name']}({h['category']})" for h in r["hazards"]) or "-"
                writer.writerow([
                    f.name, r["risk_level"], r["risk_score"], r["scene"], hz,
                    r["blocked_passage"], r["flammable_material"], r["confidence"],
                    r.get("meta", {}).get("elapsed_ms", ""), r["evidence"], r["suggestion"],
                ])
                print(f"[{i:>3}/{len(files)}] {r['risk_level']:<4} {r['risk_score']:>3}  {f.name}")
            except (llm.LLMError, llm.ImageError) as exc:
                writer.writerow([f.name, "ERROR", "", "", "", "", "", "", "", str(exc), ""])
                print(f"[{i:>3}/{len(files)}] ERROR  {f.name}  {exc}")

    cost = time.perf_counter() - t_all
    print("\n" + "-" * 46)
    for k in ["高风险", "中风险", "低风险", "无风险", "非楼道", "ERROR"]:
        if counter[k]:
            print(f"  {k}: {counter[k]} 张")
    print(f"  总耗时 {cost:.1f}s，平均 {cost / len(files):.2f}s/张")
    print(f"  结果已写入 {out_csv}")


if __name__ == "__main__":
    main()

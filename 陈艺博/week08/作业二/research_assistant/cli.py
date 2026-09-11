"""命令行入口。

用法：
    python -m research_assistant.cli "研究主题" [--rounds 3] [--count 5] [--questions 5]

未配置 key 时会自动进入桩/演示路径，仍可跑通并输出模板报告。
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="research_assistant",
        description="深度研究助手：输入主题，自动检索-迭代-综合，输出带来源的可追溯报告。")
    ap.add_argument("topic", help="研究主题")
    ap.add_argument("--rounds", type=int, default=3,
                    help="最多迭代检索轮数(1+)，默认 3")
    ap.add_argument("--count", type=int, default=5,
                    help="每轮检索返回条数，默认 5")
    ap.add_argument("--questions", type=int, default=5,
                    help="规划拆分子问题上限，默认 5")
    args = ap.parse_args(argv)

    from .agent import ResearchAgent
    from .report import render_full

    agent = ResearchAgent(max_rounds=max(1, args.rounds),
                          count_per_round=max(1, args.count),
                          question_limit=max(1, args.questions))
    llm = agent.llm  # ResearchAgent 已 from_env 构造
    searcher = agent.searcher

    try:
        if getattr(searcher, "is_stub", lambda: False)():
            print("⚠ 未配置 BOCHA_API_KEY —— 将不执行真实网页检索（桩模式）。", file=sys.stderr)
        if getattr(llm, "is_stub", lambda: False)():
            print("⚠ 未配置 DEEPSEEK_API_KEY —— 将进入演示桩报告（不进行真实推理）。", file=sys.stderr)

        print(f"\n开始深度研究：{args.topic} …\n")
        report = agent.run(args.topic)
        print("\n" + "=" * 20 + " 研究报告 " + "=" * 20 + "\n")
        print(render_full(report))
    except KeyboardInterrupt:
        print("\n已中止。", file=sys.stderr)
        return 1
    except Exception as e:  # 顶层兜底：任何内部异常以非零退出暴露
        print(f"运行出错：{type(e).__name__}: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

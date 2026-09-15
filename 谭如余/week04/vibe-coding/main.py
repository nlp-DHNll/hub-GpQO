"""CLI 入口

使用方式:
    python main.py             启动交互式问答
    python main.py --check     依赖自检
    python main.py --eval      在内置测试集上评估
    python main.py --query "iPhone 15 电池容量"    单条问答
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import List

from pipeline.qa_pipeline import QAPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("main")


BANNER = r"""
╔══════════════════════════════════════════════════════════════╗
║                  电商智能问答系统 v1.0                        ║
║        RAG + BM25 + Neo4j + BERT + DeepSeek                  ║
║                                                              ║
║   命令:                                                      ║
║     /check   依赖自检                                         ║
║     /reset   重置会话                                         ║
║     /eval    跑评估                                            ║
║     /quit    退出                                             ║
╚══════════════════════════════════════════════════════════════╝
"""


def build_pipeline() -> QAPipeline:
    try:
        return QAPipeline()
    except Exception as e:  # noqa: BLE001
        print(f"\n❌ 启动失败: {e}\n", file=sys.stderr)
        print("修复建议:", file=sys.stderr)
        print("  1) 启动 Neo4j: docker run -d -p 7687:7687 -p 7474:7474 -e NEO4J_AUTH=neo4j/password neo4j", file=sys.stderr)
        print("  2) 灌库: python scripts/init_neo4j.py", file=sys.stderr)
        print("  3) 设置 DEEPSEEK_API_KEY 环境变量", file=sys.stderr)
        sys.exit(1)


def cmd_check(pipe: QAPipeline) -> None:
    print("=" * 60)
    print("  依赖自检")
    print("=" * 60)
    for k, v in pipe.self_check().items():
        print(f"  {k:10s} {v}")
    print()


def cmd_repl(pipe: QAPipeline) -> None:
    print(BANNER)
    state = pipe.dm.new_session()
    while True:
        try:
            q = input("\n👤 您: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见!")
            break
        if not q:
            continue
        if q.startswith("/"):
            cmd = q.strip().lower()
            if cmd in ("/quit", "/exit", "/q"):
                print("👋 再见!")
                break
            if cmd == "/check":
                cmd_check(pipe)
                continue
            if cmd == "/reset":
                state = pipe.dm.new_session()
                print("🔄 会话已重置")
                continue
            if cmd == "/eval":
                cmd_eval(pipe)
                continue
            print("未知命令:", q)
            continue
        # 正常问答
        try:
            res = pipe.ask(q, session_state=state)
        except Exception as e:  # noqa: BLE001
            print(f"❌ 出错了: {e}")
            logger.exception("问答异常")
            continue
        print(f"\n🤖 小淘: {res.answer}")
        meta = f"  [意图={res.intent}  置信={res.confidence:.2f}  检索={len(res.sources)}条  {res.latency_ms}ms]"
        print(meta)


def cmd_single(pipe: QAPipeline, query: str) -> None:
    res = pipe.ask(query)
    print(f"\nQ: {query}")
    print(f"A: {res.answer}")
    print(f"  intent={res.intent} conf={res.confidence:.2f} {res.latency_ms}ms")
    if res.sources:
        print("  参考资料:")
        for s in res.sources[:3]:
            print(f"    · {s['head']} {s['relation']} {s['tail']}")


# ---------- 内置评估 ----------
EVAL_SET: List[dict] = [
    {"q": "iPhone 15 Pro 的电池容量多大？", "expected_intent": "query_product",
     "expect_in_answer": ["3274"]},
    {"q": "耐克 Air Max 的价格？", "expected_intent": "query_product",
     "expect_in_answer": ["899"]},
    {"q": "怎么退货？", "expected_intent": "after_sales",
     "expect_in_answer": ["退货"]},
    {"q": "运费多少？包邮吗？", "expected_intent": "policy_inquiry"},
    {"q": "我的快递到哪了？", "expected_intent": "logistics"},
    {"q": "你好", "expected_intent": "greeting"},
    {"q": "再见", "expected_intent": "goodbye"},
    {"q": "谢谢", "expected_intent": "thanks"},
    {"q": "MateBook 的续航多久？", "expected_intent": "query_product",
     "expect_in_answer": ["12"]},
    {"q": "AirPods Pro 续航多久？", "expected_intent": "query_product",
     "expect_in_answer": ["6"]},
]


def cmd_eval(pipe: QAPipeline) -> None:
    print("=" * 60)
    print(f"  评估 {len(EVAL_SET)} 条 query")
    print("=" * 60)
    correct_intent = 0
    correct_answer = 0
    for case in EVAL_SET:
        res = pipe.ask(case["q"])
        ok_intent = (res.intent == case.get("expected_intent", ""))
        if ok_intent:
            correct_intent += 1
        expect_kw = case.get("expect_in_answer", [])
        ok_answer = (not expect_kw) or all(kw in res.answer for kw in expect_kw)
        if ok_answer:
            correct_answer += 1
        flag = "✅" if (ok_intent and ok_answer) else "❌"
        print(f"  {flag} intent={res.intent:18}  Q: {case['q']}")
        if not ok_intent:
            print(f"      expected={case.get('expected_intent')}")
        if not ok_answer:
            print(f"      missing_kw={expect_kw}, got='{res.answer[:60]}...'")
    n = len(EVAL_SET)
    print("\n--- 评估结果 ---")
    print(f"  意图识别准确率: {correct_intent}/{n} = {correct_intent/n*100:.1f}%")
    print(f"  答案正确率:     {correct_answer}/{n} = {correct_answer/n*100:.1f}%")


# ---------- main ----------
def main():
    parser = argparse.ArgumentParser(description="电商智能问答系统 CLI")
    parser.add_argument("--check", action="store_true", help="依赖自检")
    parser.add_argument("--query", type=str, help="单条问答")
    parser.add_argument("--eval", action="store_true", help="跑内置评估")
    parser.add_argument("--quiet", action="store_true", help="减少日志输出")
    args = parser.parse_args()

    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    pipe = build_pipeline()

    if args.check:
        cmd_check(pipe)
    elif args.query:
        cmd_single(pipe, args.query)
    elif args.eval:
        cmd_eval(pipe)
    else:
        cmd_repl(pipe)


if __name__ == "__main__":
    main()
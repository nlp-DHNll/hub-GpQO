"""SQL Agent（LangChain 复刻版）命令行入口。

用法：
    python main.py "每个艺术家的专辑数量，按数量降序排前 10"
    python main.py            # 进入交互式问答循环
    python main.py --json "..."  # 输出完整 JSON（含 SQL / 证据 / 告警）

依赖：
    pip install -r requirements.txt
    export OPENAI_API_KEY=sk-xxx
    # 可选：export OPENAI_BASE_URL=...  SQL_AGENT_MODEL=...
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from workflow_lc import SQLAgentWorkflow

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _ask_once(question: str) -> int:
    workflow = SQLAgentWorkflow()
    result = workflow.run(question)
    return result, workflow


def main() -> int:
    parser = argparse.ArgumentParser(description="LangChain 版 SQL Agent")
    parser.add_argument("question", nargs="?", help="自然语言查询问题")
    parser.add_argument("--json", action="store_true", help="以 JSON 形式输出完整结果")
    args = parser.parse_args()

    if args.question:
        result, _ = _ask_once(args.question)
        if args.json:
            print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
        else:
            print("\n答案：", result.answer)
            if result.sql:
                print("SQL：", result.sql)
            if result.evidence:
                print("证据：", "; ".join(result.evidence))
            if result.caveats:
                print("注意：", "; ".join(result.caveats))
        return 0

    # 交互模式
    print("LangChain SQL Agent（输入空行或 exit 退出）")
    workflow = SQLAgentWorkflow()
    while True:
        try:
            question = input("\n问题> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question or question.lower() in {"exit", "quit"}:
            break
        result = workflow.run(question)
        print("\n答案：", result.answer)
        if result.sql:
            print("SQL：", result.sql)
        if result.caveats:
            print("注意：", "; ".join(result.caveats))
    return 0


if __name__ == "__main__":
    sys.exit(main())

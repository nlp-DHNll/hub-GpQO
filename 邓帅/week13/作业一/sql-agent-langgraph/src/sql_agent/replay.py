"""回放演示（课件 04_回放）：checkpoint 历史 + 从中间快照重放。

用法：PYTHONPATH=src python -m sql_agent.replay ["问题"]

流程：
1. 正常跑完一轮（AsyncSqliteSaver 记录每个 superstep 的快照）；
2. get_state_history 列出该 thread 的全部快照（倒序）；
3. 定位「generate 完成、即将进入修复子图」的快照；
4. ainvoke(None, 该快照 config) 从该点重放——repair / summarize 重跑。
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

from .checkpoint import open_checkpointer
from .config import settings
from .graph import SQLAgentGraph
from .logging_config import configure_logging
from .models import WorkflowOutput

DEFAULT_QUESTION = "销量最高的前三张专辑是什么？"


def _final_of(raw: Any) -> WorkflowOutput | None:
    if isinstance(raw, dict):
        return raw.get("final")
    return getattr(raw, "final", None)


async def main_async() -> None:
    question = " ".join(sys.argv[1:]).strip() or DEFAULT_QUESTION

    async with open_checkpointer() as checkpointer:
        graph = SQLAgentGraph(checkpointer=checkpointer)
        turn_input, config = await graph.prepare_turn(question)
        thread_id = str(config["configurable"]["thread_id"])

        print(f"[1] 正常运行：{question}")
        final = _final_of(await graph.app.ainvoke(turn_input, config=config))
        print(f"    答案：{final.answer if final else '（无输出）'}")
        print(f"    thread_id：{thread_id}")

        print("[2] checkpoint 历史（倒序，最新在前）：")
        history = [item async for item in graph.app.aget_state_history(config)]
        for snapshot in history:
            checkpoint_id = snapshot.config["configurable"].get("checkpoint_id")
            print(f"    next={snapshot.next}  checkpoint_id={checkpoint_id}")

        # generate 完成后的快照：下一步即将进入 repair 子图。
        target = next(
            (s for s in history if s.next and "repair" in tuple(s.next)), None
        )
        if target is None:
            print("（该轮没有走到 repair 之前的快照，演示结束。）")
            return
        target_id = target.config["configurable"].get("checkpoint_id")
        print(f"[3] 从「generate 之后」的 checkpoint 重放：{target_id}")
        replay_final = _final_of(await graph.app.ainvoke(None, config=target.config))
        print(f"    重放后答案：{replay_final.answer if replay_final else '（无输出）'}")
        print(
            "[4] 说明：重放从 checkpoint 恢复状态，generate 不重跑，\n"
            "    repair（校验/执行/修复子图）与 summarize 重新执行。"
        )


def main() -> None:
    configure_logging(os.getenv("SQL_AGENT_LOG_LEVEL", "INFO"))
    if not settings.api_key:
        print("缺少 API key（.env 中 API_KEY），回放需要真实调用 LLM。", file=sys.stderr)
        raise SystemExit(1)
    asyncio.run(main_async())


if __name__ == "__main__":
    main()

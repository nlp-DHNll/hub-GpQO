"""离线替身 Agent：不联网也能跑通整条编排。

用途：
1. 单元测试固定每个 Agent 的返回值，专测「状态机、重试预算、降级路径」；
2. ``demo_offline.py`` 在没有 API Key 的机器上演示整条链路。

它实现与 :class:`sql_agent_lc.llm.StructuredAgent` 相同的最小接口
（``name`` + ``async ainvoke(text) -> BaseModel``），所以可以直接替换。
"""

from __future__ import annotations

from collections import deque
from typing import Iterable

from pydantic import BaseModel


class ScriptedAgent:
    """按脚本依次返回预设结果，并记录每次收到的 prompt。"""

    def __init__(self, name: str, outputs: Iterable[BaseModel]) -> None:
        self.name = name
        self._queue: deque[BaseModel] = deque(outputs)
        self.calls: list[str] = []

    async def ainvoke(self, user_input: str) -> BaseModel:
        self.calls.append(user_input)
        if not self._queue:
            raise AssertionError(f"{self.name} 的脚本已用尽，但又被调用了一次")
        return self._queue.popleft()

    @property
    def remaining(self) -> int:
        return len(self._queue)


class ExplodingAgent:
    """永远抛错的 Agent：用来验证「汇总失败降级为表格」这条路径。"""

    def __init__(self, name: str = "ExplodingAgent") -> None:
        self.name = name
        self.calls: list[str] = []

    async def ainvoke(self, user_input: str) -> BaseModel:
        self.calls.append(user_input)
        raise RuntimeError(f"{self.name} 故意失败")

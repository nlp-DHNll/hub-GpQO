"""调用 .env 配置的模型输出结构化 JSON，并累计用量。"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

from openai import OpenAI

from . import config

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


@dataclass
class Usage:
    """模型的用量累计。"""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, input_tokens: int, output_tokens: int) -> None:
        with _LOCK:
            self.calls += 1
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens

    def as_dict(self) -> dict[str, Any]:
        with _LOCK:
            return asdict(self)


_LOCK = threading.Lock()
"""筛选阶段多线程调用模型，用量累计要加锁。"""


def parse_json(text: str) -> Any:
    """把模型输出解析成 JSON：先取代码围栏里的内容，再退而取第一个配平的对象或数组。"""
    stripped = text.strip()
    fenced = _FENCE.search(stripped)
    if fenced:
        stripped = fenced[1].strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    starts = [position for position in (stripped.find("{"), stripped.find("[")) if position >= 0]
    if not starts:
        raise ValueError("模型输出里没有 JSON")
    start = min(starts)
    closer = "}" if stripped[start] == "{" else "]"
    return json.loads(stripped[start : stripped.rfind(closer) + 1])


def resolve_model(client: OpenAI, name: str) -> str:
    """按大小写不敏感把配置里的模型名换成接口上的 id（.env 写的是 qwen3.8-Flash，接口上是 qwen3.8-flash）。"""
    try:
        return next(item.id for item in client.models.list().data if item.id.lower() == name.lower())
    except (StopIteration, Exception):
        return name


class LLM:
    """带重试的 JSON 调用。"""

    def __init__(self, model: str | None = None) -> None:
        self.client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
        self.model = resolve_model(self.client, model or config.LLM_MODEL)
        self.usage = Usage()

    def __enter__(self) -> LLM:
        return self

    def __exit__(self, *_: object) -> None:
        self.client.close()

    def json(self, instruction: str, payload: str, *, retries: int = 2) -> Any:
        """发一轮对话，返回解析后的 JSON；解析失败或接口报错时重试，仍失败则抛出最后一次的异常。"""
        failure: Exception | None = None
        for attempt in range(retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": instruction},
                        {"role": "user", "content": payload},
                    ],
                    temperature=0,
                    max_tokens=4096,
                    extra_body={"enable_thinking": False},  # 默认开着长思考：一次小调用也要一分钟、四千 token
                )
                usage = response.usage
                if usage is not None:
                    self.usage.add(usage.prompt_tokens or 0, usage.completion_tokens or 0)
                return parse_json(response.choices[0].message.content or "")
            except Exception as exc:  # 接口报错与解析失败都值得重试一次
                failure = exc
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
        assert failure is not None
        raise failure

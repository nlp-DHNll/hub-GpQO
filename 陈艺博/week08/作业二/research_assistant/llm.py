"""DeepSeek（OpenAI 兼容）轻封装。

提供自由文本 chat 与尽力 JSON 的 chat_json。未配置 key 时回落 NoLLM 桩，
保证演示/冒烟不联网不报错。
"""
from __future__ import annotations

import json
import time
from typing import Optional

from . import config


def _smart_retry_decode(text: str) -> Optional[dict]:
    """社区技巧：容忍模型输出里的 markdown 代码块首尾等噪音。"""
    cands = [text]
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        # 去掉开头的 ``` 行（可能带语言名）与结尾的 ``` 行
        body = "\n".join(lines[1:])
        if body.rstrip().endswith("```"):
            body = body[: body.rstrip().rfind("```")].rstrip()
        cands.append(body)
    t2 = cands[0].strip()
    if t2.startswith("```"):
        return _smart_retry_decode("\n".join(t2.splitlines()[1:]))
    for c in cands:
        try:
            return json.loads(c)
        except Exception:
            continue
    return None


class LLM:
    """DeepSeek 封装。"""

    max_retries = 3
    base_delay_s = 2.0

    def __init__(self, key: Optional[str] = None,
                 base_url: Optional[str] = None,
                 model: Optional[str] = None) -> None:
        # 延迟 import，避免未联网误装 openai 时 import 本模块即炸
        from openai import OpenAI

        self._client = OpenAI(
            api_key=key or config.ChatConfig.api_key(),
            base_url=base_url or config.ChatConfig.base_url,
        )
        self.model = model or config.ChatConfig.model
        self.last_error = ""

    @classmethod
    def from_env(cls):
        """无 DEEPSEEK_API_KEY 时返回可用的 NoLLM 桩。"""
        if not config.ChatConfig.api_key():
            return NoLLM()
        return cls()

    def _chat_once(self, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        return (resp.choices[0].message.content or "").strip()

    def chat(self, system: str, user: str) -> str:
        """自由文本对话；带指数退避重试；最终失败返回空串不抛错。"""
        last = ""
        for attempt in range(self.max_retries):
            try:
                return self._chat_once(system, user)
            except Exception as e:  # 网络/限流/解析
                last = f"{type(e).__name__}: {e}"
                if attempt < self.max_retries - 1:
                    time.sleep(self.base_delay_s * (2 ** attempt))
        self.last_error = last
        return ""

    def chat_json(self, system: str, user: str) -> Optional[dict]:
        """尽力返回 JSON dict；解析失败额外重试一次，最后给 None。"""
        out = self.chat(system, user)
        if not out:
            return None
        parsed = _smart_retry_decode(out)
        if parsed is None:
            time.sleep(self.base_delay_s)
            out2 = self.chat(system, user)
            if out2:
                parsed = _smart_retry_decode(out2)
        return parsed

    def is_stub(self) -> bool:
        return False


class NoLLM(LLM):
    """供未配 key / 测试用的桩：不联网，产出合理占位结果。"""

    def __init__(self) -> None:
        self._client = None
        self.model = config.ChatConfig.model
        self.last_error = "未配置 DEEPSEEK_API_KEY，使用 NoLLM 桩（不联网）"

    def chat(self, system: str, user: str) -> str:
        # 触发桩时总是返回占位结构化文本（尽量贴合 JSON 期望）
        return self._tag(system)

    @staticmethod
    def _tag(_system: str) -> str:
        return ("{" + json.dumps({
            "message": "NoLLM stub 占位：未配置 LLM，以下为演示内容，无真实联网推理。",
            "items": [{"text": "请配置 DEEPSEEK_API_KEY 后运行以获得真实报告。"}],
        }, ensure_ascii=False) + "}")

    def chat_json(self, system: str, user: str) -> Optional[dict]:
        return json.loads(self._tag(""))

    def is_stub(self) -> bool:
        return True

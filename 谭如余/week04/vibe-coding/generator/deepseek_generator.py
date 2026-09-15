"""DeepSeek 大模型生成器

调用 DeepSeek Chat API(OpenAI 兼容协议),使用官方 /chat/completions 端点。
必需配置 DEEPSEEK_API_KEY,否则抛错。
"""
from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

import requests

from config import DEEPSEEK_API_BASE, DEEPSEEK_API_KEY, DEEPSEEK_MODEL, SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class DeepSeekError(RuntimeError):
    """DeepSeek 调用错误"""


class DeepSeekGenerator:
    """DeepSeek 生成器"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 30,
    ):
        self.api_key = api_key or DEEPSEEK_API_KEY
        self.api_base = (api_base or DEEPSEEK_API_BASE).rstrip("/")
        self.model = model or DEEPSEEK_MODEL
        self.timeout = timeout
        self._verified = False

    def _ensure_key(self) -> None:
        if not self.api_key:
            raise DeepSeekError(
                "未配置 DeepSeek API Key。请设置环境变量 DEEPSEEK_API_KEY,"
                "或在 config.py 中直接填写 DEEPSEEK_API_KEY。"
            )
        if not self._verified:
            self._verify()

    def _verify(self) -> None:
        """快速验证 Key 是否可用(发一个最小请求)"""
        try:
            r = requests.post(
                f"{self.api_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                    "stream": False,
                },
                timeout=10,
            )
            if r.status_code == 401:
                raise DeepSeekError("DeepSeek API Key 无效(401)")
            if r.status_code >= 500:
                raise DeepSeekError(f"DeepSeek 服务异常({r.status_code})")
            self._verified = True
        except requests.RequestException as e:
            raise DeepSeekError(f"无法连接 DeepSeek: {e}") from e

    # ---------- 主接口 ----------
    def generate(
        self,
        user_query: str,
        retrieved_chunks: Optional[List[str]] = None,
        history: Optional[List[Dict[str, str]]] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.6,
        max_tokens: int = 800,
    ) -> str:
        """生成最终回答

        Args:
            user_query: 用户问题
            retrieved_chunks: 检索到的参考文本
            history: 历史对话 [{role, content}, ...]
            system_prompt: 自定义系统提示词
        """
        self._ensure_key()
        messages = self._build_messages(
            user_query, retrieved_chunks or [], history or [], system_prompt or SYSTEM_PROMPT
        )
        try:
            r = requests.post(
                f"{self.api_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": False,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise DeepSeekError(f"DeepSeek 请求失败: {e}") from e
        if r.status_code != 200:
            raise DeepSeekError(f"DeepSeek 返回 {r.status_code}: {r.text[:300]}")
        try:
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, json.JSONDecodeError) as e:
            raise DeepSeekError(f"DeepSeek 响应解析失败: {e}; body={r.text[:200]}") from e

    @staticmethod
    def _build_messages(
        user_query: str, retrieved: List[str], history: List[Dict[str, str]], sys_prompt: str
    ) -> List[Dict[str, str]]:
        """构造消息列表"""
        messages: List[Dict[str, str]] = [{"role": "system", "content": sys_prompt}]
        # 检索到的内容作为 system 提示的一部分注入
        if retrieved:
            ctx = "\n".join(f"- {c}" for c in retrieved)
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "以下是检索到的【参考资料】,请基于这些信息回答用户问题。\n"
                        "如果资料中没有相关信息,请明确告知用户并建议联系人工客服。\n\n"
                        f"{ctx}"
                    ),
                }
            )
        # 历史(只保留 user/assistant 角色)
        for h in history[-10:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_query})
        return messages


def demo() -> None:
    gen = DeepSeekGenerator()
    try:
        ans = gen.generate(
            user_query="iPhone 15 Pro 的电池容量多大？",
            retrieved_chunks=[
                "苹果 iPhone 15 Pro 256GB 的电池容量是 3274mAh。",
                "iPhone 15 Pro 处理器为 A17 Pro,屏幕 6.1 英寸。",
            ],
        )
        print("回答:", ans)
    except DeepSeekError as e:
        print("DeepSeek 调用失败:", e)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    demo()
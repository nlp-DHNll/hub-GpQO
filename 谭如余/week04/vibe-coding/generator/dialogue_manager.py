"""对话管理模块(Dialogue Manager)

职责:
1) 维护对话状态(当前意图、已填充槽位、缺失槽位)
2) 缺槽时反问
3) 槽位齐全时返回策略标记(retrieval / template / chitchat)
4) 多轮上下文追踪
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from generator.nlu import NLUResult

logger = logging.getLogger(__name__)


class ActionType(str, Enum):
    RETRIEVE = "retrieve"     # 调用检索 + 生成器
    CLARIFY = "clarify"       # 缺槽反问
    CHITCHAT = "chitchat"     # 闲聊直接答
    TEMPLATE = "template"     # 用预设模板回答


@dataclass
class DialogueState:
    """单次会话状态"""
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    history: List[Dict[str, str]] = field(default_factory=list)  # [{role, content}, ...]
    current_intent: Optional[str] = None
    slots: Dict[str, str] = field(default_factory=dict)
    required_slots: List[str] = field(default_factory=list)
    missing_slots: List[str] = field(default_factory=list)
    context_entities: List[Dict[str, str]] = field(default_factory=list)
    turn_count: int = 0

    def push(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})
        if len(self.history) > 20:
            self.history = self.history[-20:]


@dataclass
class DialogueDecision:
    """对话管理决策结果"""
    action: ActionType
    question: Optional[str] = None   # 反问/回复内容
    needed_slots: Optional[List[str]] = None
    retrieval_query: Optional[str] = None
    state: Optional[DialogueState] = None


# 闲聊类意图直接回复
_CHITCHAT_TEMPLATES = {
    "greeting": [
        "您好!我是小淘,很高兴为您服务~请问有什么可以帮您？",
        "Hi 您好!小淘上线啦,需要什么帮助吗？😊",
    ],
    "goodbye": [
        "感谢您的咨询,祝您生活愉快,期待下次为您服务~👋",
        "好的,再见!有任何问题随时找小淘哦~",
    ],
    "thanks": [
        "不客气!为您服务是小淘的荣幸~😊",
        "感谢您的支持!如果还有其他问题,随时来问小淘哦~",
    ],
    "other": [
        "小淘还在学习中,您可以换个问法试试,例如:「iPhone 15 的电池容量多大？」",
        "抱歉没太理解您的问题,可以再具体描述一下吗？",
    ],
}

# 缺槽时的反问模板
_CLARIFY_TEMPLATES = {
    "query_product": {
        "product": "请问您想了解哪款商品的具体信息？",
        "brand": "请问您关注哪个品牌？",
    },
    "query_order": {
        "order_id": "请提供您的订单号,我帮您查询~",
    },
    "after_sales": {
        "order_id": "请提供订单号,我帮您处理退换货~",
    },
    "logistics": {
        "order_id": "请提供订单号,我帮您查询物流轨迹~",
    },
}


class DialogueManager:
    """对话管理器"""

    def __init__(self, nlu):
        self.nlu = nlu
        # 跨轮实体记忆(简单策略:把上一轮识别到的实体延续到下一轮)

    def new_session(self) -> DialogueState:
        return DialogueState()

    def handle(self, state: DialogueState, user_text: str) -> DialogueDecision:
        """处理用户输入,返回下一步动作"""
        # 1) NLU 解析
        nlu_result: NLUResult = self.nlu.parse(user_text)
        state.turn_count += 1
        state.push("user", user_text)

        # 2) 闲聊/告别/感谢 -> 直接答
        if nlu_result.intent in _CHITCHAT_TEMPLATES:
            import random
            reply = random.choice(_CHITCHAT_TEMPLATES[nlu_result.intent])
            state.push("assistant", reply)
            return DialogueDecision(
                action=ActionType.CHITCHAT,
                question=reply,
                state=state,
            )

        # 3) 投诉 -> 走 RETRIEVE(由检索层返回模板/话术)
        if nlu_result.intent == "complaint":
            state.current_intent = "complaint"
            state.slots = {}
            return DialogueDecision(
                action=ActionType.TEMPLATE,
                question="非常抱歉给您带来不愉快的体验,我已记录您的反馈。请问是否需要我帮您联系人工客服优先处理？",
                retrieval_query="投诉处理流程 售后客服",
                state=state,
            )

        # 4) 政策咨询 -> 走 RETRIEVE
        if nlu_result.intent == "policy_inquiry":
            state.current_intent = "policy_inquiry"
            # 用更精确的检索词
            return DialogueDecision(
                action=ActionType.RETRIEVE,
                retrieval_query=user_text,
                state=state,
            )

        # 5) 业务意图(query_product / query_order / after_sales / logistics) -> 槽位填充
        intent = nlu_result.intent
        state.current_intent = intent
        required = self.nlu.INTENT_SLOT_SCHEMA.get(intent, [])
        state.required_slots = required
        # 合并已填槽
        for slot in required:
            if nlu_result.slots.get(slot):
                state.slots[slot] = nlu_result.slots[slot]
            # 上下文继承
            elif slot in state.slots:
                pass  # 保留上一轮值
        # 计算缺失槽
        state.missing_slots = [s for s in required if not state.slots.get(s)]
        # 实体记忆:本轮新实体加入 context
        for ent in nlu_result.entities:
            if ent not in state.context_entities:
                state.context_entities.append(ent)
                if len(state.context_entities) > 20:
                    state.context_entities = state.context_entities[-20:]

        if state.missing_slots:
            # 反问第一个缺失槽
            slot = state.missing_slots[0]
            template_map = _CLARIFY_TEMPLATES.get(intent, {})
            question = template_map.get(slot, f"请补充{slot}信息:")
            return DialogueDecision(
                action=ActionType.CLARIFY,
                question=question,
                needed_slots=state.missing_slots,
                state=state,
            )

        # 6) 槽位齐 -> 进入 RETRIEVE
        # 构造精炼的检索 query
        retrieval_query = self._build_query(state, nlu_result)
        return DialogueDecision(
            action=ActionType.RETRIEVE,
            retrieval_query=retrieval_query,
            state=state,
        )

    def _build_query(self, state: DialogueState, nlu: NLUResult) -> str:
        parts = []
        if nlu.product:
            parts.append(nlu.product)
        if nlu.brand:
            parts.append(nlu.brand)
        if nlu.category:
            parts.append(nlu.category)
        # 用户原始问题也保留
        parts.append(nlu.raw_text)
        return " ".join(parts)

    def on_assistant_reply(self, state: DialogueState, reply: str) -> None:
        state.push("assistant", reply)


def demo() -> None:
    from generator.nlu import NLU
    nlu = NLU()
    dm = DialogueManager(nlu)
    state = dm.new_session()
    queries = [
        "你好",
        "我想查一下 iPhone 15 Pro",
        "它的电池容量多大？",  # 应继承上一轮的产品
    ]
    for q in queries:
        dec = dm.handle(state, q)
        print(f"\n>>> {q}")
        print(f"  action={dec.action.value}  question={dec.question}")
        print(f"  retrieval={dec.retrieval_query}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    demo()
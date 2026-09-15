"""端到端问答流水线

数据流:
    query
      ↓
    NLU.parse()        意图 + 实体 + 槽位
      ↓
    DialogueManager    决策:闲聊 / 反问 / 检索
      ↓
    BM25 / Neo4j       检索参考资料
      ↓
    DeepSeek           生成最终答案
      ↓
    QAResult
"""
from __future__ import annotations

import logging
import time
import traceback
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from config import BM25_TOP_K, RETURN_POLICY, SHIPPING_POLICY
from generator.deepseek_generator import DeepSeekError, DeepSeekGenerator
from generator.dialogue_manager import ActionType, DialogueDecision, DialogueManager, DialogueState
from generator.nlu import NLU
from retriever.bm25_retriever import BM25Retriever
from retriever.knowledge_graph import EntityNotFound, Neo4jKnowledgeGraph

logger = logging.getLogger(__name__)


@dataclass
class QAResult:
    """问答结果"""
    answer: str
    intent: str
    confidence: float
    sources: List[Dict[str, str]] = field(default_factory=list)
    trace: List[str] = field(default_factory=list)
    follow_up_question: Optional[str] = None
    latency_ms: int = 0
    meta: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "intent": self.intent,
            "confidence": self.confidence,
            "sources": self.sources,
            "trace": self.trace,
            "follow_up_question": self.follow_up_question,
            "latency_ms": self.latency_ms,
            "meta": self.meta,
        }


class QAPipeline:
    """端到端问答流水线"""

    def __init__(
        self,
        nlu: Optional[NLU] = None,
        dialogue_manager: Optional[DialogueManager] = None,
        bm25: Optional[BM25Retriever] = None,
        kg: Optional[Neo4jKnowledgeGraph] = None,
        generator: Optional[DeepSeekGenerator] = None,
        use_neo4j: bool = True,
    ):
        # 各组件延迟初始化,确保依赖失败时报错信息友好
        self.nlu = nlu or NLU()
        self.dm = dialogue_manager or DialogueManager(self.nlu)
        self.bm25 = bm25 or BM25Retriever()
        self.bm25.load_default()
        self.kg: Optional[Neo4jKnowledgeGraph] = None
        if use_neo4j:
            try:
                self.kg = Neo4jKnowledgeGraph.from_config()
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(
                    f"无法连接 Neo4j: {e}\n"
                    "请先启动 Neo4j 服务,或运行 scripts/init_neo4j.py 灌库。"
                ) from e
        self.generator = generator or DeepSeekGenerator()
        # 触发 DeepSeek Key 校验,失败立即抛错
        try:
            self.generator._ensure_key()  # noqa: SLF001
        except DeepSeekError:
            raise

    # ---------- 主入口 ----------
    def ask(self, query: str, session_state: Optional[DialogueState] = None) -> QAResult:
        t0 = time.time()
        state = session_state or self.dm.new_session()
        trace: List[str] = []

        # 1) 对话管理
        decision: DialogueDecision = self.dm.handle(state, query)
        trace.append(f"intent={state.current_intent}")
        trace.append(f"action={decision.action.value}")
        if decision.needed_slots:
            trace.append(f"missing_slots={decision.needed_slots}")

        # 2) 根据 action 路由
        if decision.action == ActionType.CLARIFY:
            result = QAResult(
                answer=decision.question or "请补充信息",
                intent=state.current_intent or "unknown",
                confidence=1.0,
                trace=trace,
                follow_up_question=decision.question,
                meta={"stage": "clarify"},
            )
            self.dm.on_assistant_reply(state, result.answer)
            result.latency_ms = int((time.time() - t0) * 1000)
            return result

        if decision.action == ActionType.CHITCHAT:
            result = QAResult(
                answer=decision.question or "",
                intent=state.current_intent or "unknown",
                confidence=1.0,
                trace=trace,
                meta={"stage": "chitchat"},
            )
            self.dm.on_assistant_reply(state, result.answer)
            result.latency_ms = int((time.time() - t0) * 1000)
            return result

        if decision.action == ActionType.TEMPLATE:
            # 投诉等场景:用业务话术 + 可选检索增强
            templates = self._retrieve(decision.retrieval_query or query)
            answer = decision.question or ""
            trace.append(f"retrieved={len(templates)}")
            result = QAResult(
                answer=answer,
                intent="complaint",
                confidence=0.9,
                sources=templates,
                trace=trace,
                meta={"stage": "template"},
            )
            self.dm.on_assistant_reply(state, result.answer)
            result.latency_ms = int((time.time() - t0) * 1000)
            return result

        # 3) RETRIEVE: 调检索 + DeepSeek 生成
        search_query = decision.retrieval_query or query
        retrieved = self._retrieve(search_query)
        trace.append(f"retrieved={len(retrieved)}")
        # 拼装 retrieved chunk
        retrieved_chunks = [
            f"{t['head']} 的 {t['relation']} 是 {t['tail']}" for t in retrieved
        ]
        # 业务策略:对退换货/物流等直接拼装更友好的答案
        if state.current_intent in ("after_sales", "policy_inquiry") and not retrieved:
            retrieved_chunks = [self._policy_template(state.current_intent)]
        # 注入业务策略
        history = state.history
        try:
            answer = self.generator.generate(
                user_query=query,
                retrieved_chunks=retrieved_chunks,
                history=history,
            )
        except DeepSeekError as e:
            logger.error(f"DeepSeek 调用失败: {e}")
            answer = self._fallback_answer(query, retrieved, state.current_intent, str(e))
            trace.append(f"generator_fallback=template (reason: {e})")
        result = QAResult(
            answer=answer,
            intent=state.current_intent or "other",
            confidence=0.9,
            sources=retrieved,
            trace=trace,
            meta={"stage": "retrieve+generate"},
        )
        self.dm.on_assistant_reply(state, result.answer)
        result.latency_ms = int((time.time() - t0) * 1000)
        return result

    # ---------- 检索融合:BM25 + Neo4j ----------
    def _retrieve(self, query: str, top_k: int = BM25_TOP_K) -> List[Dict[str, str]]:
        """BM25 为主,Neo4j 作为实体精确查询补充"""
        results = self.bm25.search(query, top_k=top_k)
        triple_set = {(t["head"], t["relation"], t["tail"]): t for t, _ in results}
        # Neo4j 实体扩展:如果 BM25 结果里有 head 实体,再拉一跳
        if self.kg is not None and results:
            try:
                seed = results[0][0]["head"]
                kg_rows = self.kg.query_entity(seed)
                for row in kg_rows:
                    key = (row["head"], row["relation"], row["tail"])
                    triple_set.setdefault(key, row)
            except EntityNotFound:
                pass
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Neo4j 扩展查询失败: {e}")
        return list(triple_set.values())[:top_k]

    # ---------- 业务策略模板 ----------
    def _policy_template(self, intent: str) -> str:
        if intent == "after_sales":
            p = RETURN_POLICY
            return (
                f"支持 {p['window_days']} 天无理由退货,条件: {p['conditions']}。"
                f"申请渠道: {','.join(p['channels'])}。"
                f"退款方式: {','.join(p['refund_methods'])}。{p['note']}。"
            )
        if intent == "logistics" or intent == "policy_inquiry":
            p = SHIPPING_POLICY
            return (
                f"默认快递: {p['default_carrier']};"
                f"满 {p['free_shipping_threshold']} 元包邮;"
                f"发货时效: {p['delivery_window_hours'][0]}-{p['delivery_window_hours'][1]} 小时。"
                f"{p['note']}。"
            )
        return ""

    def _fallback_answer(self, query: str, sources: List[Dict[str, str]], intent: str, err: str) -> str:
        """DeepSeek 不可用时的模板兜底"""
        if not sources:
            return (
                f"抱歉,未检索到与「{query}」相关的信息,建议您换个问法或联系人工客服。"
            )
        snippets = "; ".join(
            f"{s['head']} {s['relation']} {s['tail']}" for s in sources[:3]
        )
        return f"根据资料:{snippets}。如需更详细帮助,请联系人工客服。"

    # ---------- 依赖自检 ----------
    def self_check(self) -> Dict[str, str]:
        """返回各依赖的状态"""
        result: Dict[str, str] = {}
        # 1) Neo4j
        if self.kg is not None:
            try:
                stats = self.kg.stats()
                result["neo4j"] = f"✅ 已连接 (节点 {stats['nodes']}, 关系 {stats['relations']})"
            except Exception as e:  # noqa: BLE001
                result["neo4j"] = f"❌ 异常: {e}"
        else:
            result["neo4j"] = "❌ 未启用"
        # 2) DeepSeek
        try:
            self.generator._ensure_key()  # noqa: SLF001
            result["deepseek"] = f"✅ API Key 已配置 (model: {self.generator.model})"
        except DeepSeekError as e:
            result["deepseek"] = f"❌ {e}"
        # 3) BM25
        result["bm25"] = f"✅ 已索引 {self.bm25.size} 条三元组"
        # 4) NLU
        result["nlu"] = (
            f"{'✅ 加载 BERT' if self.nlu.intent_predictor.is_real_model else '⚠️ 使用规则兜底(无训练权重)'}"
        )
        return result


def demo() -> None:
    pipe = QAPipeline()
    print("=== 依赖自检 ===")
    for k, v in pipe.self_check().items():
        print(f"  {k}: {v}")
    print("\n=== 问答 ===")
    queries = [
        "你好",
        "iPhone 15 Pro 的电池容量多大？",
        "我想退货,订单号 12345678901234",
        "退换货政策是什么？",
        "运费多少？",
    ]
    for q in queries:
        res = pipe.ask(q)
        print(f"\nQ: {q}")
        print(f"A: {res.answer}")
        print(f"  intent={res.intent} | {res.latency_ms}ms | sources={len(res.sources)}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    demo()
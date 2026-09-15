"""端到端测试

仅在依赖(Neo4j + DeepSeek)可用时执行集成测试;
否则通过 pytest.skip 跳过,保证环境无依赖时也能跑通基础单元测试。
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.WARNING)


# ---------- 单元测试:不依赖外部服务 ----------
def test_bm25_retriever_basic():
    """BM25 基本检索"""
    from retriever.bm25_retriever import BM25Retriever

    bm = BM25Retriever()
    bm.load_default()
    assert bm.size > 100, "知识库应加载 100+ 条三元组"
    results = bm.search("iPhone 15 Pro 电池容量", top_k=3)
    assert results, "应至少返回 1 条结果"
    triples, scores = zip(*results)
    assert any("电池容量" in t["relation"] or "电池容量" in t["tail"] for t in triples)


def test_entity_disambiguation():
    """实体消歧:同义词、模糊匹配"""
    from retriever.entity_disambiguation import EntityDisambiguator

    triples = json.loads((ROOT / "data" / "knowledge_triples.json").read_text(encoding="utf-8"))
    entities = sorted({t["head"] for t in triples} | {t["tail"] for t in triples})
    dis = EntityDisambiguator(entities)

    # 同义词:nikc -> 耐克
    std, conf, mode = dis.disambiguate("nikc")
    assert "耐克" in std
    assert mode == "synonym"

    # 模糊:Air Max
    std, conf, mode = dis.disambiguate("Air Max")
    assert "Air Max" in std
    assert conf > 0.4


def test_nlu_intent_classification():
    """NLU:至少识别 3 类意图"""
    from generator.nlu import NLU

    nlu = NLU()
    cases = [
        ("iPhone 15 电池多大", "query_product"),
        ("我想退货", "after_sales"),
        ("运费多少", "policy_inquiry"),
    ]
    for q, expected in cases:
        r = nlu.parse(q)
        assert r.intent == expected, f"'{q}' -> {r.intent} (expected {expected})"


def test_dialogue_manager_clarify():
    """对话管理:缺槽反问"""
    from generator.dialogue_manager import ActionType, DialogueManager
    from generator.nlu import NLU

    nlu = NLU()
    dm = DialogueManager(nlu)
    state = dm.new_session()
    # 订单查询但没有提供订单号
    dec = dm.handle(state, "我的订单到哪了?")
    assert dec.action == ActionType.CLARIFY
    assert "订单号" in dec.question


def test_dialogue_manager_chitchat():
    """对话管理:闲聊直接答"""
    from generator.dialogue_manager import ActionType, DialogueManager
    from generator.nlu import NLU

    nlu = NLU()
    dm = DialogueManager(nlu)
    state = dm.new_session()
    dec = dm.handle(state, "你好")
    assert dec.action == ActionType.CHITCHAT


# ---------- 集成测试(需要 Neo4j + DeepSeek) ----------
def pytest_addoption(parser):
    parser.addoption(
        "--integration", action="store_true", default=False,
        help="跑需要 Neo4j + DeepSeek 的集成测试",
    )


def _integration_enabled(config):
    return config.getoption("--integration", default=False)


@pytest.mark.skipif(
    "not _integration_enabled(config)",
    reason="需要 Neo4j + DeepSeek 外部依赖,显式加 --integration 才跑",
)
def test_integration_end_to_end():
    from pipeline.qa_pipeline import QAPipeline

    pipe = QAPipeline()
    res = pipe.ask("iPhone 15 Pro 的电池容量多大？")
    assert res.intent == "query_product"
    assert "3274" in res.answer or "电池" in res.answer
    assert res.latency_ms < 30_000


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
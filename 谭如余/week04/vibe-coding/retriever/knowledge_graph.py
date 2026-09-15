"""Neo4j 知识图谱客户端

提供:
- Neo4jKnowledgeGraph: 严格依赖 Neo4j 的实现
- EntityNotFound: 实体未找到异常

API:
- connect()  : 连接到 Neo4j
- add_triple(): 添加 (h, r, t) 三元组
- query_entity(): 查询实体所有三元组
- get_subgraph(): 获取以实体为中心的两跳子图
- stats(): 节点 / 关系计数
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class EntityNotFound(Exception):
    """实体未找到"""


class Neo4jKnowledgeGraph:
    """Neo4j 知识图谱客户端

    使用 py2neo 操作图数据库。启动时即连接,失败抛错。
    """

    def __init__(self, uri: str, user: str, password: str):
        self.uri = uri
        self.user = user
        self.password = password
        self._graph = None
        self._connected = False

    # ---------- 连接管理 ----------
    def connect(self) -> None:
        if self._connected:
            return
        try:
            from py2neo import Graph  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "缺少 py2neo 依赖,请运行: pip install py2neo"
            ) from e
        try:
            self._graph = Graph(self.uri, auth=(self.user, self.password))
            # 触发一次查询验证连接
            self._graph.run("RETURN 1 AS ok").data()
            self._connected = True
            logger.info(f"[Neo4j] 已连接 {self.uri}")
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"无法连接 Neo4j ({self.uri}): {e}\n"
                "请确认 Neo4j 已启动,并检查 NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD。"
            ) from e

    def close(self) -> None:
        if self._graph is not None:
            try:
                self._graph.driver.close()  # type: ignore
            except Exception:  # noqa: BLE001
                pass
        self._connected = False

    # ---------- 数据写入 ----------
    def add_triple(self, head: str, relation: str, tail: str) -> None:
        """添加 (h, r, t),使用 MERGE 避免重复"""
        assert self._graph is not None
        cypher = (
            "MERGE (h:Entity {name: $head}) "
            "MERGE (t:Entity {name: $tail}) "
            "MERGE (h)-[r:RELATION {type: $rel}]->(t)"
        )
        self._graph.run(cypher, head=head, rel=relation, tail=tail)

    def add_triples(self, triples: List[Dict[str, str]]) -> int:
        n = 0
        for tri in triples:
            try:
                self.add_triple(tri["head"], tri["relation"], tri["tail"])
                n += 1
            except Exception as e:  # noqa: BLE001
                logger.warning(f"插入失败 {tri}: {e}")
        return n

    def clear(self) -> None:
        """清空所有节点和关系"""
        assert self._graph is not None
        self._graph.run("MATCH (n) DETACH DELETE n")

    # ---------- 查询 ----------
    def query_entity(self, entity: str) -> List[Dict[str, str]]:
        """查询与某实体相关的所有三元组"""
        assert self._graph is not None
        cypher = (
            "MATCH (h:Entity {name: $name})-[r:RELATION]->(t:Entity) "
            "RETURN h.name AS head, r.type AS relation, t.name AS tail"
        )
        rows = self._graph.run(cypher, name=entity).data()
        return [{"head": r["head"], "relation": r["relation"], "tail": r["tail"]} for r in rows]

    def get_subgraph(self, entity: str, hops: int = 2) -> List[Dict[str, str]]:
        """获取 N 跳以内的子图"""
        assert self._graph is not None
        cypher = (
            f"MATCH (e:Entity {{name: $name}})-[r:RELATION*1..{hops}]-(other) "
            "UNWIND r AS rel "
            "RETURN startNode(rel).name AS head, rel.type AS relation, endNode(rel).name AS tail"
        )
        rows = self._graph.run(cypher, name=entity).data()
        return [
            {"head": r["head"], "relation": r["relation"], "tail": r["tail"]}
            for r in rows
            if r["head"] and r["tail"]
        ]

    def search_by_text(self, text: str) -> List[Dict[str, str]]:
        """按文本模糊匹配实体名"""
        assert self._graph is not None
        cypher = (
            "MATCH (h:Entity)-[r:RELATION]->(t:Entity) "
            "WHERE h.name CONTAINS $t OR t.name CONTAINS $t "
            "RETURN h.name AS head, r.type AS relation, t.name AS tail "
            "LIMIT 50"
        )
        rows = self._graph.run(cypher, t=text).data()
        return [{"head": r["head"], "relation": r["relation"], "tail": r["tail"]} for r in rows]

    def stats(self) -> Dict[str, int]:
        assert self._graph is not None
        n_nodes = self._graph.run("MATCH (n) RETURN count(n) AS c").data()[0]["c"]
        n_rels = self._graph.run("MATCH ()-[r]->() RETURN count(r) AS c").data()[0]["c"]
        return {"nodes": n_nodes, "relations": n_rels}

    # ---------- 工厂方法 ----------
    @classmethod
    def from_config(cls) -> "Neo4jKnowledgeGraph":
        """从 config.py 创建并连接"""
        from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

        kg = cls(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
        kg.connect()
        return kg


def demo() -> None:
    kg = Neo4jKnowledgeGraph.from_config()
    print("统计:", kg.stats())
    print("iPhone 15 Pro 关联三元组:")
    for tri in kg.query_entity("苹果 iPhone 15 Pro 256GB")[:5]:
        print(f"  {tri}")
    kg.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    demo()
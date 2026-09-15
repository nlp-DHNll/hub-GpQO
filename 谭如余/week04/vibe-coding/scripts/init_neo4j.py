"""初始化 Neo4j 知识图谱

从 data/knowledge_triples.json 灌库到 Neo4j。
用法:
    python scripts/init_neo4j.py           # 增量灌入
    python scripts/init_neo4j.py --drop    # 先清空再灌入
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from retriever.knowledge_graph import Neo4jKnowledgeGraph  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("init_neo4j")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--drop", action="store_true", help="先清空再灌入")
    parser.add_argument("--data", type=str, default=None, help="三元组 JSON 路径")
    args = parser.parse_args()

    data_path = Path(args.data) if args.data else ROOT / "data" / "knowledge_triples.json"
    if not data_path.exists():
        logger.error(f"数据文件不存在: {data_path}")
        sys.exit(1)
    triples = json.loads(data_path.read_text(encoding="utf-8"))
    logger.info(f"读取 {len(triples)} 条三元组 from {data_path}")

    logger.info("连接 Neo4j ...")
    kg = Neo4jKnowledgeGraph.from_config()

    if args.drop:
        logger.warning("清空知识图谱 ...")
        kg.clear()

    t0 = time.time()
    n = kg.add_triples(triples)
    logger.info(f"插入 {n} 条三元组,耗时 {time.time() - t0:.2f}s")
    stats = kg.stats()
    logger.info(f"图谱统计: 节点={stats['nodes']}, 关系={stats['relations']}")
    kg.close()
    logger.info("✅ 知识图谱初始化完成")


if __name__ == "__main__":
    main()
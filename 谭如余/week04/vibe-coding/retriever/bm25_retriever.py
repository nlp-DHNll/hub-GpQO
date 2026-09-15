"""BM25 检索器

实现 Okapi BM25:
    score(D, Q) = Σ IDF(qi) · (f(qi, D) · (k1 + 1)) / (f(qi, D) + k1 · (1 - b + b · |D|/avgdl))

要点:
- 使用 jieba 做中文分词
- 优先使用 rank_bm25 库,失败时使用自实现
- 支持查询、批量检索、Top-K
"""
from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

DEFAULT_K1 = 1.5
DEFAULT_B = 0.75


def _tokenize(text: str) -> List[str]:
    """简单中文分词(优先 jieba,失败则退化为单字)"""
    try:
        import jieba  # type: ignore

        jieba.setLogLevel(logging.ERROR)
        return [t for t in jieba.cut(text) if t.strip()]
    except Exception:  # noqa: BLE001
        # 退化:中文字 + ASCII 一起
        return [c for c in text if c.strip()]


class _ManualBM25:
    """手写 BM25 实现(避免 rank_bm25 缺失)"""

    def __init__(self, corpus_tokens: List[List[str]], k1: float = DEFAULT_K1, b: float = DEFAULT_B):
        self.k1 = k1
        self.b = b
        self.corpus = corpus_tokens
        self.N = len(corpus_tokens)
        self.avgdl = sum(len(d) for d in corpus_tokens) / max(self.N, 1)
        # 词频
        self.tf: List[Counter] = [Counter(d) for d in corpus_tokens]
        # 文档频率
        self.df: Counter = Counter()
        for tf in self.tf:
            for term in tf:
                self.df[term] += 1
        # 逆文档频率(对每个词一次性算好)
        self.idf = {
            term: math.log((self.N - df + 0.5) / (df + 0.5) + 1.0) for term, df in self.df.items()
        }

    def score(self, query_tokens: Sequence[str], doc_idx: int) -> float:
        tf = self.tf[doc_idx]
        dl = sum(tf.values())
        s = 0.0
        for q in query_tokens:
            if q not in tf:
                continue
            f = tf[q]
            idf = self.idf.get(q, 0.0)
            s += idf * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return s

    def top_k(self, query_tokens: Sequence[str], k: int = 5) -> List[Tuple[int, float]]:
        scores = [(i, self.score(query_tokens, i)) for i in range(self.N)]
        scores.sort(key=lambda x: -x[1])
        return [s for s in scores if s[1] > 0][:k]


class BM25Retriever:
    """BM25 检索器(基于三元组语料)

    输入:用户 query
    输出:排序后的 (三元组 dict, 分数) 列表
    """

    def __init__(self, k1: float = DEFAULT_K1, b: float = DEFAULT_B):
        self.k1 = k1
        self.b = b
        self._bm25: Optional[_ManualBM25] = None
        self._triples: List[dict] = []
        self._corpus_text: List[str] = []
        self._loaded = False

    @property
    def size(self) -> int:
        return len(self._triples)

    def index(self, triples: Iterable[dict]) -> None:
        """对三元组建立索引"""
        self._triples = list(triples)
        self._corpus_text = [f"{t.get('head','')} {t.get('relation','')} {t.get('tail','')}" for t in self._triples]
        tokens_list = [_tokenize(t) for t in self._corpus_text]
        # 尝试使用 rank_bm25,失败则手写
        try:
            from rank_bm25 import BM25Okapi  # type: ignore

            self._bm25 = BM25Okapi(tokens_list, k1=self.k1, b=self.b)
            self._backend = "rank_bm25"
        except Exception as e:  # noqa: BLE001
            logger.info(f"rank_bm25 不可用({e}),使用手写 BM25")
            self._bm25 = _ManualBM25(tokens_list, self.k1, self.b)
            self._backend = "manual"
        self._loaded = True
        logger.info(f"[BM25] 索引完成,共 {len(self._triples)} 条三元组(后端: {self._backend})")

    def load_default(self, data_path: Optional[Path] = None) -> None:
        """加载内置数据"""
        if data_path is None:
            data_path = Path(__file__).parent.parent / "data" / "knowledge_triples.json"
        triples = json.loads(data_path.read_text(encoding="utf-8"))
        self.index(triples)

    def search(self, query: str, top_k: int = 5) -> List[Tuple[dict, float]]:
        if not self._loaded:
            self.load_default()
        assert self._bm25 is not None
        q_tokens = _tokenize(query)
        if self._backend == "rank_bm25":
            scores = self._bm25.get_scores(q_tokens)
            idx_scores = sorted(enumerate(scores), key=lambda x: -x[1])[:top_k]
        else:
            idx_scores = self._bm25.top_k(q_tokens, k=top_k)  # type: ignore
        results: List[Tuple[dict, float]] = []
        for idx, score in idx_scores:
            if score <= 0:
                continue
            results.append((self._triples[idx], float(score)))
        return results

    def search_by_entity(self, entity: str, top_k: int = 10) -> List[dict]:
        """按实体名检索(精确或模糊)"""
        if not self._loaded:
            self.load_default()
        result: List[dict] = []
        for tri in self._triples:
            if entity in tri.get("head", "") or entity in tri.get("tail", ""):
                result.append(tri)
                if len(result) >= top_k:
                    break
        return result


def demo() -> None:
    bm25 = BM25Retriever()
    bm25.load_default()
    for q in ["iPhone 15 Pro 的电池容量", "耐克的运动鞋价格", "退换货政策"]:
        print(f"\nQ: {q}")
        for tri, score in bm25.search(q, top_k=3):
            print(f"  ({score:.2f}) {tri}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    demo()
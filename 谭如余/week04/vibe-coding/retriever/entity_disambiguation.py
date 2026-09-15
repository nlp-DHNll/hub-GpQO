"""实体消歧模块

两步策略:
1) 同义词词典精确匹配
2) TF-IDF + 余弦相似度 模糊匹配
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


class EntityDisambiguator:
    """实体消歧器

    把用户输入的「可能是某个实体的字符串」映射到知识库中的「标准实体名」
    """

    def __init__(self, knowledge_entities: Optional[Sequence[str]] = None,
                 synonyms: Optional[Dict[str, str]] = None,
                 sim_threshold: float = 0.35):
        self.synonyms = synonyms or self._load_synonyms()
        self.entities: List[str] = []
        self._entity_vec = None  # TF-IDF 向量
        self._vectorizer = None
        self.sim_threshold = sim_threshold
        if knowledge_entities:
            self.fit(knowledge_entities)

    @staticmethod
    def _load_synonyms() -> Dict[str, str]:
        path = Path(__file__).parent.parent / "data" / "entity_synonyms.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def fit(self, entities: Sequence[str]) -> None:
        """基于标准实体列表训练 TF-IDF"""
        from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore

        self.entities = list(entities)
        self._vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(1, 2))
        if self.entities:
            self._entity_vec = self._vectorizer.fit_transform(self.entities)
        logger.info(f"[消歧] 加载了 {len(self.entities)} 个标准实体")

    def disambiguate(self, mention: str) -> Tuple[Optional[str], float, str]:
        """把 mention 映射到标准实体

        Returns: (标准实体, 置信度, 匹配方式: "exact"/"synonym"/"tfidf"/"none")
        """
        if not mention or not self.entities:
            return None, 0.0, "none"

        # 1) 词典匹配(最高优先),对 ASCII 做大小写不敏感
        for key, mapped in self.synonyms.items():
            if mention == key or mention.lower() == key.lower():
                if mapped in self.entities:
                    return mapped, 1.0, "synonym"
                return self._tfidf_match(mapped)

        # 2) 精确包含
        for ent in self.entities:
            if mention in ent or ent in mention:
                return ent, 0.95, "exact"

        # 3) TF-IDF 模糊匹配
        return self._tfidf_match(mention)

    def _tfidf_match(self, mention: str) -> Tuple[Optional[str], float, str]:
        if self._entity_vec is None or self._vectorizer is None:
            return None, 0.0, "none"
        from sklearn.metrics.pairwise import cosine_similarity  # type: ignore

        try:
            v = self._vectorizer.transform([mention])
            sims = cosine_similarity(v, self._entity_vec)[0]
            best_idx = sims.argmax()
            best_score = float(sims[best_idx])
            if best_score >= self.sim_threshold:
                return self.entities[best_idx], best_score, "tfidf"
        except Exception as e:  # noqa: BLE001
            logger.warning(f"TF-IDF 匹配失败: {e}")
        return None, 0.0, "none"

    def extract_and_disambiguate(self, text: str, candidates: Optional[List[str]] = None) -> List[Tuple[str, str, float]]:
        """从文本中抽取可能的实体提及并消歧

        Args:
            text: 原始文本
            candidates: 自定义候选实体提及(若为 None,自动扫描)

        Returns: [(标准实体, 匹配方式, 置信度), ...]
        """
        # 收集候选
        if candidates is None:
            candidates = self._scan_candidates(text)
        seen = set()
        out: List[Tuple[str, str, float]] = []
        for cand in candidates:
            std, conf, mode = self.disambiguate(cand)
            if std and std not in seen and conf > 0:
                seen.add(std)
                out.append((std, mode, conf))
        return out

    def _scan_candidates(self, text: str) -> List[str]:
        cands: List[str] = []
        # 1) 同义词词典里的所有 key
        for k in self.synonyms.keys():
            if k and k in text and len(k) >= 2:
                cands.append(k)
        # 2) 知识库实体名扫描(从长到短)
        for ent in sorted(self.entities, key=len, reverse=True):
            if ent and ent in text:
                cands.append(ent)
        return cands


def demo() -> None:
    data_path = Path(__file__).parent.parent / "data" / "knowledge_triples.json"
    triples = json.loads(data_path.read_text(encoding="utf-8"))
    entities = sorted({t["head"] for t in triples} | {t["tail"] for t in triples})

    dis = EntityDisambiguator(entities)
    for m in ["nikc", "Air Max", "iPhone", "苹果手机", "阿迪", "Apple"]:
        std, conf, mode = dis.disambiguate(m)
        print(f"  '{m}' -> {std} (mode={mode}, conf={conf:.2f})")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    demo()
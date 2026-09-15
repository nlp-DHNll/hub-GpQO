"""自然语言理解(NLU)模块

组合:
1) BERT 意图分类(主)
2) 关键词词典(兜底)
3) 实体消歧(基于 EntityDisambiguator)

输出 NLUResult: {intent, intent_conf, entities, slots, raw_text}
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class NLUResult:
    """NLU 解析结果"""
    raw_text: str
    intent: str
    intent_confidence: float
    entities: List[Dict[str, str]] = field(default_factory=list)  # {text, type, value, mode, conf}
    slots: Dict[str, str] = field(default_factory=dict)
    # 实体类型白名单
    brand: Optional[str] = None
    product: Optional[str] = None
    category: Optional[str] = None
    price: Optional[str] = None
    order_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "raw_text": self.raw_text,
            "intent": self.intent,
            "intent_confidence": round(self.intent_confidence, 3),
            "entities": self.entities,
            "slots": self.slots,
            "brand": self.brand,
            "product": self.product,
            "category": self.category,
            "price": self.price,
            "order_id": self.order_id,
        }


class NLU:
    """自然语言理解器"""

    # 意图 -> 需要的槽位
    INTENT_SLOT_SCHEMA = {
        "query_product": ["brand", "product"],
        "query_order": ["order_id"],
        "after_sales": ["order_id"],
        "logistics": ["order_id"],
        "policy_inquiry": [],
        "complaint": [],
        "greeting": [],
        "goodbye": [],
        "thanks": [],
        "other": [],
    }

    def __init__(self):
        from models.intent_classifier import IntentPredictor
        from retriever.entity_disambiguation import EntityDisambiguator

        self.intent_predictor = IntentPredictor()
        # 加载知识库实体以构建消歧器
        triples_path = Path(__file__).parent.parent / "data" / "knowledge_triples.json"
        import json
        triples = json.loads(triples_path.read_text(encoding="utf-8"))
        entities = sorted({t["head"] for t in triples} | {t["tail"] for t in triples})
        self.disambiguator = EntityDisambiguator(entities)

    def parse(self, text: str) -> NLUResult:
        intent, conf = self.intent_predictor.predict(text)
        # 实体抽取 + 消歧
        entities = self.disambiguator.extract_and_disambiguate(text)
        # 抽取订单号(数字串)
        order_id = self._extract_order_id(text)
        # 抽取价格
        price = self._extract_price(text)
        # 解析标准字段
        brand = product = category = None
        for ent in entities:
            std, mode, c = ent
            if self._is_brand(std):
                brand = std
            elif self._is_category(std):
                category = std
            elif std not in (brand, category):
                product = std
        # 槽位填充
        slots = {slot: self._pick_slot(slot, brand, product, category, price, order_id)
                 for slot in self.INTENT_SLOT_SCHEMA.get(intent, [])}
        return NLUResult(
            raw_text=text,
            intent=intent,
            intent_confidence=conf,
            entities=[
                {"text": std, "mode": mode, "confidence": round(c, 3)}
                for std, mode, c in entities
            ],
            slots=slots,
            brand=brand,
            product=product,
            category=category,
            price=price,
            order_id=order_id,
        )

    # ---------- 内部辅助 ----------
    _BRAND_KEYWORDS = {
        "耐克", "阿迪达斯", "苹果", "小米", "华为", "联想", "索尼", "戴森",
        "美的", "海尔", "小天才", "雅诗兰黛", "兰蔻", "SK-II", "可口可乐",
        "三只松鼠", "九阳", "罗技", "雷蛇", "迪卡侬", "李宁", "安踏",
        "特步", "苏泊尔", "OPPO",
    }
    _CATEGORY_KEYWORDS = {
        "运动鞋", "跑步鞋", "篮球鞋", "手机", "笔记本电脑", "笔记本", "平板电脑",
        "耳机", "空调", "洗衣机", "冰箱", "电视", "美妆", "精华", "眼霜",
        "护肤水", "饮料", "零食", "小家电", "键盘", "鼠标", "厨房用品",
        "智能穿戴", "儿童手表", "电脑配件", "破壁机", "电饭煲", "不粘锅",
        "家电", "运动健身",
    }

    def _is_brand(self, name: str) -> bool:
        for b in self._BRAND_KEYWORDS:
            if b in name or name in b:
                return True
        return False

    def _is_category(self, name: str) -> bool:
        return name in self._CATEGORY_KEYWORDS

    def _extract_order_id(self, text: str) -> Optional[str]:
        # 12-20 位纯数字 或 「订单 123456」 / 「订单号 123456」
        m = re.search(r"订单\s?(?:号?\s?)?(\d{8,20})", text)
        if m:
            return m.group(1)
        m = re.search(r"(?<!\d)(\d{12,20})(?!\d)", text)
        if m:
            return m.group(1)
        return None

    def _extract_price(self, text: str) -> Optional[str]:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:元|块)", text)
        return m.group(1) if m else None

    def _pick_slot(self, slot: str, brand, product, category, price, order_id) -> Optional[str]:
        return {
            "brand": brand,
            "product": product,
            "category": category,
            "price": price,
            "order_id": order_id,
        }.get(slot)


def demo() -> None:
    nlu = NLU()
    for q in [
        "iPhone 15 Pro 的电池容量多大？",
        "我想退货,订单号 123456789012345",
        "耐克 Air Max 的价格是 899 元吗？",
        "运费多少？",
    ]:
        res = nlu.parse(q)
        print(f"\nQ: {q}")
        print(f"  intent={res.intent} ({res.intent_confidence:.2f})")
        print(f"  brand={res.brand} product={res.product} category={res.category} order_id={res.order_id}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    demo()
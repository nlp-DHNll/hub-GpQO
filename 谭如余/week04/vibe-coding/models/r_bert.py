"""R-BERT 关系抽取模型

参考论文:Enriching Pre-trained Language Model with Entity Information for Relation Classification
(arXiv:1905.08284)

核心做法:
1) 在 BERT 输入中插入实体标记符(本文用 §...§ / £...£)
2) 取 [CLS] 表征与两个实体首位的隐藏状态拼接
3) 经过分类头输出关系标签

为了在不引入 torch / transformers 训练成本的前提下保留可演示的接口,
本模块默认加载「基于预训练 BERT + 随机初始化分类头」 的模型,
对内置 10+ 类关系给出基于规则 + 关键词相似度的伪预测。
真实训练请运行 scripts/train_r_bert.py。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 关系类型定义
RELATION_LABELS = [
    "无关",
    "品牌",
    "类别",
    "价格",
    "库存",
    "电池容量",
    "处理器",
    "内存",
    "硬盘",
    "屏幕尺寸",
    "重量",
    "颜色",
    "续航",
    "降噪能力",
    "容量",
    "核心成分",
    "功效",
    "防水等级",
    "中底科技",
    "鞋底材质",
    "适用场景",
    "吸力",
    "制冷量",
    "能效等级",
    "适用面积",
    "转速",
    "特色功能",
    "材质",
    "直径",
    "厚度",
    "轴体",
    "芯片",
    "充电",
    "连接",
    "佩戴方式",
    "集尘容量",
    "加热方式",
    "功率",
    "规格",
    "净含量",
    "直径",
    "摄像头",
    "退款方式",
    "适用商品",
    "退货时限",
    "退货条件",
    "申请渠道",
    "运费承担",
    "不适用商品",
    "退款时效",
    "包邮门槛",
    "发货时效",
    "附加运费",
    "派送时间",
    "支持渠道",
    "分期支持",
    "发票",
    "等级",
    "专属折扣",
    "免邮特权",
    "服务时间",
    "号码",
    "型号",
    "其他",
]
ID2REL = {i: r for i, r in enumerate(RELATION_LABELS)}


class RBertRelationExtractor:
    """R-BERT 关系抽取器

    接口与真实模型保持一致:
        extractor.predict(sentence, head, tail) -> (relation, confidence)
    """

    def __init__(self, model_name: str = "bert-base-chinese"):
        self.model_name = model_name
        self._pipeline = None  # 真实 transformers pipeline(延迟加载)
        self._use_real = False

    def _lazy_load(self):
        if self._pipeline is not None:
            return
        try:
            from transformers import pipeline  # type: ignore
            self._pipeline = pipeline(
                "text-classification",
                model=self.model_name,
                tokenizer=self.model_name,
                top_k=1,
            )
            self._use_real = True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"无法加载真实 BERT,使用规则回退: {e}")
            self._use_real = False

    def predict(self, sentence: str, head: str, tail: str) -> Tuple[str, float]:
        """预测 head 与 tail 在 sentence 中的关系

        Returns: (关系, 置信度)
        """
        self._lazy_load()
        if self._use_real:
            try:
                # 拼接 R-BERT 输入:用 § § 包围 head,用 £ £ 包围 tail
                marked = sentence.replace(head, f"§{head}§", 1).replace(tail, f"£{tail}£", 1)
                res = self._pipeline(marked)
                if isinstance(res, list) and res:
                    if isinstance(res[0], list):
                        res = res[0][0]
                    else:
                        res = res[0]
                    return res["label"], float(res["score"])
            except Exception as e:  # noqa: BLE001
                logger.warning(f"BERT 推理失败,使用规则: {e}")
        return self._rule_based(sentence, head, tail)

    # ---------- 基于规则 + 关键词的回退 ----------
    _PATTERNS = [
        # (关键词, 关系)
        (r"价格.{0,8}是?|多少钱", "价格"),
        (r"电池容量|mAh", "电池容量"),
        (r"处理器|CPU|骁龙|麒麟|A1[0-9]|Ultra", "处理器"),
        (r"内存|GB\s?RAM", "内存"),
        (r"硬盘|SSD|存储", "硬盘"),
        (r"屏幕.{0,4}(尺寸|大小|英寸)|英寸|inch", "屏幕尺寸"),
        (r"重量|约.{0,4}g", "重量"),
        (r"颜色|配色", "颜色"),
        (r"续航|小时|分钟", "续航"),
        (r"降噪|降噪能力", "降噪能力"),
        (r"容量|ml|L\b|kg", "容量"),
        (r"PITERA|玻色因|核心成分|成分", "核心成分"),
        (r"功效|作用", "功效"),
        (r"防水|IPX|ATM", "防水等级"),
        (r"中底科技|䨻|Boost|泡棉|科技", "中底科技"),
        (r"鞋底.{0,3}材质|材质", "鞋底材质"),
        (r"适用场景|场景", "适用场景"),
        (r"吸力|AW", "吸力"),
        (r"制冷量", "制冷量"),
        (r"能效", "能效等级"),
        (r"适用面积", "适用面积"),
        (r"转速|转/分", "转速"),
        (r"特色功能|除菌|显尘|动态|激光", "特色功能"),
        (r"材质|不粘|麦饭石", "材质"),
        (r"直径", "直径"),
        (r"厚度|mm", "厚度"),
        (r"轴体|轴", "轴体"),
        (r"芯片|H\d", "芯片"),
        (r"充电|USB-C|Type-C|无线", "充电"),
        (r"蓝牙.{0,3}\d|连接", "连接"),
        (r"入耳|头戴|佩戴", "佩戴方式"),
        (r"集尘容量", "集尘容量"),
        (r"加热.{0,3}方式|IH", "加热方式"),
        (r"功率|W$|\dW", "功率"),
        (r"规格|×|x", "规格"),
        (r"净含量", "净含量"),
        (r"摄像头|像素|主摄", "摄像头"),
        (r"品牌|哪个.{0,2}牌|厂商", "品牌"),
        (r"类别|什么类|分类", "类别"),
        (r"库存|有货|现货", "库存"),
    ]

    def _rule_based(self, sentence: str, head: str, tail: str) -> Tuple[str, float]:
        text = sentence
        for pat, rel in self._PATTERNS:
            if re.search(pat, text):
                return rel, 0.78
        return "无关", 0.92

    def extract_from_text(self, text: str) -> List[Dict[str, str]]:
        """从句子中抽取所有三元组

        1) 使用 NER 找到所有实体
        2) 实体两两配对,送入 R-BERT 判关系
        """
        from .bilstm_crf import BiLSTMCRF  # 局部导入避免循环

        ner = BiLSTMCRF()
        entities = ner.predict(text)
        triples: List[Dict[str, str]] = []
        # 只用 PROD / BRAND 作为 head
        heads = [e for e in entities if e[1] in ("PROD", "BRAND")]
        tails = [e for e in entities if e[1] in ("PRICE", "CAT", "MODEL", "PROD", "BRAND")]
        for h in heads:
            for t in tails:
                if h == t:
                    continue
                rel, conf = self.predict(text, h[0], t[0])
                if rel != "无关" and conf >= 0.5:
                    triples.append(
                        {"head": h[0], "relation": rel, "tail": t[0], "confidence": f"{conf:.2f}"}
                    )
        return triples


def demo() -> None:
    extractor = RBertRelationExtractor()
    triples = extractor.extract_from_text("耐克 Air Max 2024 的价格是 899 元,使用橡胶鞋底")
    print("抽取结果:")
    for t in triples:
        print(f"  ({t['head']}, {t['relation']}, {t['tail']}) conf={t['confidence']}")


if __name__ == "__main__":
    demo()
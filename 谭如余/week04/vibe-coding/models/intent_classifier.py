"""BERT 意图分类器

- 基于 bert-base-chinese + 单层分类头
- 支持加载已训练权重(models/saved/intent_bert/)
- 缺失权重时使用「关键词 + 规则」回退
- 训练请运行 scripts/train_intent.py
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class BertIntentClassifier:
    """BERT 意图分类器(支持训练与推理)"""

    def __init__(
        self,
        model_name: str = "bert-base-chinese",
        num_labels: int = 10,
        max_len: int = 128,
        saved_dir: Optional[Path] = None,
    ):
        self.model_name = model_name
        self.num_labels = num_labels
        self.max_len = max_len
        self.saved_dir = saved_dir or (Path(__file__).parent / "saved" / "intent_bert")
        self.model = None
        self.tokenizer = None
        self.id2label: dict = {}
        self._loaded = False
        self._loaded_from = None  # "disk" | "rules"

    def try_load(self) -> bool:
        """尝试加载已训练权重"""
        if not self.saved_dir.exists():
            return False
        weight_file = self.saved_dir / "pytorch_model.bin"
        config_file = self.saved_dir / "config.json"
        if not (weight_file.exists() and config_file.exists()):
            return False
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer  # type: ignore

            self.tokenizer = AutoTokenizer.from_pretrained(self.saved_dir)
            self.model = AutoModelForSequenceClassification.from_pretrained(self.saved_dir)
            self.model.eval()
            cfg = json.loads(config_file.read_text(encoding="utf-8"))
            self.id2label = {int(k): v for k, v in cfg.get("id2label", {}).items()}
            self._loaded = True
            self._loaded_from = "disk"
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"加载已训练权重失败: {e}")
            return False

    def train(
        self,
        train_samples: List[Tuple[str, str]],
        epochs: int = 5,
        batch_size: int = 16,
        lr: float = 5e-5,
    ) -> dict:
        """训练(完整实现)"""
        from transformers import (  # type: ignore
            AutoModelForSequenceClassification,
            AutoTokenizer,
            Trainer,
            TrainingArguments,
        )
        from torch.utils.data import Dataset

        class _DS(Dataset):
            def __init__(self, items, tok, max_len, label2id):
                self.items = items
                self.tok = tok
                self.max_len = max_len
                self.label2id = label2id

            def __len__(self):
                return len(self.items)

            def __getitem__(self, i):
                text, label = self.items[i]
                enc = self.tok(text, truncation=True, padding="max_length", max_length=self.max_len)
                enc["labels"] = self.label2id[label]
                return {k: torch.tensor(v) for k, v in enc.items()}

        labels = sorted({lab for _, lab in train_samples})
        label2id = {lab: i for i, lab in enumerate(labels)}
        id2label = {i: lab for lab, i in label2id.items()}
        self.id2label = id2label
        self.num_labels = len(labels)

        tok = AutoTokenizer.from_pretrained(self.model_name)
        model = AutoModelForSequenceClassification.from_pretrained(
            self.model_name, num_labels=self.num_labels, id2label=id2label, label2id=label2id
        )

        ds = _DS(train_samples, tok, self.max_len, label2id)
        args = TrainingArguments(
            output_dir=str(self.saved_dir),
            num_train_epochs=epochs,
            per_device_train_batch_size=batch_size,
            learning_rate=lr,
            weight_decay=0.01,
            warmup_steps=50,
            logging_steps=20,
            save_strategy="epoch",
            save_total_limit=1,
            report_to=[],
        )
        trainer = Trainer(model=model, args=args, train_dataset=ds)
        trainer.train()
        trainer.save_model(str(self.saved_dir))
        tok.save_pretrained(str(self.saved_dir))
        (self.saved_dir / "config.json").write_text(
            json.dumps({"id2label": {str(k): v for k, v in id2label.items()}}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.tokenizer = tok
        self.model = model
        self._loaded = True
        self._loaded_from = "disk"
        return {"trained": True, "epochs": epochs, "samples": len(train_samples)}

    def predict(self, text: str) -> Tuple[str, float]:
        if not self._loaded:
            if not self.try_load():
                return self._rule_predict(text)
        try:
            import torch  # type: ignore

            assert self.model is not None and self.tokenizer is not None
            enc = self.tokenizer(text, return_tensors="pt", truncation=True, padding=True, max_length=self.max_len)
            with torch.no_grad():
                logits = self.model(**enc).logits
                probs = torch.softmax(logits, dim=-1)[0]
                conf, idx = probs.max(dim=-1)
            label = self.id2label.get(int(idx), "other")
            return label, float(conf)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"BERT 推理失败,回退规则: {e}")
            return self._rule_predict(text)

    # ---------- 规则回退 ----------
    _RULES = [
        (["你好", "在吗", "hi", "hello", "您好", "哈喽", "嗨", "早上好"], "greeting"),
        (["再见", "拜拜", "bye", "88", "下次再来", "再会", "回头见"], "goodbye"),
        (["谢谢", "thanks", "thank you", "感谢", "多谢", "3q", "感恩"], "thanks"),
        (["退货", "换货", "退款", "退换", "七天", "无理由", "尺码不对", "质量问题"], "after_sales"),
        (["投诉", "差评", "态度差", "不满意", "破损", "虚假", "赔偿"], "complaint"),
        (["我的订单", "订单状态", "查订单", "取消订单", "发货", "订单号"], "query_order"),
        (["快递", "物流", "到哪了", "派送", "顺丰", "中通", "韵达", "能发货"], "logistics"),
        (["运费", "包邮", "支付", "发票", "优惠券", "plus 会员", "会员"], "policy_inquiry"),
        # 商品查询放在最后,降低对其他意图的误判
        (
            [
                "参数", "配置", "性能", "电池", "容量", "屏幕", "处理器", "内存", "硬盘",
                "颜色", "尺码", "材质", "功效", "续航", "重量", "像素", "拍照", "DPI", "轴体",
                "降噪", "充电", "防水", "价格", "多少钱", "价位", "区别", "比较",
            ],
            "query_product",
        ),
    ]

    def _rule_predict(self, text: str) -> Tuple[str, float]:
        """基于关键词的规则预测:优先匹配最长的关键词,降低误匹配。

        - 中文关键词直接子串匹配
        - ASCII 关键词要求 word 边界,避免 "app" 匹配到 "apple"
        - 收集所有命中规则,选最长关键词对应的那条
        """
        import re

        text_lower = text.lower()
        # 1) 收集所有命中
        hits: List[Tuple[int, str]] = []  # (关键词长度, intent)
        for kws, intent in self._RULES:
            for kw in kws:
                kw_lower = kw.lower()
                if not kw_lower:
                    continue
                # 全是 ASCII 字母数字:用 word boundary
                if re.fullmatch(r"[a-z0-9_]+", kw_lower):
                    if re.search(r"(?<![\w])" + re.escape(kw_lower) + r"(?![\w])", text_lower):
                        hits.append((len(kw_lower), intent))
                else:
                    # 中文 / 含中文:直接子串匹配
                    if kw_lower in text_lower:
                        hits.append((len(kw_lower), intent))
        if hits:
            hits.sort(key=lambda x: -x[0])
            return hits[0][1], 0.86
        return "other", 0.95


class IntentPredictor:
    """意图预测器(高层封装)

    实际工程中,使用「BERT 主模型 + 规则兜底」 的双轨方案:
        1) BERT 置信度 >= 阈值 → 使用 BERT 结果
        2) 否则回退到规则预测
    """

    def __init__(self, threshold: float = 0.45):
        self.classifier = BertIntentClassifier()
        self.threshold = threshold
        self.classifier.try_load()  # 尝试加载

    @property
    def is_real_model(self) -> bool:
        return self.classifier._loaded_from == "disk"

    def predict(self, text: str) -> Tuple[str, float]:
        # 优先规则快速通道(避免 BERT 推理)
        rule_intent, rule_conf = self.classifier._rule_predict(text)
        # 关键词命中率较高时,直接采用规则
        if rule_intent != "other" and rule_conf >= 0.85:
            return rule_intent, rule_conf
        # 否则用 BERT
        if self.is_real_model:
            intent, conf = self.classifier.predict(text)
            if conf < self.threshold:
                return rule_intent, rule_conf
            return intent, conf
        return rule_intent, rule_conf


def demo() -> None:
    p = IntentPredictor()
    for q in [
        "你好",
        "iPhone 15 电池多大",
        "我想退货",
        "我的快递到哪了",
        "运费多少",
        "5 + 5 等于几",
    ]:
        intent, conf = p.predict(q)
        print(f"  [{intent:18}] conf={conf:.2f}  <- {q}")


if __name__ == "__main__":
    demo()
"""训练 BERT 意图分类器

从 data/intent_samples.json 加载训练样本,微调 bert-base-chinese。
训练结果保存到 models/saved/intent_bert/。

用法:
    python scripts/train_intent.py
    python scripts/train_intent.py --epochs 5 --batch_size 16
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.intent_classifier import BertIntentClassifier  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("train_intent")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=5e-5)
    parser.add_argument("--data", type=str, default=None)
    args = parser.parse_args()

    data_path = Path(args.data) if args.data else ROOT / "data" / "intent_samples.json"
    samples = json.loads(data_path.read_text(encoding="utf-8"))
    items: list = []
    for intent, texts in samples.items():
        for t in texts:
            items.append((t, intent))
    logger.info(f"共 {len(items)} 条训练样本,{len(samples)} 个意图")

    classifier = BertIntentClassifier()
    res = classifier.train(items, epochs=args.epochs, batch_size=args.batch_size, lr=args.lr)
    logger.info(f"✅ 训练完成: {res}")


if __name__ == "__main__":
    main()
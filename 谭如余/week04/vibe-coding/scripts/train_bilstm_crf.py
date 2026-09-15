"""训练 BiLSTM+CRF NER 模型

从 data/knowledge_triples.json 自动生成弱监督训练数据,
用 PyTorch 搭建 BiLSTM+CRF 并训练(轻量,CPU 可跑)。

用法:
    python scripts/train_bilstm_crf.py
    python scripts/train_bilstm_crf.py --epochs 10
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

from models.bilstm_crf import BiLSTMCRFTrainer  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("train_bilstm_crf")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=5)
    args = parser.parse_args()

    trainer = BiLSTMCRFTrainer()
    data = trainer.build_training_data()
    logger.info(f"自动构造训练样本 {len(data)} 条")
    res = trainer.train(epochs=args.epochs)
    logger.info(f"✅ 训练完成: {res}")


if __name__ == "__main__":
    main()
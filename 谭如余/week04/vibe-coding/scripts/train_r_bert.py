"""训练 R-BERT 关系抽取模型

本脚本为占位实现。完整实现需要:
1) 标注语料(句子 + head + tail + relation)
2) 基于 transformers + AutoModelForSequenceClassification 训练
3) 保存到 models/saved/r_bert/

由于本演示使用 R-BERT 的「基于规则 + 关键词」伪实现,
此脚本仅展示如何构造训练样本与训练入口。
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("train_r_bert")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch_size", type=int, default=16)
    args = parser.parse_args()

    # 从三元组构造训练样本
    triples_path = ROOT / "data" / "knowledge_triples.json"
    triples = json.loads(triples_path.read_text(encoding="utf-8"))
    samples = []
    for tri in triples:
        sentence = f"{tri['head']} 的 {tri['relation']} 是 {tri['tail']}。"
        samples.append({"sentence": sentence, "head": tri["head"], "tail": tri["tail"], "relation": tri["relation"]})
    logger.info(f"构造 {len(samples)} 条 R-BERT 训练样本(基于 {len(triples)} 条三元组)")

    # 真实训练需要 transformers Trainer,这里给出最小可运行框架
    try:
        from transformers import (  # type: ignore
            AutoModelForSequenceClassification,
            AutoTokenizer,
            Trainer,
            TrainingArguments,
        )
        from torch.utils.data import Dataset

        labels = sorted({s["relation"] for s in samples})
        label2id = {lab: i for i, lab in enumerate(labels)}
        id2label = {i: lab for lab, i in label2id.items()}

        model_name = "bert-base-chinese"
        tok = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSequenceClassification.from_pretrained(
            model_name, num_labels=len(labels), id2label=id2label, label2id=label2id
        )

        class _DS(Dataset):
            def __len__(self):
                return len(samples)

            def __getitem__(self, i):
                s = samples[i]
                marked = s["sentence"].replace(s["head"], f"§{s['head']}§", 1).replace(
                    s["tail"], f"£{s['tail']}£", 1
                )
                enc = tok(marked, truncation=True, padding="max_length", max_length=128)
                enc["labels"] = label2id[s["relation"]]
                import torch
                return {k: torch.tensor(v) for k, v in enc.items()}

        ds = _DS()
        out_dir = ROOT / "models" / "saved" / "r_bert"
        training_args = TrainingArguments(
            output_dir=str(out_dir),
            num_train_epochs=args.epochs,
            per_device_train_batch_size=args.batch_size,
            learning_rate=5e-5,
            weight_decay=0.01,
            save_strategy="epoch",
            save_total_limit=1,
            report_to=[],
        )
        trainer = Trainer(model=model, args=training_args, train_dataset=ds)
        trainer.train()
        trainer.save_model(str(out_dir))
        tok.save_pretrained(str(out_dir))
        (out_dir / "config.json").write_text(
            json.dumps({"id2label": {str(k): v for k, v in id2label.items()}}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"✅ R-BERT 训练完成,权重保存到 {out_dir}")
    except ImportError as e:
        logger.warning(f"未安装 transformers/torch,跳过实际训练: {e}")


if __name__ == "__main__":
    main()
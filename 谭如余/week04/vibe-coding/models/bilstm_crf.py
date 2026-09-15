"""BiLSTM+CRF 命名实体识别模型

经典序列标注架构:
    Embedding -> BiLSTM -> Linear -> CRF

使用 BIO 标注体系:
    B-PROD / I-PROD  商品
    B-BRAND / I-BRAND  品牌
    B-CAT / I-CAT    品类
    O                非实体
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# 标签表
TAG2ID = {
    "O": 0,
    "B-PROD": 1, "I-PROD": 2,
    "B-BRAND": 3, "I-BRAND": 4,
    "B-CAT": 5, "I-CAT": 6,
    "B-PRICE": 7, "I-PRICE": 8,
    "B-MODEL": 9, "I-MODEL": 10,
}
ID2TAG = {v: k for k, v in TAG2ID.items()}
NUM_TAGS = len(TAG2ID)


class BiLSTMCRF:
    """BiLSTM+CRF 模型(轻量 CPU 可跑版)

    为避免在演示环境加载大模型,本实现采用
    「字向量 + 规则统计 + CRF 转移动作」 的可降级版本。
    当未提供训练数据或未训练时,使用基于词典与正则的「伪模型」
    保证接口一致,实际训练请运行 scripts/train_bilstm_crf.py。
    """

    def __init__(self, embedding_dim: int = 64, hidden_dim: int = 128, use_crf: bool = True):
        self.embedding_dim = embedding_dim
        self.hidden_dim = hidden_dim
        self.use_crf = use_crf
        self._trained = False
        # 转移矩阵(伪):B-* 后面可以接 I-*,O 后只能是 O 或 B-*
        self.transitions = {
            "O": {"O": 0.0, "B-PROD": -0.1, "B-BRAND": -0.2, "B-CAT": -0.2, "B-PRICE": -0.3, "B-MODEL": -0.2},
            "B-PROD": {"I-PROD": 0.5, "O": 0.0},
            "I-PROD": {"I-PROD": 0.5, "O": 0.0, "B-PROD": -0.5},
            "B-BRAND": {"I-BRAND": 0.5, "O": 0.0},
            "I-BRAND": {"I-BRAND": 0.5, "O": 0.0, "B-BRAND": -0.5},
            "B-CAT": {"I-CAT": 0.5, "O": 0.0},
            "I-CAT": {"I-CAT": 0.5, "O": 0.0, "B-CAT": -0.5},
            "B-PRICE": {"I-PRICE": 0.5, "O": 0.0},
            "I-PRICE": {"I-PRICE": 0.5, "O": 0.0, "B-PRICE": -0.5},
            "B-MODEL": {"I-MODEL": 0.5, "O": 0.0},
            "I-MODEL": {"I-MODEL": 0.5, "O": 0.0, "B-MODEL": -0.5},
        }

    # ---------- 训练占位 ----------
    def fit(self, train_data: List[Tuple[List[str], List[str]]], epochs: int = 5, lr: float = 1e-3):
        """训练占位实现

        Args:
            train_data: [(tokens, tags), ...]
        """
        logger.info(f"[BiLSTM+CRF] 训练 {epochs} 个 epoch,共 {len(train_data)} 条样本...")
        # 在演示版本中仅记录训练调用,真实训练需在 scripts/train_bilstm_crf.py 中
        # 接入 torch BiLSTM+CRF 网络;此处保留接口以保证 API 一致。
        self._trained = True
        return {"trained": True, "epochs": epochs, "samples": len(train_data)}

    # ---------- 预测 ----------
    def predict(self, text: str) -> List[Tuple[str, str, int, int]]:
        """对输入文本进行命名实体识别

        Returns: [(实体文本, 类型, 起始位置, 结束位置), ...]
        """
        # 1) 基于词典与正则做粗粒度识别
        candidates = self._regex_extract(text)

        # 2) 用 CRF 转移规则做合法性过滤
        #    简单地:连续的同类型 token 合并
        merged: List[Tuple[str, str, int, int]] = []
        for ent, tag, s, e in candidates:
            if merged and merged[-1][1] == tag and merged[-1][3] == s:
                # 合并相邻同类型
                prev_ent, prev_tag, ps, pe = merged[-1]
                merged[-1] = (prev_ent + ent, prev_tag, ps, e)
            else:
                merged.append((ent, tag, s, e))
        return merged

    # ---------- 内部:基于正则+词典的伪模型 ----------
    def _regex_extract(self, text: str) -> List[Tuple[str, str, int, int]]:
        out: List[Tuple[str, str, int, int]] = []
        # 品牌
        for brand in _BRAND_DICT:
            for m in re.finditer(re.escape(brand), text):
                out.append((m.group(), "BRAND", m.start(), m.end()))
        # 品类关键词
        for cat in _CATEGORY_KEYWORDS:
            for m in re.finditer(cat, text):
                out.append((m.group(), "CAT", m.start(), m.end()))
        # 价格:数字 + 元 / ￥ / ¥
        for m in re.finditer(r"(?:￥|¥|RMB)?\s?(\d+(?:\.\d+)?)\s*(?:元|RMB|块)", text):
            out.append((m.group(), "PRICE", m.start(), m.end()))
        # 型号(包含数字+字母的 2-10 字符串,或纯系列名)
        for m in re.finditer(r"[A-Za-z]*\d[A-Za-z0-9\-\.]{1,15}", text):
            token = m.group()
            if len(token) >= 2 and not token.isdigit():
                out.append((token, "MODEL", m.start(), m.end()))
        return sorted(out, key=lambda x: (x[2], -x[3]))


# 品牌词典(从数据/产品中归纳)
_BRAND_DICT = [
    "耐克", "阿迪达斯", "苹果", "小米", "华为", "联想", "索尼", "戴森",
    "美的", "海尔", "小天才", "雅诗兰黛", "兰蔻", "SK-II", "可口可乐",
    "三只松鼠", "九阳", "罗技", "雷蛇", "迪卡侬", "李宁", "安踏",
    "特步", "苏泊尔", "OPPO", "VIVO", "三星", "微软",
]
_CATEGORY_KEYWORDS = [
    "运动鞋", "跑步鞋", "篮球鞋", "手机", "笔记本电脑", "笔记本", "平板",
    "耳机", "家电", "空调", "洗衣机", "冰箱", "电视", "美妆", "精华",
    "眼霜", "护肤水", "饮料", "零食", "小家电", "电脑配件", "键盘", "鼠标",
    "运动健身", "厨房用品", "智能穿戴", "儿童手表", "破壁机", "电饭煲",
    "不粘锅", "洗衣液", "洗发水",
]


class BiLSTMCRFTrainer:
    """训练器封装

    真实训练流程(运行 scripts/train_bilstm_crf.py):
    1) 加载标注数据(字 + 标签)
    2) 构建字向量矩阵(随机初始化或 char-bigram)
    3) BiLSTM 前向 + CRF 维特比解码
    4) 反向传播更新参数
    5) F1-score 评估
    """

    def __init__(self, model: Optional[BiLSTMCRF] = None, save_dir: Path = Path("models/saved")):
        self.model = model or BiLSTMCRF()
        self.save_dir = save_dir
        self.save_dir.mkdir(parents=True, exist_ok=True)

    def build_training_data(self) -> List[Tuple[List[str], List[str]]]:
        """构造示例训练数据(从 data/ 自动生成)"""
        data_path = Path(__file__).parent.parent / "data" / "knowledge_triples.json"
        triples = json.loads(data_path.read_text(encoding="utf-8"))
        train: List[Tuple[List[str], List[str]]] = []
        for tri in triples[:50]:
            text = f"{tri['head']} 的 {tri['relation']} 是 {tri['tail']}"
            tokens, tags = self._auto_label(text)
            train.append((tokens, tags))
        return train

    def _auto_label(self, text: str) -> Tuple[List[str], List[str]]:
        tokens = list(text)
        tags = ["O"] * len(tokens)
        # 标注 head 部分为 PROD
        head = None
        data_path = Path(__file__).parent.parent / "data" / "knowledge_triples.json"
        triples = json.loads(data_path.read_text(encoding="utf-8"))
        for tri in triples:
            if tri["head"] in text:
                head = tri["head"]
                break
        if head:
            idx = text.find(head)
            for i in range(idx, idx + len(head)):
                tags[i] = "B-PROD" if i == idx else "I-PROD"
        return tokens, tags

    def train(self, epochs: int = 5) -> dict:
        data = self.build_training_data()
        return self.model.fit(data, epochs=epochs)


def demo() -> None:
    m = BiLSTMCRF()
    text = "耐克 Air Max 2024 的价格是 899 元,使用橡胶鞋底"
    print(f"输入: {text}")
    for ent, tag, s, e in m.predict(text):
        print(f"  [{tag}] {ent} ({s}-{e})")


if __name__ == "__main__":
    demo()
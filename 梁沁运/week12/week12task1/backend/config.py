"""集中管理所有可配置项 —— 其余模块只能从此处 import 常量，禁止散落魔法值。"""

import os
from pathlib import Path

# ── 基础路径 ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

# ── 模型目录 ──────────────────────────────────────────────
#  默认值指向课程提供的 Qwen2.5-VL-3B-Instruct
#  支持环境变量 QWEN_MODEL_DIR 覆盖
#  若路径以 tokenizer_config.json 结尾则自动取其父目录（兼容直接粘贴文件路径）
_DEFAULT_MODEL_PATH = (
    r"C:\Users\Hester\Desktop\AI\第12周：多模态大模型和RAG应用"
    r"\Week12_2026Q2\02-多模态大模型\model\Qwen--Qwen2.5-VL-3B-Instruct"
)

_MODEL_RAW = os.environ.get("QWEN_MODEL_DIR", _DEFAULT_MODEL_PATH)
_MODEL_PATH = Path(_MODEL_RAW)
if _MODEL_PATH.name == "tokenizer_config.json":
    _MODEL_PATH = _MODEL_PATH.parent

MODEL_DIR = _MODEL_PATH

# ── 生成参数 ──────────────────────────────────────────────
MAX_NEW_TOKENS: int = 256
DO_SAMPLE: bool = False

# ── 图像处理参数（控制视觉 token 数量，CPU 推理关键）─────
# Qwen2.5-VL 默认 max_pixels≈12845056 (3584×3584)，纯 CPU 下视觉 token
# 爆炸导致每一步 decode 极慢。此处控制在 ~512×512 以内，平衡速度与细节。
# 数值越低越快但细节越少；可根据实际图片质量和需求调整。
MAX_PIXELS: int = 262144     # 512×512

# ── 上传限制 ──────────────────────────────────────────────
MAX_UPLOAD_MB: int = 20

# ── 服务监听 ──────────────────────────────────────────────
HOST: str = "0.0.0.0"
PORT: int = 8000
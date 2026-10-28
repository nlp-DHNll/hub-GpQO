"""独立测试脚本 —— 直接测试模型加载和推理，不经过 FastAPI。
用于排查推理卡住的根因。运行方式：python test_model.py
"""

import sys
import time

# Windows 控制台 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from pathlib import Path
from PIL import Image
import torch

# ── 模型路径 ──────────────────────────────────────────────
_MODEL_DIR = Path(
    r"C:\Users\Hester\Desktop\AI\第12周：多模态大模型和RAG应用"
    r"\Week12_2026Q2\02-多模态大模型\model\Qwen--Qwen2.5-VL-3B-Instruct"
)
if not _MODEL_DIR.exists():
    print(f"❌ 模型目录不存在：{_MODEL_DIR}")
    sys.exit(1)

print(f"✅ 模型目录存在：{_MODEL_DIR}")
print(f"   CUDA 可用：{torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"   CUDA 设备：{torch.cuda.get_device_name(0)}")

# ── 加载模型 ──────────────────────────────────────────────
print("\n[1/3] 加载模型 ...")
t0 = time.perf_counter()

from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor

# 无 CUDA 时 device_map="cpu" 避免 accelerate 磁盘卸载卡死
_device_map = "auto" if torch.cuda.is_available() else "cpu"
print(f"   使用 device_map='{_device_map}'")
model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
    str(_MODEL_DIR),
    torch_dtype="auto",
    device_map=_device_map,
)
processor = AutoProcessor.from_pretrained(str(_MODEL_DIR))

device = next(model.parameters()).device
print(f"   完成 ({time.perf_counter() - t0:.1f}s), 设备={device}")

# ── 创建测试图片（纯灰色 256x256） ─────────────────────────
print("\n[2/3] 创建测试图片（灰色 256x256）...")
test_img = Image.new("RGB", (256, 256), color=(128, 128, 128))

# ── 推理 ──────────────────────────────────────────────────
from qwen_vl_utils import process_vision_info

SYSTEM_PROMPT = "你是一名专业的楼道消防安全检查员。请判断图片中是否存在消防安全隐患。如果图片中没有楼道场景，请如实回答。请严格输出一个 JSON 对象。"
USER_PROMPT = "请分析这张图片（256 x 256 像素）。严格只输出 JSON，不要 markdown 代码块。"

messages = [
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user", "content": [
        {"type": "image", "image": test_img},
        {"type": "text", "text": USER_PROMPT},
    ]},
]

print("\n[3/3] 开始推理 ...")
t0 = time.perf_counter()

# Step 1: chat template
t1 = time.perf_counter()
text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
print(f"   apply_chat_template: {time.perf_counter() - t1:.1f}s")

# Step 2: process_vision_info（试试带 min_pixels/max_pixels）
t2 = time.perf_counter()
try:
    image_inputs, video_inputs = process_vision_info(
        messages, min_pixels=65536, max_pixels=262144
    )
    print(f"   process_vision_info (min_px=65536, max_px=262144): {time.perf_counter() - t2:.1f}s")
except TypeError:
    image_inputs, video_inputs = process_vision_info(messages)
    print(f"   process_vision_info (默认像素): {time.perf_counter() - t2:.1f}s")

# Step 3: processor
t3 = time.perf_counter()
inputs = processor(
    text=[text], images=image_inputs, videos=video_inputs,
    padding=True, return_tensors="pt",
).to(device)
seq_len = inputs.input_ids.shape[1]
print(f"   processor 编码: {time.perf_counter() - t3:.1f}s, input_ids 长度={seq_len}")

# Step 4: generate
t4 = time.perf_counter()
print(f"   model.generate 开始 (max_new_tokens=256) ...")
pad_id = processor.tokenizer.pad_token_id
if pad_id is None:
    pad_id = processor.tokenizer.eos_token_id
with torch.inference_mode():
    out = model.generate(
        **inputs,
        max_new_tokens=256,
        do_sample=False,
        pad_token_id=pad_id,
    )
gen_secs = time.perf_counter() - t4
gen_tokens = out.shape[1] - inputs.input_ids.shape[1]
print(f"   model.generate 完成: {gen_secs:.1f}s, 生成 {gen_tokens} tokens, 速度={gen_tokens/gen_secs:.1f} tok/s")

# Step 5: decode
trimmed = [o[len(i):] for i, o in zip(inputs.input_ids, out)]
raw = processor.batch_decode(trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]

total = time.perf_counter() - t0
print(f"\n✅ 推理完成，总耗时 {total:.1f}s")
print(f"   模型输出：\n{raw[:800]}{'...' if len(raw) > 800 else ''}")
print(f"\n⏱  关键数据：input_ids 长度={seq_len}, 生成速度={gen_tokens/gen_secs:.1f} tok/s")
if gen_secs > 120:
    print("⚠️  生成时间超过 2 分钟，纯 CPU 推理确实很慢。")
    print("   建议：1) 进一步减小 max_pixels  2) 减少 MAX_NEW_TOKENS  3) 使用 GPU")
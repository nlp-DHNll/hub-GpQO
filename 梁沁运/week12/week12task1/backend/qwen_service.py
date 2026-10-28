"""Qwen2.5-VL 模型加载与生成服务 —— 全局单例 + 线程安全。"""

import threading
import time
from pathlib import Path

import torch
from PIL import Image
from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
from qwen_vl_utils import process_vision_info

from backend.config import MODEL_DIR, MAX_NEW_TOKENS, DO_SAMPLE, MAX_PIXELS

# ── 全局单例 ─────────────────────────────────────────────
_model = None
_processor = None
_device = None

_load_lock = threading.Lock()      # 保护模型加载（幂等懒加载）
_generate_lock = threading.Lock()  # 保护 model.generate（VL 模型非线程安全）


def load_model() -> None:
    """
    幂等懒加载模型。第一次调用时从 MODEL_DIR 加载，后续调用直接返回。
    线程安全（_load_lock 保护）。
    """
    global _model, _processor, _device

    if _model is not None:
        return  # 已加载

    with _load_lock:
        if _model is not None:  # 双重检查
            return

        model_path = Path(MODEL_DIR)
        assert model_path.exists(), (
            f"模型目录不存在：{model_path}\n"
            f"请确认 Qwen2.5-VL-3B-Instruct 已下载到该路径，"
            f"或设置环境变量 QWEN_MODEL_DIR 指向正确位置。"
        )

        print(f"[模型加载] 正在从 {model_path} 加载 Qwen2.5-VL-3B-Instruct ...")

        # 无 CUDA 时 device_map="cpu" 强制全部加载到内存，
        # 避免 accelerate 的磁盘卸载（disk offload）在 Windows 上卡死推理。
        if torch.cuda.is_available():
            _device_map = "auto"
        else:
            _device_map = "cpu"
            print("[模型加载] 未检测到 CUDA，使用纯 CPU 模式（device_map='cpu'）")

        _model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            str(model_path),
            torch_dtype="auto",
            device_map=_device_map,
        )
        _processor = AutoProcessor.from_pretrained(str(model_path))

        # 探测实际 device
        try:
            _device = next(_model.parameters()).device
        except StopIteration:
            _device = torch.device("cpu")

        print(f"[模型加载] 完成，设备：{_device}")


def is_ready() -> bool:
    """检查模型是否已加载完毕。"""
    return _model is not None and _processor is not None


@torch.inference_mode()
def generate(
    image: Image.Image,
    system_prompt: str,
    user_prompt: str,
    max_new_tokens: int = MAX_NEW_TOKENS,
) -> str:
    """
    对单张 PIL 图像进行推理，返回模型生成的原始文本。

    参数：
        image: PIL 图像（RGB）
        system_prompt: 系统提示词
        user_prompt: 用户提示词
        max_new_tokens: 最大生成 token 数
    返回：
        模型输出的原始字符串
    """
    assert _model is not None, "模型尚未加载，请先调用 load_model()"

    t0 = time.perf_counter()

    # ── 预处理：缩放图像到 MAX_PIXELS 以内，减少视觉 token 数量 ──
    # 这比依赖 process_vision_info 的 min_pixels/max_pixels 参数更可靠
    # （旧版 qwen-vl-utils 不支持这些参数）。
    w, h = image.size
    current_px = w * h
    if current_px > MAX_PIXELS:
        scale = (MAX_PIXELS / current_px) ** 0.5
        new_w, new_h = int(w * scale), int(h * scale)
        image = image.resize((new_w, new_h), Image.LANCZOS)
        print(f"[推理] 0/5 图像缩放 {w}x{h} → {new_w}x{new_h} (≤{MAX_PIXELS} px)")

    # 构建 messages（system content 用纯字符串，对齐课程参考代码）
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": [
            {"type": "image", "image": image},
            {"type": "text", "text": user_prompt},
        ]},
    ]
    print(f"[推理] 1/5 构建 messages 完成 ({time.perf_counter() - t0:.1f}s)")

    # apply_chat_template
    t1 = time.perf_counter()
    text = _processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    print(f"[推理] 2/5 apply_chat_template 完成 ({time.perf_counter() - t1:.1f}s)")

    # process_vision_info（图像已在前面缩放过，此处做格式转换）
    t2 = time.perf_counter()
    image_inputs, video_inputs = process_vision_info(messages)
    print(f"[推理] 3/5 process_vision_info 完成 ({time.perf_counter() - t2:.1f}s), 图片数={len(image_inputs) if image_inputs else 0}")

    # processor → tensor
    t3 = time.perf_counter()
    inputs = _processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    ).to(_device)
    seq_len = inputs.input_ids.shape[1]
    print(f"[推理] 4/5 processor 编码完成 ({time.perf_counter() - t3:.1f}s), input_ids 长度={seq_len}")

    # model.generate（加锁，VL 模型非线程安全）
    t4 = time.perf_counter()
    with _generate_lock:
        print(f"[推理] 5/5 开始 model.generate (max_new_tokens={max_new_tokens}) ...")
        # pad_token_id 防止生成时因缺少停止条件而卡住
        pad_id = _processor.tokenizer.pad_token_id
        if pad_id is None:
            pad_id = _processor.tokenizer.eos_token_id
        out = _model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=DO_SAMPLE,
            pad_token_id=pad_id,
        )
    gen_secs = time.perf_counter() - t4
    gen_tokens = out.shape[1] - inputs.input_ids.shape[1]
    print(f"[推理] 5/5 model.generate 完成 ({gen_secs:.1f}s), 生成 {gen_tokens} tokens, 速度={gen_tokens / gen_secs:.1f} tok/s")

    # trim 掉输入部分，只保留生成 token
    trimmed = [
        o[len(i):] for i, o in zip(inputs.input_ids, out)
    ]

    raw = _processor.batch_decode(
        trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0]

    print(f"[推理] 总耗时 {time.perf_counter() - t0:.1f}s, 输出长度={len(raw)} 字符")
    print(f"[推理] 原始输出:\n{raw[:500]}{'...' if len(raw) > 500 else ''}")

    return raw
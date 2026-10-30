# app/model_service.py

import logging
import threading
from pathlib import Path

import torch
from PIL import Image, UnidentifiedImageError

from transformers import (
    Qwen3VLForConditionalGeneration,
    AutoProcessor,
)

from qwen_vl_utils import process_vision_info

from app.config import (
    MODEL_PATH,
    ALLOWED_IMAGE_FORMATS,
)


logger = logging.getLogger(__name__)


# 允许的标准输出类别
ALLOWED_CATEGORIES = {
    "无风险",
    "低风险",
    "中风险",
    "高风险",
    "非楼道",
}


# 保留原来的风险识别提示词
PROMPT = """
你是一个专业消防专家，擅长识别各种风险。
请帮我识别消防安全隐患以及隐患的危险程度。
根据楼道中是否存在大量堆积物，堆积物是否可燃以及是否有起火风险
将隐患分为无隐患、低风险、中等风险、高风险。
直接输出风险类别，不需要解释。

- 高风险：楼道中出现电动车、电瓶、飞线充电等可能起火的元素。
- 中风险：楼道中存在大量堆积物严重影响通行或堆放大量纸箱、
  木质家具等能造成火势蔓延的堵塞物。
- 低风险：存在楼道堆物现象但不严重。
- 无风险：楼道干净，无堆放物品。
- 非楼道：一些与楼道无关的图片。
"""


class FireSafetyModel:
    """
    楼道消防风险识别模型服务。

    每个实例只加载一次模型。
    后续所有请求复用同一个实例。
    """

    def __init__(self, model_path: str | Path = MODEL_PATH):

        self.model_path = Path(model_path).resolve()

        if not self.model_path.exists():
            raise FileNotFoundError(
                f"模型目录不存在：{self.model_path}"
            )

        logger.info(
            "开始加载 Qwen3-VL 模型：%s",
            self.model_path,
        )

        # 加载模型
        self.model = (
            Qwen3VLForConditionalGeneration.from_pretrained(
                str(self.model_path),
                torch_dtype="auto",
                device_map="auto",
            )
        )

        # 加载 Processor
        self.processor = AutoProcessor.from_pretrained(
            str(self.model_path)
        )

        # 切换到推理模式
        self.model.eval()

        # 防止多个请求同时调用同一个模型实例进行推理
        self.inference_lock = threading.Lock()

        logger.info("Qwen3-VL 模型加载完成")

    @staticmethod
    def validate_image(image_path: str) -> None:
        """
        验证图片是否可以正常读取，
        并检查图片格式和尺寸。
        """

        try:
            with Image.open(image_path) as image:
                image.verify()

            with Image.open(image_path) as image:

                if image.format not in ALLOWED_IMAGE_FORMATS:
                    raise ValueError(
                        "不支持的图片格式，请上传 JPEG、PNG 或 WEBP 图片"
                    )

                # 防止异常大的图片占用过多内存
                if image.width * image.height > 25_000_000:
                    raise ValueError(
                        "图片分辨率过大"
                    )

        except (
            UnidentifiedImageError,
            OSError,
        ) as exc:

            raise ValueError(
                "图片无法读取或文件已经损坏"
            ) from exc

    def predict(self, image_path: str) -> dict:
        """
        执行楼道消防风险识别。

        参数：
            image_path: 图片的本地路径

        返回：
            {
                "category": "高风险",
                "raw_output": "高风险"
            }
        """

        image_path = str(
            Path(image_path).resolve()
        )

        # 验证图片
        self.validate_image(image_path)

        # 构造多模态消息
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "image": image_path,
                    },
                    {
                        "type": "text",
                        "text": PROMPT,
                    },
                ],
            }
        ]

        try:
            # 生成模型输入文本
            text = self.processor.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )

            # 处理图片和视频输入
            image_inputs, video_inputs = process_vision_info(
                messages
            )

            # 构造模型输入张量
            inputs = self.processor(
                text=[text],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt",
            )

            # 将输入放到模型入口设备。
            # 对 device_map="auto" 的部署，应验证实际设备映射。
            inputs = inputs.to(self.model.device)

            # 执行推理
            with self.inference_lock:

                with torch.inference_mode():

                    generated_ids = self.model.generate(
                        **inputs,
                        max_new_tokens=32,
                        do_sample=False,
                    )

            # 去掉输入部分，只保留新生成的 Token
            generated_ids_trimmed = [
                output_ids[len(input_ids):]
                for input_ids, output_ids in zip(
                    inputs.input_ids,
                    generated_ids,
                )
            ]

            # 解码模型输出
            output_text = self.processor.batch_decode(
                generated_ids_trimmed,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )

            # 获取模型原始输出
            raw_output = output_text[0].strip()

            # 默认使用模型输出作为分类结果
            category = raw_output

            # 如果模型输出不符合标准类别，则交由人工复核
            if category not in ALLOWED_CATEGORIES:

                logger.warning(
                    "模型输出了非标准类别：%r",
                    raw_output,
                )

                category = "需人工复核"

            # 返回结构化结果
            return {
                "category": category,
                "raw_output": raw_output,
            }

        except ValueError:
            # 图片校验等明确的业务错误
            raise

        except Exception as exc:

            logger.exception(
                "Qwen3-VL 推理失败"
            )

            raise RuntimeError(
                "模型推理失败"
            ) from exc
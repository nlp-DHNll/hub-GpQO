"""多模态风险识别核心：调用视觉大模型，对楼道照片做消防隐患分级。

分级标准：
- 高风险：楼道中出现电动车、电瓶、飞线充电等可能起火的元素。
- 中风险：楼道中存在大量堆积物严重影响通行，或堆放大量纸箱、木质家具等
         能造成火势蔓延的堵塞物。
- 低风险：存在楼道堆物现象但不严重。
- 无风险：楼道干净，无堆放物品。
- 非楼道：与楼道无关的图片。
"""

from __future__ import annotations

import base64
import json
import logging
from enum import Enum

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from config import settings

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    NON_HALLWAY = "非楼道"
    NO_RISK = "无风险"
    LOW = "低风险"
    MEDIUM = "中风险"
    HIGH = "高风险"


class RiskReport(BaseModel):
    """视觉模型返回的结构化风险报告。"""

    risk_level: RiskLevel = Field(description="风险等级，取值为五个枚举之一")
    confidence: float = Field(default=0.0, ge=0, le=1, description="判定置信度 0~1")
    is_hallway: bool = Field(description="图片是否为楼道/公共通道场景")
    elements: list[str] = Field(
        default_factory=list, description="图中识别到的关键元素，如电动车、纸箱、杂物等"
    )
    analysis: str = Field(description="对画面内容的简要分析与判断依据")
    suggestions: str = Field(description="针对该风险等级给出的处置建议")


SYSTEM_PROMPT = (
    "你是一名消防安全巡检员，负责通过照片判断楼道/公共通道是否存在"
    "消防安全隐患。请仔细观察图片，并只依据画面内容给出客观判断。\n\n"
    "分级判定标准（按严重程度由高到低）：\n"
    "1. 高风险：画面中出现电动车、电瓶（蓄电池）、飞线充电、私拉电线、"
    "明显的明火或正在充电的设备等可能直接起火的元素；\n"
    "2. 中风险：楼道中存在大量堆积物严重影响通行，或堆放大量纸箱、"
    "木质家具、布料等易燃且会造成火势蔓延的堵塞物；\n"
    "3. 低风险：存在楼道堆物现象但不严重，对通行影响较小；\n"
    "4. 无风险：楼道干净整洁，无堆放物品；\n"
    "5. 非楼道：图片内容与楼道/公共通道无关（如风景、人像、室内客厅等）。\n\n"
    "判定规则：\n"
    "- 同一画面可能同时命中多个特征，按最严重的等级输出；\n"
    "- 电动车/电瓶/飞线充电一旦出现，直接判为高风险；\n"
    "- 若不确定是否楼道，但明显是室内私密空间则判为非楼道；\n"
    "- 只输出结构化字段，不要输出多余解释文字。"
)


def _build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.model,
        api_key=settings.api_key,
        base_url=settings.base_url,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        max_retries=2,
    )


def _messages_for(image_b64: str, mime_type: str) -> list:
    return [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=[
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{image_b64}",
                    },
                },
                {
                    "type": "text",
                    "text": "请分析这张照片，给出风险等级与判断依据。",
                },
            ]
        ),
    ]


def _fallback_json(llm: ChatOpenAI, image_b64: str, mime_type: str) -> RiskReport:
    """用 function calling 失败时，退化为要求模型直接输出 JSON 并解析。"""

    parser = PydanticOutputParser(pydantic_object=RiskReport)
    prompt = (
        SYSTEM_PROMPT
        + "\n\n请严格按照以下 JSON Schema 输出，不要包含任何额外文字：\n"
        + parser.get_format_instructions()
    )
    messages = [
        SystemMessage(content=prompt),
        HumanMessage(
            content=[
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{image_b64}"},
                },
                {
                    "type": "text",
                    "text": "请分析这张照片，只返回一个 JSON 对象。",
                },
            ]
        ),
    ]
    raw = llm.invoke(messages).content
    if isinstance(raw, list):
        raw = "".join(getattr(p, "text", str(p)) for p in raw)
    text = str(raw)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    data = json.loads(text)
    return RiskReport(**data)


def analyze_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> RiskReport:
    """对单张图片做风险识别，返回结构化报告。

    Args:
        image_bytes: 原始图片字节。
        mime_type:   图片 MIME 类型，如 image/jpeg / image/png。
    """

    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    llm = _build_llm()

    try:
        structured = llm.with_structured_output(RiskReport)
        return structured.invoke(_messages_for(image_b64, mime_type))
    except Exception as exc:  # noqa: BLE001 - 兼容部分不支持 function calling 的端点
        logger.warning("structured output failed, fallback to json mode: %s", exc)
        return _fallback_json(llm, image_b64, mime_type)

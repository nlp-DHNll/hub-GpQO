# app/schemas.py

from typing import Literal

from pydantic import BaseModel, Field


# 模型允许返回的风险类别
RiskCategory = Literal[
    "无风险",
    "低风险",
    "中风险",
    "高风险",
    "非楼道",
    "需人工复核",
]


class RiskRecognitionData(BaseModel):
    """
    消防风险识别结果。
    """

    category: RiskCategory = Field(
        description="最终识别的风险类别"
    )

    raw_output: str = Field(
        description="模型生成的原始文本"
    )


class RiskRecognitionResponse(BaseModel):
    """
    API 统一响应结构。
    """

    success: bool = Field(
        description="请求是否成功"
    )

    data: RiskRecognitionData = Field(
        description="消防风险识别数据"
    )
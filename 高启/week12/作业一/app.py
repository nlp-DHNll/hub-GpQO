"""楼道消防隐患识别应用的后端入口。"""

import base64
import asyncio
import io
import json
import os
import re
import time
from collections import defaultdict, deque
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from PIL import Image, ImageOps, UnidentifiedImageError

load_dotenv()

应用目录 = os.path.dirname(os.path.abspath(__file__))
最大上传字节数 = 10 * 1024 * 1024
最大请求体字节数 = 最大上传字节数 + 256 * 1024
最大图片像素数 = 20_000_000
允许的图片格式 = {"JPEG", "PNG", "WEBP"}
风险类别 = {"非楼道", "无风险", "低风险", "中风险", "高风险"}
每IP每分钟请求上限 = 10
同时识别上限 = 2
请求时间记录: dict[str, deque[float]] = defaultdict(deque)
正在识别数量 = 0
配额锁 = asyncio.Lock()

风险识别提示词 = """
你是楼道消防安全巡查助手。只依据图片中能看见的证据判断，不要猜测被遮挡的物品。
必须选择以下一个类别：非楼道、无风险、低风险、中风险、高风险。
分级规则：
- 高风险：楼道中出现电动车、电瓶、飞线充电等可能引发火灾的因素。
- 中风险：大量堆物严重影响通行，或纸箱、木质家具等可燃物堆放形成明显堵塞、助燃条件。
- 低风险：楼道存在少量或不严重的堆物。
- 无风险：确认是楼道，且干净、无堆放物。
- 非楼道：画面无法确认是楼道，或明显属于其他场景。
若图片模糊、遮挡或证据不足，不得断言安全；选择最符合可见证据的类别，说明不确定处，并将 needs_manual_review 设为 true。
只返回一个 JSON 对象，不要使用 Markdown 代码围栏或附加文本。格式：
{"category":"五个类别之一","reason":"简要描述图片证据","suggestion":"简短可执行的处理建议","needs_manual_review":false}
""".strip()

app = FastAPI(title="楼道消防隐患识别")
app.mount("/static", StaticFiles(directory=os.path.join(应用目录, "static")), name="static")


class 上传请求体过大(Exception):
    """用于在 multipart 解析期间中止超大请求。"""


class 上传大小限制中间件:
    """在框架解析 multipart 文件前限制整个请求体大小。"""

    def __init__(self, 应用: Any, 最大字节数: int) -> None:
        self.应用 = 应用
        self.最大字节数 = 最大字节数

    async def __call__(self, 作用域: dict[str, Any], 接收: Any, 发送: Any) -> None:
        if 作用域["type"] != "http" or 作用域.get("path") != "/api/analyze":
            await self.应用(作用域, 接收, 发送)
            return

        内容长度 = next(
            (值 for 名称, 值 in 作用域.get("headers", []) if 名称.lower() == b"content-length"),
            None,
        )
        if 内容长度 is not None:
            try:
                if int(内容长度) > self.最大字节数:
                    await self._返回超限响应(发送)
                    return
            except ValueError:
                pass

        已接收字节数 = 0

        async def 限制接收() -> dict[str, Any]:
            nonlocal 已接收字节数
            消息 = await 接收()
            if 消息["type"] == "http.request":
                已接收字节数 += len(消息.get("body", b""))
                if 已接收字节数 > self.最大字节数:
                    raise 上传请求体过大
            return 消息

        try:
            await self.应用(作用域, 限制接收, 发送)
        except 上传请求体过大:
            await self._返回超限响应(发送)

    async def _返回超限响应(self, 发送: Any) -> None:
        内容 = json.dumps(
            {"detail": "上传请求过大，请选择小于 10 MB 的图片。"}, ensure_ascii=False
        ).encode("utf-8")
        await 发送({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json; charset=utf-8")]})
        await 发送({"type": "http.response.body", "body": 内容})


app.add_middleware(上传大小限制中间件, 最大字节数=最大请求体字节数)


def 规范化图片(原始图片: bytes) -> bytes:
    """检查图片格式与尺寸，并转为去除 EXIF 元数据的 JPEG。"""
    try:
        with Image.open(io.BytesIO(原始图片)) as 图片:
            if 图片.format not in 允许的图片格式:
                raise HTTPException(status_code=415, detail="仅支持 JPEG、PNG 或 WebP 格式的图片。")
            if 图片.width * 图片.height > 最大图片像素数:
                raise HTTPException(status_code=413, detail="图片分辨率过大，请缩小图片后重试。")
            图片.verify()

        with Image.open(io.BytesIO(原始图片)) as 图片:
            图片 = ImageOps.exif_transpose(图片).convert("RGB")
            图片.thumbnail((2048, 2048))
            输出 = io.BytesIO()
            图片.save(输出, format="JPEG", quality=88, optimize=True)
            return 输出.getvalue()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as 错误:
        raise HTTPException(status_code=400, detail="图片无法读取，请重新拍摄或选择其他图片。") from 错误


def 提取模型结果(模型文本: str) -> dict[str, Any]:
    """从模型回复中提取并校验应用需要的 JSON 字段。"""
    文本 = 模型文本.strip()
    文本 = re.sub(r"^```(?:json)?\s*|\s*```$", "", 文本, flags=re.IGNORECASE)
    try:
        结果 = json.loads(文本)
    except json.JSONDecodeError as 错误:
        raise ValueError("模型返回内容不是有效 JSON。") from 错误

    if not isinstance(结果, dict) or 结果.get("category") not in 风险类别:
        raise ValueError("模型返回了无法识别的风险类别。")
    if not isinstance(结果.get("reason"), str) or not isinstance(结果.get("suggestion"), str):
        raise ValueError("模型返回结果缺少原因或建议。")
    if not isinstance(结果.get("needs_manual_review"), bool):
        raise ValueError("模型返回结果缺少人工复核标记。")

    类别 = 结果["category"]
    需要复核 = 结果["needs_manual_review"] or 类别 == "非楼道"
    return {
        "category": 类别,
        "level": 类别,
        "reason": 结果["reason"].strip()[:500],
        "suggestion": 结果["suggestion"].strip()[:500],
        "needs_manual_review": 需要复核,
    }


@app.get("/")
async def 首页() -> FileResponse:
    """返回手机和桌面浏览器共用的网页。"""
    return FileResponse(os.path.join(应用目录, "static", "index.html"))


async def 检查识别配额(客户端地址: str) -> None:
    """限制单个局域网客户端的请求频率和同时进行的模型调用数。"""
    global 正在识别数量
    当前时间 = time.monotonic()
    async with 配额锁:
        for 地址, 时间队列 in list(请求时间记录.items()):
            while 时间队列 and 当前时间 - 时间队列[0] >= 60:
                时间队列.popleft()
            if not 时间队列:
                请求时间记录.pop(地址, None)

        时间队列 = 请求时间记录[客户端地址]
        if len(时间队列) >= 每IP每分钟请求上限:
            raise HTTPException(status_code=429, detail="识别次数较多，请一分钟后再试。")
        if 正在识别数量 >= 同时识别上限:
            raise HTTPException(status_code=429, detail="当前识别请求较多，请稍后重试。")

        时间队列.append(当前时间)
        正在识别数量 += 1


async def 释放识别配额() -> None:
    """释放一个模型调用名额。"""
    global 正在识别数量
    async with 配额锁:
        正在识别数量 = max(0, 正在识别数量 - 1)


@app.post("/api/analyze")
async def 识别楼道风险(请求: Request, 图片文件: UploadFile = File(...)) -> dict[str, Any]:
    """接收一张照片，调用 DeepSeek Flash 并返回风险类别与说明。"""
    await 检查识别配额(请求.client.host if 请求.client else "unknown")
    try:
        原始图片 = await 图片文件.read(最大上传字节数 + 1)
        if not 原始图片:
            raise HTTPException(status_code=400, detail="请先拍照或选择一张图片。")
        if len(原始图片) > 最大上传字节数:
            raise HTTPException(status_code=413, detail="图片不能超过 10 MB，请压缩后重试。")

        图片字节 = 规范化图片(原始图片)
        密钥 = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not 密钥 or 密钥 == "请填写你的DeepSeek_API_Key":
            raise HTTPException(status_code=503, detail="尚未配置 DeepSeek API Key，请先在服务端 .env 文件中填写。")

        基础地址 = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
        模型名称 = os.getenv("DEEPSEEK_MODEL", "deepseek-flash").strip()
        图片编码 = base64.b64encode(图片字节).decode("ascii")

        async with AsyncOpenAI(api_key=密钥, base_url=基础地址, timeout=90.0, max_retries=0) as 客户端:
            回复 = await 客户端.chat.completions.create(
                model=模型名称,
                messages=[
                    {"role": "system", "content": 风险识别提示词},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "请检查这张照片中的楼道消防安全隐患。"},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{图片编码}",
                                    "detail": "high",
                                },
                            },
                        ],
                    },
                ],
                max_tokens=600,
            )
        模型文本 = 回复.choices[0].message.content or ""
        return 提取模型结果(模型文本)
    except HTTPException:
        raise
    except (APITimeoutError, APIConnectionError) as 错误:
        raise HTTPException(status_code=504, detail="连接 DeepSeek 超时或失败，请检查网络后重试。") from 错误
    except APIStatusError as 错误:
        raise HTTPException(status_code=502, detail=f"DeepSeek 服务暂不可用（HTTP {错误.status_code}），请稍后重试。") from 错误
    except ValueError as 错误:
        raise HTTPException(status_code=502, detail="模型未能返回有效的风险判断，请重新识别。") from 错误
    except Exception as 错误:
        raise HTTPException(status_code=502, detail="识别过程中发生错误，请稍后重试。") from 错误
    finally:
        await 释放识别配额()


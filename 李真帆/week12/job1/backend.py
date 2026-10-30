"""
楼道风险监控识别 —— 后端模块（FastAPI + LangChain）

职责：接收前端上传的单张楼道照片，调用 DeepSeek（deepseek-flash 原生支持图片输入）
      判定堆物与火灾隐患，并把模型输出逐块流式返回。

接口：
    GET  /health    健康检查，前端据此确认后端已就绪
    POST /analyze   multipart 字段 file 上传图片，流式返回 NDJSON 数据帧
                    {"text": "..."} 为内容块，{"done": true} 结束，{"error": "..."} 失败

单独运行：python backend.py （一般情况下由 job1.py 的 mainapp 自动拉起）
"""

import base64
import json
from typing import AsyncIterator

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

# ═══════════════════════════════════════════════════════════════════════════════
# 全局配置
# ═══════════════════════════════════════════════════════════════════════════════

APP_NAME = "楼道风险监控识别"

# DeepSeek API Key —— 留给你自己填
DEEPSEEK_API_KEY = "your_api_key"

# DeepSeek 兼容 OpenAI 协议的接口地址
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# 模型名称：deepseek-flash 原生支持图片输入（标准 OpenAI 多模态格式）
DEEPSEEK_MODEL = "deepseek-flash"

# 监听 0.0.0.0 便于本机与局域网设备访问；BACKEND_URL 是前端调用后端时使用的地址
BACKEND_HOST = "0.0.0.0"
BACKEND_PORT = 8000
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"

# 只允许图片、且限制单张大小（一次仅分析一张图片）
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/bmp", "image/gif"}
MAX_IMAGE_MB = 10

SYSTEM_PROMPT = """你是社区消防安全巡检专家，专门判断楼道（公共走廊、楼梯间、电梯厅）堆放物品的火灾隐患。
只依据图片中真实可见的内容判断，看不清就说不确定，不要臆造画面里没有的东西。"""

ANALYZE_PROMPT = """请判断这张图片的楼道堆物隐患，严格按下面的等级标准和输出格式作答。

【等级标准】
- 高风险：楼道中出现电动车、电瓶（电池）、飞线充电等可能起火的元素。
- 中等风险：存在大量堆积物严重影响通行，或堆放大量纸箱、木质家具等能造成火势蔓延的堵塞物。
- 低风险：存在楼道堆物现象但不严重，通道基本畅通。
- 无隐患：楼道干净，无堆放物品。
- 非楼道：图片与楼道无关（风景、人物、其他室内场景等）。

【输出格式】
风险等级：<从 无隐患 / 低风险 / 中等风险 / 高风险 / 非楼道 中五选一>
判定依据：<命中的关键视觉元素，如电动车、飞线、纸箱堆、木质家具、通道被占等>
现场说明：<1~3 句中文，说明画面里具体看到了什么、堆在哪个位置>
处置建议：<1~2 句针对性整改建议；若为非楼道图片则提示重新拍摄楼道照片>
"""

# 变量名故意不叫 app：新版 `streamlit run` 会把脚本里的 FastAPI/Starlette 实例当成 ASGI 入口，
# 一旦发现就只起 API、不渲染前端界面，所以前端脚本（job1.py）里绝对不能出现这种赋值。
api = FastAPI(title=APP_NAME)


# ═══════════════════════════════════════════════════════════════════════════════
# LangChain 调用
# ═══════════════════════════════════════════════════════════════════════════════

def build_model() -> ChatOpenAI:
    """构造 LangChain 的 DeepSeek 客户端（OpenAI 兼容协议，流式输出）。"""
    return ChatOpenAI(
        model=DEEPSEEK_MODEL,
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
        temperature=0,
        streaming=True,
        timeout=120,
    )


def chunk_to_text(content) -> str:
    """把消息块的 content 归一化成字符串（可能是 str，也可能是 content block 列表）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return ""


async def stream_analyze(data: bytes, mime: str) -> AsyncIterator[str]:
    """图片转 base64 内联 -> 多模态模型，逐块输出 NDJSON（每行一个 JSON，避免换行被切碎）。"""
    message = HumanMessage(content=[
        {"type": "text", "text": ANALYZE_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}},
    ])

    try:
        async for chunk in build_model().astream([SystemMessage(content=SYSTEM_PROMPT), message]):
            text = chunk_to_text(chunk.content)
            if text:
                yield json.dumps({"text": text}, ensure_ascii=False) + "\n"
        yield json.dumps({"done": True}, ensure_ascii=False) + "\n"
    except Exception as exc:  # 网络 / 鉴权 / 模型报错都转成 error 帧，交给前端提示
        yield json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False) + "\n"


# ═══════════════════════════════════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════════════════════════════════

@api.get("/health")
async def health() -> dict:
    """健康检查。"""
    return {"status": "ok", "model": DEEPSEEK_MODEL, "key_ready": DEEPSEEK_API_KEY not in {"", "your_api_key"}}


@api.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    """接收单张图片，流式返回隐患分析结果。"""
    data = await file.read()
    mime = (file.content_type or "").split(";")[0]
    if not data:
        return JSONResponse({"detail": "图片内容为空"}, status_code=400)
    if len(data) > MAX_IMAGE_MB * 1024 * 1024:
        return JSONResponse({"detail": f"图片超过 {MAX_IMAGE_MB}MB"}, status_code=400)
    if mime not in ALLOWED_MIME:
        return JSONResponse({"detail": f"不支持的图片格式：{mime or '未知'}"}, status_code=400)

    return StreamingResponse(stream_analyze(data, mime), media_type="application/x-ndjson")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(api, host=BACKEND_HOST, port=BACKEND_PORT, log_level="info")



import base64
import json
import os
import re
import socket
from io import BytesIO

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from PIL import Image, ImageOps, UnidentifiedImageError

ROOT = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(ROOT, ".env"))

LEVELS = ("高风险", "中风险", "低风险", "无风险", "非楼道")
LEVEL_ALIASES = {
    "高风险": "高风险",
    "中风险": "中风险",
    "中等风险": "中风险",
    "低风险": "低风险",
    "无风险": "无风险",
    "无隐患": "无风险",
    "非楼道": "非楼道",
}

PROMPT = """你是一名专业消防安全检查员，只根据照片里看得见的内容判断楼道消防隐患，不要猜测画面外的情况。

楼道包括：楼梯间、消防通道、楼内公共走廊、门厅、电梯厅外的通道。

风险只允许是下面五类之一：
- 高风险：楼道中出现电动车、电瓶、电池、充电器、飞线充电等可能起火的元素。
- 中风险：楼道中存在大量堆积物，严重影响通行；或堆放大量纸箱、木质家具、泡沫、织物等容易让火势蔓延的堵塞物。没有电动车、电瓶、飞线充电时，才归入这一类。
- 低风险：存在楼道堆物，但数量少，没有严重堵住通道，也没有大量可燃物或起火源。
- 无风险：可以确认是楼道，而且楼道干净，没有堆放物品。
- 非楼道：画面主体不是楼道、楼梯间、消防通道或楼内公共走廊。

判定顺序：先看是不是楼道；是楼道时，只要出现电动车、电瓶或飞线充电就是高风险；否则大量可燃物或严重占道是中风险；轻微堆物是低风险；干净就是无风险。

只输出一个 JSON 对象，不要 Markdown，不要额外解释。格式如下：
{"risk_level":"高风险|中风险|低风险|无风险|非楼道","is_corridor":true,"summary":"一句话说明依据","evidence":["看到的关键物品或现象"],"suggestion":"给居民或物业的一句处理建议"}
evidence 最多 4 条。非楼道时 suggestion 写“请拍摄楼道、楼梯间或消防通道”。"""

MODELS = {
    "deepseek": {
        "label": "DeepSeek Flash 4.1",
        "model": "deepseek-flash",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "extra_body": {"thinking": {"type": "disabled"}},
    },
    "qwen": {
        "label": "Qwen3-VL",
        "model": "qwen3-vl-plus",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "DASHSCOPE_API_KEY",
        "extra_body": {"enable_thinking": False},
    },
}

app = FastAPI(title="楼道消防隐患识别")
app.mount("/static", StaticFiles(directory=os.path.join(ROOT, "static")), name="static")


def model_ready(model_id: str) -> bool:
    return bool(os.getenv(MODELS[model_id]["api_key_env"], "").strip())


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT, "static", "index.html"))


@app.get("/api/models")
def list_models():
    items = []
    for model_id, spec in MODELS.items():
        ready = model_ready(model_id)
        hint = "" if ready else f"请在 .env 中填写 {spec['api_key_env']}"
        items.append(
            {
                "id": model_id,
                "label": spec["label"],
                "model": spec["model"],
                "ready": ready,
                "hint": hint,
            }
        )
    return {"models": items}


def prepare_image(data: bytes) -> str:
    if not data:
        raise HTTPException(status_code=400, detail="没有收到图片")
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片请小于 12MB")
    try:
        image = ImageOps.exif_transpose(Image.open(BytesIO(data)))
    except UnidentifiedImageError as exc:
        raise HTTPException(
            status_code=400,
            detail="无法读取这张图片。请使用 JPG、PNG 或 WEBP；手机相册里的 HEIC 可先改用页面拍照。",
        ) from exc

    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        image = background
    else:
        image = image.convert("RGB")

    image.thumbnail((1600, 1600))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def strip_think(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    return text.strip()


def normalize_level(value: str) -> str | None:
    text = re.sub(r"\s+", "", str(value or ""))
    for alias, level in LEVEL_ALIASES.items():
        if alias in text:
            return level
    return None


def parse_model_text(text: str) -> dict:
    cleaned = strip_think(text)
    payload = None
    fenced = re.sub(r"^```(?:json)?", "", cleaned, flags=re.I).strip()
    fenced = re.sub(r"```$", "", fenced).strip()
    candidates = [fenced]
    match = re.search(r"\{.*\}", fenced, flags=re.S)
    if match:
        candidates.append(match.group(0))

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
            break
        except json.JSONDecodeError:
            continue

    if isinstance(payload, dict):
        level = normalize_level(payload.get("risk_level", ""))
        evidence = payload.get("evidence") or []
        if isinstance(evidence, str):
            evidence = [evidence]
        evidence = [str(item).strip() for item in evidence if str(item).strip()][:4]
        if level:
            return {
                "risk_level": level,
                "is_corridor": bool(payload.get("is_corridor", level != "非楼道")),
                "summary": str(payload.get("summary") or "").strip(),
                "evidence": evidence,
                "suggestion": str(payload.get("suggestion") or "").strip(),
            }

    first_line = cleaned.splitlines()[0] if cleaned else ""
    level = normalize_level(first_line) or normalize_level(cleaned[:80])
    if not level:
        raise HTTPException(status_code=502, detail=f"模型没有返回可识别的风险等级：{cleaned[:300]}")
    return {
        "risk_level": level,
        "is_corridor": level != "非楼道",
        "summary": cleaned[:300],
        "evidence": [],
        "suggestion": "",
    }


def call_model(model_id: str, image_b64: str) -> tuple[str, str, str]:
    spec = MODELS[model_id]
    api_key = os.getenv(spec["api_key_env"], "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail=f"未配置 {spec['api_key_env']}，请写入 .env 后重启服务")

    client = OpenAI(api_key=api_key, base_url=spec["base_url"], timeout=90)
    try:
        response = client.chat.completions.create(
            model=spec["model"],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                        },
                    ],
                }
            ],
            max_tokens=800,
            extra_body=spec["extra_body"],
        )
    except Exception as exc:
        message = re.sub(r"sk-[A-Za-z0-9]+", "sk-***", str(exc))
        if "invalid_api_key" in message or "Incorrect API key" in message:
            detail = f"{spec['label']} 的密钥无效，请检查 .env 中的 {spec['api_key_env']}"
        elif "Insufficient Balance" in message or "insufficient_balance" in message:
            detail = f"{spec['label']} 账户余额不足，请充值后再识别"
        else:
            detail = f"{spec['label']} 调用失败：{message[:300]}"
        raise HTTPException(status_code=502, detail=detail) from exc

    content = response.choices[0].message.content or ""
    if not content.strip():
        raise HTTPException(status_code=502, detail=f"{spec['label']} 没有返回识别结果")
    return spec["label"], spec["model"], content


@app.post("/api/analyze")
async def analyze(
    image: UploadFile = File(...),
    model: str = Form("qwen"),
):
    if model not in MODELS:
        raise HTTPException(status_code=400, detail="不支持的模型")
    data = await image.read()
    image_b64 = prepare_image(data)
    label, model_name, content = call_model(model, image_b64)
    result = parse_model_text(content)
    if result["risk_level"] not in LEVELS:
        raise HTTPException(status_code=502, detail="风险等级不在规定范围内")
    result.update({"model_label": label, "model_name": model_name})
    return result


def lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    ip = lan_ip()
    print(f"本机打开: http://127.0.0.1:{port}")
    print(f"手机同一 Wi-Fi 打开: http://{ip}:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)

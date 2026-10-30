"""
全局配置：模型注册表 + 提示词 + 环境变量。

改模型 / 改提示词只需要动这一个文件。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

UPLOAD_DIR = BASE_DIR / "uploads"
RESULT_DIR = BASE_DIR / "results"
STATIC_DIR = BASE_DIR / "static"
for _d in (UPLOAD_DIR, RESULT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- 服务参数
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "60"))
ENABLE_CACHE = os.getenv("ENABLE_CACHE", "1") == "1"
SAVE_UPLOAD = os.getenv("SAVE_UPLOAD", "1") == "1"
# 关闭思考链：qwen3 / omni 系列支持。实测同一张图 12s -> 1.4s，判定结果一致。
# 想让它"先想再答"就设成 0（更慢，复杂场景可能略稳）。
DISABLE_THINKING = os.getenv("DISABLE_THINKING", "1") == "1"
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen3.8-omni-flash")

# 上传图统一压缩到的长边像素（越大越准，越费 token）
MAX_SIDE = int(os.getenv("MAX_SIDE", "1280"))
JPEG_QUALITY = int(os.getenv("JPEG_QUALITY", "88"))

# ---------------------------------------------------------------- 服务商
PROVIDERS = {
    "dashscope": {
        "label": "阿里云百炼",
        "base_url": os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "api_key_env": "DASHSCOPE_API_KEY",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        "api_key_env": "DEEPSEEK_API_KEY",
    },
}

# ---------------------------------------------------------------- 模型注册表
# order 越小越优先做兜底；enabled 会在运行时结合 Key 是否存在再判一次
MODELS: list[dict] = [
    {
        "id": "qwen3.8-omni-flash",
        "label": "Qwen3.8-Omni-Flash",
        "provider": "dashscope",
        "desc": "全模态极速版，默认首选",
        "order": 1,
    },
    {
        "id": "qwen-vl-max-latest",
        "label": "Qwen-VL-Max",
        "provider": "dashscope",
        "desc": "视觉能力最强（兜底）",
        "order": 2,
    },
    {
        "id": "qwen-vl-plus",
        "label": "Qwen-VL-Plus",
        "provider": "dashscope",
        "desc": "速度与成本均衡（兜底）",
        "order": 3,
    },
    {
        "id": "deepseek-v4.1-flash",
        "label": "DeepSeek-V4.1-Flash",
        "provider": "deepseek",
        "desc": "极速推理，需配置 DEEPSEEK_API_KEY",
        "order": 4,
    },
]

MODEL_MAP = {m["id"]: m for m in MODELS}

# 运行时黑名单：探测到 403/404（未开通、模型名不对）的模型自动摘除，
# 既让下拉框诚实，也避免兜底链白等一轮。
_BLOCKED: dict[str, str] = {}


def mark_blocked(model_id: str, reason: str) -> None:
    if model_id and model_id not in _BLOCKED:
        _BLOCKED[model_id] = reason


def blocked_reason(model_id: str) -> str | None:
    return _BLOCKED.get(model_id)


def api_key(provider: str) -> str:
    """取某个服务商的 Key。"""
    return (os.getenv(PROVIDERS[provider]["api_key_env"], "") or "").strip()


def model_available(model_id: str) -> bool:
    m = MODEL_MAP.get(model_id)
    return bool(m) and bool(api_key(m["provider"])) and model_id not in _BLOCKED


def available_models() -> list[dict]:
    """返回给前端的模型列表（带 available 标记）。"""
    out = []
    for m in sorted(MODELS, key=lambda x: x["order"]):
        out.append(
            {
                "id": m["id"],
                "label": m["label"],
                "provider": m["provider"],
                "provider_label": PROVIDERS[m["provider"]]["label"],
                "desc": m["desc"],
                "available": model_available(m["id"]),
                "blocked": blocked_reason(m["id"]),
            }
        )
    return out


def fallback_chain(model_id: str) -> list[str]:
    """首选模型 + 同服务商/其它服务商里可用的兜底模型。"""
    chain = [model_id] if model_available(model_id) else []
    for m in sorted(MODELS, key=lambda x: x["order"]):
        if m["id"] != model_id and model_available(m["id"]):
            chain.append(m["id"])
    return chain


# ---------------------------------------------------------------- 提示词
RISK_LEVELS = ["高风险", "中风险", "低风险", "无风险", "非楼道"]

SYSTEM_PROMPT = """你是住宅小区楼道消防安全的专业检查员，具备消防工程与火灾调查经验。
你只依据照片中真实可见的内容做判断，不臆测画面外的信息。

你能识别的隐患要素包括：电动自行车 / 电动摩托车 / 电动踏板车、单独放置的电瓶或电池组、
飞线充电（从住户窗户、门洞、电表箱私拉电线到楼下给车辆或电池充电）、裸露插排与临时接线、
纸箱纸板、木质家具、泡沫塑料、旧衣物被褥、燃气罐/液化气瓶、可燃液体、
以及被堵塞的疏散通道、楼梯踏步堆物、被遮挡的消火栓/灭火器/配电箱/电表箱。

严格的取证原则：
1. 只描述你在画面里能指出位置的东西，禁止"可能""大概"之类的推测性表述当作证据。
2. 区分"一件小杂物"和"成堆的可燃物"，二者风险等级不同。
3. 看不清细节时，宁可按较低等级判定，但一旦能明确看到电动车/电瓶/飞线充电，必须判为高风险。"""

USER_PROMPT = """请判断这张照片所在场景的消防安全隐患等级。

【等级定义】（按顺序匹配，命中即停止）
- 非楼道：画面主体不是居民楼公共楼道 / 楼梯间 / 电梯厅 / 疏散走道，例如居家室内、街道、
  商铺、办公室、风景、单纯的人物或物品特写；或画面严重模糊、过暗，无法辨认场景。
  （注：地下车库连通走道、住宅架空层公共通道，若明显是公共通行/疏散路径，算楼道。）
- 高风险：画面中出现电动自行车、电动摩托车、电动踏板车、电瓶/电池组、飞线充电、
  临时接线给车辆或电池充电、燃气罐等点火源/引火源。
  只要出现上述任一项，即使同时存在大量堆积物，也判为高风险。
- 中风险：存在大量堆积物，且满足下列任意一条：
  ① 明显侵占通道，可通行宽度被压缩到需要侧身才能通过，或直接堵住楼梯口/门口；
  ② 堆放纸箱、木质家具、泡沫、塑料、旧衣物等可燃物且成堆、成摞，具备火势蔓延条件；
  ③ 堆积物堆高，遮挡或紧贴消火栓、灭火器、配电箱、电表箱、疏散指示。
- 低风险：有零星堆物（1~3 件小物件、单个纸箱、儿童车、鞋架、扫帚等），通道依然通畅，
  没有大量可燃物聚集，也没有充电或车辆。
- 无风险：楼道干净整洁，地面无堆放物，无车辆、无杂物、无临时接线充电。

【要求】
1. risk_level 只能是：高风险 / 中风险 / 低风险 / 无风险 / 非楼道 之一。
2. evidence 必须指出具体位置（如"画面左侧贴墙""楼梯拐角""通道中央偏右"），只写看得见的事实。
3. hazards 列出每一个隐患要素；无隐患时给空数组。
4. 当 risk_level 为 非楼道 时，risk_score 固定 0，blocked_passage / flammable_material 均为 false。
5. suggestion 用 1~2 句给出可执行的处置动作，贴合物业/住户能做到的事。

【输出格式】只输出一个 JSON 对象，不要任何解释文字、不要 markdown 代码块：
{
  "is_corridor": true,
  "risk_level": "高风险",
  "risk_score": 85,
  "scene": "居民楼首层楼梯间",
  "hazards": [
    {
      "name": "电动自行车",
      "category": "电动车",
      "severity": "高",
      "location": "画面右侧贴墙",
      "reason": "整车停放于疏散走道，电池存在热失控引燃风险"
    }
  ],
  "blocked_passage": true,
  "flammable_material": false,
  "evidence": "画面右侧贴墙停放一辆电动自行车，占用走道约三分之一宽度；左侧地面堆有两个纸箱。",
  "suggestion": "立即将电动车移至室外集中停放充电点，清理走道纸箱，恢复疏散通道畅通。",
  "confidence": 0.9
}

【字段约束】
- risk_score：0~100 的整数。无风险 0~10，低风险 11~35，中风险 36~69，高风险 70~100。
- hazards[].category 取值：电动车 / 电瓶 / 飞线充电 / 可燃堆积物 / 堵塞通道 / 明火源 / 其他。
- hazards[].severity 取值：高 / 中 / 低。
- blocked_passage：堆积物是否已严重影响通行（true/false）。
- flammable_material：是否存在成堆可燃物（true/false）。
- confidence：0~1 之间的小数，表示你对本次判定的把握。"""


def build_messages(image_b64: str) -> list[dict]:
    """构造 OpenAI 兼容的多模态消息体。"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                {"type": "text", "text": USER_PROMPT},
            ],
        },
    ]

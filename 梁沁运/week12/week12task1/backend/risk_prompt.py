"""提示词构建 + 模型输出解析 + 结果归一化 —— 不依赖模型、不依赖 FastAPI。"""

import ast
import json
import re

# ── 风险等级常量 ──────────────────────────────────────────
RISK_LEVELS: tuple = ("无隐患", "低风险", "中等风险", "高风险")

# ── 等级别名映射（模型可能输出的变体 → 标准名称） ──────────
_LEVEL_ALIAS: dict[str, str] = {
    "中风险": "中等风险",
    "低危": "低风险",
    "中危": "中等风险",
    "高危": "高风险",
    "无风险": "无隐患",
    "安全": "无隐患",
}

# ── 隐患类型白名单 ────────────────────────────────────────
_HAZARD_TYPES = {
    "堆积物", "可燃物", "堵塞通道", "电动车/电池",
    "充电/飞线", "明火/烟头", "电气隐患", "其他",
}

# ── 系统提示词（完整风险分级标准） ─────────────────────────
SYSTEM_PROMPT = """你是一名专业的楼道消防安全检查员。请仔细观察用户上传的楼道/通道图片，严格按照以下标准进行安全隐患识别与分级。

## 风险分级标准（只能输出以下 4 个等级之一）

| 等级 | 判定依据（以楼道场景为准） |
|---|---|
| 无隐患 | 楼道通畅；无堆积物，或仅有少量不影响通行的非可燃物；无电动车/电池入户；无飞线充电；无明火/烟头；无电气隐患 |
| 低风险 | 有少量普通杂物或可燃物，但未明显阻塞通道，远离火源/电气设备 |
| 中等风险 | 有较多可燃堆积物（纸箱、纸皮、塑料、布料、木质杂物等），通道变窄但仍可通行；或存在电动车/电池停放但未见充电；或存在一般电气隐患 |
| 高风险 | 大量可燃物密集堆积、明显堵塞疏散通道；或电动车入户/楼道充电/飞线充电；或明火、烟头、燃气罐、私拉乱接电线等直接起火风险 |

## 重要规则
- 模型无法确定时，倾向保守等级（偏高一档），并在 reason 中说明"建议人工复核"。
- 严禁编造图片中不存在的物体。
- hazards 中每个隐患的 type 只能是：堆积物 / 可燃物 / 堵塞通道 / 电动车/电池 / 充电/飞线 / 明火/烟头 / 电气隐患 / 其他。
- bbox_2d 使用原图像素坐标，左上角为 (0,0)，格式 [x1, y1, x2, y2]；若无法定位则填 null。
- 没有发现隐患时 hazards 必须为空数组 []。"""


def build_user_prompt(width: int, height: int) -> str:
    """根据图像尺寸构建用户提示词，要求模型输出严格 JSON。"""
    return f"""请分析这张楼道图片（尺寸：{width} x {height} 像素，bbox 请使用原图像素坐标，左上角为原点 (0,0)）。

严格只输出一个 JSON 对象，不要 markdown 代码块、不要解释文字、不要前后缀。格式如下：

{{
  "risk_level": "无隐患|低风险|中等风险|高风险",
  "risk_score": 0到100的整数,
  "is_fire_hazard": true或false,
  "reason": "一两句话的判断原因",
  "hazards": [
    {{
      "type": "堆积物|可燃物|堵塞通道|电动车/电池|充电/飞线|明火/烟头|电气隐患|其他",
      "description": "该隐患的具体描述",
      "bbox_2d": [x1, y1, x2, y2]
    }}
  ],
  "suggestion": "针对性的处置建议"
}}

注意：
- hazards 为空时填 []
- bbox_2d 无法定位时填 null
- risk_score 须为 0-100 的整数
- is_fire_hazard 为 true 表示存在火灾隐患"""


def parse_and_normalize(raw: str) -> dict:
    """
    从模型原始输出中解析 JSON 并做全面归一化，返回最终 dict。
    无论输入多不规范，始终返回合法结构，不会抛异常。
    """
    # ── 1. 解析 JSON ──────────────────────────────────────
    parsed = _extract_json(raw)

    # ── 2. 归一化各字段 ───────────────────────────────────
    result: dict = {}

    # risk_level 归一化
    level = str(parsed.get("risk_level", "")).strip()
    if level in RISK_LEVELS:
        result["risk_level"] = level
    elif level in _LEVEL_ALIAS:
        result["risk_level"] = _LEVEL_ALIAS[level]
    else:
        # 非法等级 → 用 risk_score 分档兜底
        result["risk_level"] = _score_to_level(parsed.get("risk_score"))
        result["need_manual_review"] = True

    # risk_score
    try:
        score = int(parsed.get("risk_score", 0))
    except (ValueError, TypeError):
        score = 0
    result["risk_score"] = max(0, min(100, score))

    # is_fire_hazard（缺省时按等级推）
    if "is_fire_hazard" in parsed:
        result["is_fire_hazard"] = bool(parsed["is_fire_hazard"])
    else:
        result["is_fire_hazard"] = result["risk_level"] != "无隐患"

    # reason
    reason = str(parsed.get("reason", "")).strip()
    result["reason"] = reason if reason else "模型未给出判断原因，建议人工复核。"
    if not reason and "need_manual_review" not in result:
        result["need_manual_review"] = True

    # hazards
    hazards_raw = parsed.get("hazards", [])
    if not isinstance(hazards_raw, list):
        hazards_raw = []
    hazards: list[dict] = []
    for h in hazards_raw:
        if not isinstance(h, dict):
            continue
        h_type = str(h.get("type", "其他")).strip()
        if h_type not in _HAZARD_TYPES:
            h_type = "其他"
        h_desc = str(h.get("description", "")).strip()
        if not h_desc:
            h_desc = "未描述"
        bbox = h.get("bbox_2d", None)
        if isinstance(bbox, list) and len(bbox) == 4:
            try:
                bbox = [int(v) for v in bbox]
            except (ValueError, TypeError):
                bbox = None
        else:
            bbox = None
        hazards.append({
            "type": h_type,
            "description": h_desc,
            "bbox_2d": bbox,
        })
    result["hazards"] = hazards

    # suggestion
    suggestion = str(parsed.get("suggestion", "")).strip()
    result["suggestion"] = suggestion if suggestion else "建议人工到现场复核。"
    if not suggestion and "need_manual_review" not in result:
        result["need_manual_review"] = True

    # need_manual_review
    if "need_manual_review" not in result:
        result["need_manual_review"] = bool(parsed.get("need_manual_review", False))

    # raw
    result["raw"] = raw

    # ── 3. 保证固定字段顺序 ──────────────────────────────
    return {
        "risk_level": result["risk_level"],
        "risk_score": result["risk_score"],
        "is_fire_hazard": result["is_fire_hazard"],
        "reason": result["reason"],
        "hazards": result["hazards"],
        "suggestion": result["suggestion"],
        "need_manual_review": result["need_manual_review"],
        "raw": result["raw"],
    }


def _score_to_level(score) -> str:
    """用 risk_score 分档兜底，返回保守等级。"""
    try:
        s = int(score)
    except (ValueError, TypeError):
        return "中等风险"  # 完全不确定 → 保守中风险
    if s <= 10:
        return "无隐患"
    if s <= 35:
        return "低风险"
    if s <= 65:
        return "中等风险"
    return "高风险"


def _extract_json(raw: str) -> dict:
    """
    从模型原始输出中尽力提取 JSON dict，多种容错策略：
    1. 去 markdown 代码块围栏
    2. 截取首 { 到末 }
    3. json.loads → ast.literal_eval 兜底
    4. 全部失败返回空 dict
    """
    if not raw:
        return {}
    text = raw.strip()

    # 去掉 ```json ... ``` 或 ``` ... ``` 围栏
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    # 截取第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    # JSON 解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 宽松容错（单引号、尾逗号等）
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        pass

    # 尝试用正则暴力提取简单 key-value（最后兜底）
    result: dict = {}
    for key in ["risk_level", "risk_score", "is_fire_hazard", "reason", "suggestion"]:
        m = re.search(rf'"{key}"\s*:\s*(.+?)(?:\s*[,}}])', text)
        if m:
            result[key] = m.group(1).strip().strip('"')
    # hazards 较复杂，跳过暴力提取
    return result if result else {}
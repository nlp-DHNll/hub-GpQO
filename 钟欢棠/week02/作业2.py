import json
from openai import OpenAI

# ── 配置──────────────────────────────
client = OpenAI(
    api_key="sk-86fec757d81a42b0bf6a8a514d55a9c7",
    base_url="https://api.deepseek.com",
)
MODEL = "deepseek-v4-flash"

# ── 系统提示词 ───────────────────────────────────────────────
SYSTEM_PROMPT = """
从用户的文本中提取所有人物关系，以 JSON 数组格式输出。
每个关系包含三个字段：
  - source: 关系起点人物
  - relation: 关系类型（如 喜欢、爱慕、暗恋、讨厌、朋友、同学、家人 等）
  - target: 关系终点人物

注意：
- 双向关系拆分为两条记录
- 转折词（但是、然而、却）暗示不同方向的关系

JSON 输出示例：
[
    {"source": "小明", "relation": "喜欢", "target": "小姚"},
    {"source": "小姚", "relation": "喜欢", "target": "小王"}
]
"""


# ── 核心函数 ─────────────────────────────────────────────────
def extract_relationships(text: str) -> list[dict]:
    """输入自然语言文本，返回人物关系图谱列表。"""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )

    content = response.choices[0].message.content

    # 解析 JSON（带简单容错）
    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        # 去除 markdown 代码块标记后重试
        cleaned = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(cleaned)

    # 兼容不同外层包装
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return result.get("relationships") or result.get("data") or [result] if "source" in result else []
    return []


# ── 测试 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    test_cases = [
        "小明喜欢小姚，但是小姚喜欢小王。",
        "张三暗恋李四，李四和王五是好朋友，但王五却讨厌张三。",
        "老张是张小小的爸爸，李芳是张小小的妈妈，老张和李芳是夫妻。",
    ]

    for text in test_cases:
        print(f"\n输入: {text}")
        result = extract_relationships(text)
        print(f"输出: {json.dumps(result, ensure_ascii=False, indent=4)}")

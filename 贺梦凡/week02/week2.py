import json
from openai import OpenAI

client = OpenAI(
    api_key="sk-436250e178044exxxabubba8f5266990f",
    base_url="https://api.deepseek.com",
)

def safe_json_parse(text: str) -> dict | list | None:
    """安全解析 JSON，处理可能的空 content 和格式异常。"""
    if not text or not text.strip():
        print("    ⚠️  模型返回了空 content（JSON 模式偶发问题）")
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"    ⚠️  JSON 解析失败: {e}")
        # 尝试修复常见问题：删除 markdown 代码块标记
        cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            print(f"    原始内容: {text[:200]}")
            return None

system_prompt = """
从用户的情感描述中提取信息列表，以 JSON 数组格式输出。
每个情感描述包含：source（情感主体）、relation（喜欢、不喜欢、厌恶等）、target（情感接受者）。

JSON 输出示例：
[
    {"source": "小明", "relation": "喜欢", "target": "小姚"},
    {"source": "小姚", "relation": "喜欢", "target": "小王"}
]
"""

user_prompt = """
小明、小姚、小王关系如下：
1. 小明喜欢小姚
2. 小姚喜欢小王
3. 小明厌恶小王
"""

response = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ],
    response_format={"type": "json_object"},
    max_tokens=500,
    temperature=0.0,
)

content = response.choices[0].message.content
result = safe_json_parse(content)

if result:
    # 兼容外层是 {"items": [...]} 或直接数组
    items = result if isinstance(result, list) else result.get("items", result.get("products", [result]))
    print(f"\n共提取 {len(items)} 三段情感描述:")
    print(f"\n原始输出:\n{json.dumps(result, ensure_ascii=False, indent=2)}")

print()

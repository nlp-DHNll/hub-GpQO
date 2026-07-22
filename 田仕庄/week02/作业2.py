"""
作业2: 借助于llm tool call 或 json mode 能力，构建一个简单的情况情感分析智能体。提交实现代码。

输入：小明喜欢小姚，但是小姚喜欢小王。
输出：人物关系图谱

[
    {
        "source": "小明",
        "relation": "爱慕",
        "target": "小姚"
    }
]
"""

import json
from openai import OpenAI

client = OpenAI(
    api_key="sk-0103470e2507427981d9bac4243a6d5a",
    base_url="https://api.deepseek.com",
)


# ═════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ═════════════════════════════════════════════════════════════════════════════

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


print("=" * 65)
print("""
作业2: 借助于llm tool call 或 json mode 能力，构建一个简单的情况情感分析智能体。提交实现代码。

输入：小明喜欢小姚，但是小姚喜欢小王。
输出：人物关系图谱

[
    {
        "source": "小明",
        "relation": "爱慕",
        "target": "小姚"
    }
]
""")
print("=" * 65)

system_prompt = """
你是一个情感分析助手。从人物的好恶关系中提取不同人员之间的关系信息列表，包括各种显现和隐现的关系，注意语气转折词并联系上下文。请逐步推理。
以JSON 数组格式输出分析结果。
每两个人之间的关系包含：source（源头）、relation（是否爱慕）、target（目标对象）。

JSON 输出示例：
[
    {
        "source": "张三",
        "relation": "爱慕",
        "target": "李四"
    },
    {
        "source": "李四",
        "relation": "不爱慕",
        "target": "张三"
    },
    {
        "source": "李四",
        "relation": "爱慕",
        "target": "王五"
    }
]
"""

user_prompt = """
输入：小明喜欢小姚，但是小姚喜欢小王。
输出：人物关系图谱
"""

response = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ],
    response_format={"type": "json_object"},
    reasoning_effort="medium",
    max_tokens=500,
    temperature=0.7,
)

content = response.choices[0].message.content
results = safe_json_parse(content)


if results:
    #
    items = results if isinstance(results, list) else results.get("items", results.get("relations", [results]))
    print(f"\n作业展示如下：共提取 {len(items)} 段关系:")
    for i, item in enumerate(items, 1):
        print(f"  {i}. {item['source']}-{item['relation']}-{item['target']}")
    print(f"\n原始输出:\n{json.dumps(results, ensure_ascii=False, indent=2)}")

print()

import json
import math
from openai import OpenAI

client = OpenAI(
    api_key="sk-52d4618141134919bd4269704e3824a5",
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

prompt = (
    "请分析以下文本中的情感关系，并用 JSON 格式输出结果：小明很喜欢小姚,但小姚喜欢小王"
)
system_json = """
    你是一个情感分析助手。你的任务是从用户输入的文本中提取主要的情感关系，并以**纯 JSON 格式**返回，格式如下：
    {
        "source": "主人物", 
        "relation": "关系", 
        "target": "对象"
    }
    请不要输出任何额外的解释、标记或代码块，只输出 JSON 对象。
"""

resp_json = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[
        {"role": "system", "content": system_json},
        {"role": "user", "content": prompt},
    ],
    response_format={"type": "json_object"},
    max_tokens=300,
    temperature=0.0,
)
print("=" * 65)
print("  JSON 方式输出实现")
print("=" * 65)
content = resp_json.choices[0].message.content
result = safe_json_parse(content)

if result:
    print(f"     source:  {result['source']}")
    print(f"     relation:  {result['relation']}")
    print(f"     target: {result['target']}")
    print(f"\n     原始 JSON:\n     {json.dumps(result, ensure_ascii=False)}")

print()


tools = [
    {
        "type": "function",
        "function": {
            "name": "extract_relations",
            "description": "提取文本中所有的情感关系",
            "parameters": {
                "type": "object",
                "properties": {
                    "relations": {
                        "type": "array",
                        "description": "关系列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source": {"type": "string", "description": "主人物"},
                                "relation": {"type": "string", "description": "关系类型，如喜欢、讨厌、爱慕等"},
                                "target": {"type": "string", "description": "对象人物"}
                            },
                            "required": ["source", "relation", "target"],
                            "additionalProperties": False
                        }
                    }
                },
                "required": ["relations"]
            }
        }
    }
]

response = client.chat.completions.create(
    model="deepseek-v4-flash",  # 或其他支持工具调用的模型
    messages=[
        {"role": "system", "content": "你是一个情感分析助手，负责提取文本中的人物关系。"},
        {"role": "user", "content": "小明很喜欢小姚,但小姚喜欢小王"}
    ],
    tools=tools,
    tool_choice="auto",
    temperature=0.0,
    max_tokens=200,
)

print("=" * 65)
print("  工具调用方式实现")
print("=" * 65)

message = response.choices[0].message
tool_calls = message.tool_calls

if tool_calls:
    # 通常只调用一个工具
    tool_call = tool_calls[0]
    if tool_call.function.name == "extract_relations":
        import json
        args = json.loads(tool_call.function.arguments)
        relations = args.get("relations", [])
        for rel in relations:
            print(f"source:   {rel['source']}")
            print(f"relation: {rel['relation']}")
            print(f"target:   {rel['target']}")
            print()
else:
    # 模型可能没调用工具，回退到 content
    print("模型未调用工具，直接输出:", message.content)

import json
from openai import OpenAI

client = OpenAI(
    api_key="这是密钥",
    base_url="https://api.siliconflow.cn/v1")

tools = [
    {"type": "function",
        "function": {
            "name": "relationship_analysis",
            "description": "你是一个情感分析智能体，请提取文本中的人物关系",
            "parameters": {
                "type": "object",
                "properties": {
                    "relationships": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source": {"type": "string"},
                                "target": {"type": "string"},
                                "relation": {"type": "string"}
                            }
                        }
                    }
                }
            }
        }
    }
]

messages = [
        {"role": "system", "content": "你是一个情感分析智能体，请提取文本中的人物关系"},
        {"role": "user", "content": "小明喜欢小姚，但是小姚喜欢小王"}
    ]
response = client.chat.completions.create(
    model="deepseek-ai/DeepSeek-V4-Flash",
    messages = messages,
    tools=tools,
    tool_choice={"type": "function", "function": {"name": "relationship_analysis"}},
    temperature=0.0,
    stream=False
)

print("情感分析智能体")
print("输入：小明喜欢小姚，但是小姚喜欢小王")

msg = response.choices[0].message

if msg.tool_calls:
    tool_call = msg.tool_calls[0]
    arguments = json.loads(tool_call.function.arguments)

    relationships = arguments.get("relationships", [])

    print("输出：人物关系图谱：")
    for i, relationship in enumerate(relationships, 1):
        print(f"  {i}. {relationship['source']} → {relationship['relation']} → {relationship['target']}")
else:
    print(f"输出：{msg.content}")

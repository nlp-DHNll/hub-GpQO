import json
from openai import OpenAI

client = OpenAI(
    api_key="sk-183e810d9fxxxabu9254bbd5832a2f8e",
    base_url="https://api.deepseek.com"
)

def get_relation(name: str) -> str:

    data = {
        "小明":"爱慕小姚",
        "小姚":"爱慕小王"
    }
    return data.get(name,f"{name} 没有爱慕的人")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_relation",
            "description": "查询人物关系",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "人物名称，如小王，小姚",
                    },
                },
                "required": ["name"],
            },
        },
    }
]

# 工具名称映射函数
FUNCTION_MAP = {

}

def run_tool_call(tc) -> str:
    """执行一次工具调用，返回结果字符串。"""
    name = tc.function.name
    args = json.loads(tc.function.arguments)
    print(f"    → 调用工具: {name}({json.dumps(args, ensure_ascii=False)})")
    result = FUNCTION_MAP[name](**args)
    print(f"    ← 结果: {result}")
    return result
# 实际用不到tools，直接以提示词来完成
messages = [
    {"role": "system", "content": "你是一个专业的人物关系图谱抽取专家。请阅读用户输入的文本，提取出其中包含的人物关系，并严格以纯 JSON 数组格式输出。关系如果是喜欢，则改为爱慕。"
                                  "格式示例：[{\"source\": \"人物A\", \"relation\": \"关系\", \"target\": \"人物B\"}],按照JSON格式进行格式beauty"},
    {"role": "user", "content": "小明喜欢小姚，但是小姚喜欢小王。"},
]

response = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=messages,
    # tools=TOOLS,
    temperature=0.0,
)

choice = response.choices[0]
msg = choice.message

# 模型可能直接回复（不需要工具），也可能发起工具调用
if msg.tool_calls:
    for tc in msg.tool_calls:
        result = run_tool_call(tc)
        messages.append(msg)
        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": result,
        })

    # 把工具结果发回模型，让其生成最终回复
    final = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=messages,
        tools=TOOLS,
        temperature=0.0,
    )
    print(f"\n最终回复: {final.choices[0].message.content}")
else:
    print(f"直接回复: {msg.content}")


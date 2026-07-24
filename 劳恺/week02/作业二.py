import os
import json
from openai import OpenAI
import ollama

#外部API调用
def web_minimax(system_prompt: str, user_prompt: str) -> dict | list | None:
    client = OpenAI(
        api_key=os.environ.get("MINIMAX_API_KEY"),
        base_url="https://api.minimaxi.com/v1",
    )
    response = client.chat.completions.create(
        model="MiniMax-M3",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        extra_body={
            "thinking": {"type": "disabled"},
        },
    )

    content = response.choices[0].message.content
    return content

#本地ollam调用
def local_qw_ollama(system_prompt: str, user_prompt: str) -> dict | list | None:
    response = ollama.chat(
        model="Qw-8b:latest",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )
    content = response['message']['content']
    return content

#本地openai调用
def local_qw_openai(system_prompt: str, user_prompt: str) -> dict | list | None:
    client = OpenAI(
        base_url="http://localhost:11434/v1",
        api_key="ollama"  # 任意值即可
    )
    response = client.chat.completions.create(
        model="Qw-8b:latest",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )
    content = response.choices[0].message.content
    return content



# ═════════════════════════════════════════════════════════════════════════════
# 1. JSON 输出
# ═════════════════════════════════════════════════════════════════════════════

system_prompt_j = """
你是情感分析智能助手，用户会输入一段感情文本，请输出人物关系图谱，从中解析出 "source"， "relation" 和"target"并以 JSON 格式输出。

输入示例：
小明喜欢小姚，但是小姚喜欢小王

JSON 输出示例：
{
        "source": "小明",
        "relation": "爱慕",
        "target": "小姚"
}
"""

user_prompt = "小李喜欢小王,小张讨厌小王"
#调用minimaxAPI
content = web_minimax(system_prompt_j, user_prompt)
# 调用本地QW模型
# content = local_qw_openai(system_prompt_j, user_prompt)
# print(content)

print()
# ═════════════════════════════════════════════════════════════════════════════
# 2. TOOL 调用
# ═════════════════════════════════════════════════════════════════════════════
#提取关系，虽然大模型已经帮忙提取好了
def extract_relations(**kwargs):
    # print("=" * 65)
    # print("正在调用方法")
    relations = kwargs.get('relations', [])
    # print(relations)
    results = relations
    print(results)
    return results

TOOLS = [
    {
        "type": "function",
        "function": {
          "name": "extract_relations",
          "description": "从文本中提取人物关系",
          "parameters": {
            "type": "object",
            "properties": {
              "relations": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "source": {
                        "type": "string",
                        "description": "关系的主体（主动方），即动作的发起者",
                    },
                    "relation": {
                        "type": "string",
                        "description": "人物之间的关系，如爱慕、厌烦",
                    },
                    "target": {
                        "type": "string",
                        "description": "关系的客体（被动方）",
                    }
                  }
                }
              }
            }
          }
        },
    }
]

FUNCTION_MAP = {
    "extract_relations": extract_relations,
}
#显示调用
def run_tool_call(tc) -> str:
    """执行一次工具调用，返回结果字符串。"""
    name = tc.function.name
    args = json.loads(tc.function.arguments)
    print(f"    → 调用工具: {name}({json.dumps(args, ensure_ascii=False)})")
    result = FUNCTION_MAP[name](**args)
    print(f"    ← 结果: {result}")
    return result
#本地模型调用
def local_qw_t(messages: str) -> dict | list | None:
    # 连接到本地 Ollama
    client = OpenAI(
        base_url="http://localhost:11434/v1",
        api_key="ollama"  # 任意值即可
    )
    response = client.chat.completions.create(
        model="Qw-8b:latest",
        messages=messages,
        tools=TOOLS
    )
    choice = response.choices[0]
    msg = choice.message

    # 模型可能直接回复（不需要工具），也可能发起工具调用
    if msg.tool_calls:
        messages.append({
            "role": "assistant",
            "content": msg.content or "",  # 确保 content 是字符串
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in msg.tool_calls
            ]
        })
        for tc in msg.tool_calls:
            # ✅ 关键：将结果转为 JSON 字符串
            result = run_tool_call(tc)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),  # 转为字符串
            })

        # 把工具结果发回模型，让其生成最终回复
        final = client.chat.completions.create(
            model="Qw-8b:latest",
            messages=messages,
            tools=TOOLS,
            temperature=0.0,
        )
        print(f"\n最终回复: {final.choices[0].message.content}")
    else:
        print(f"直接回复: {msg.content}")
#TOOL 调用提示词
system_prompt_t = "你是情感分析助手，可根据需要使用工具回答用户问题。"
messages=[
            {"role": "system", "content": system_prompt_t},
            {"role": "user", "content": user_prompt},
]
#本地模型tool用法
# local_qw_t(messages)
# print(content)

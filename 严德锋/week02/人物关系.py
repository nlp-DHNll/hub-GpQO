import json
import time
from typing import List
from pydantic import BaseModel, Field, ValidationError
from openai import OpenAI
from openai import (
    APIConnectionError,
    APIStatusError,
    BadRequestError,
    AuthenticationError,
    RateLimitError
)

# ================== 数据模型 ==================
class Person(BaseModel):
    """从文本中提取单个人物"""
    name: str = Field(description="人物姓名")

class Relation(BaseModel):
    """从文本中提取人物间的关系"""
    source: str = Field(description="关系起点人物")
    target: str = Field(description="关系终点人物")
    relation: str = Field(description="两人之间的关系")

class CharacterGraph(BaseModel):
    """从文本中提取完整人物关系图谱"""
    persons: List[Person]
    relations: List[Relation]

# ================== 创建工具 ==================
schema = CharacterGraph.model_json_schema()
tool = {
    "type": "function",
    "function": {
        "name": schema["title"],
        "description": schema["description"],
        "parameters": {
            "type": "object",
            "properties": schema["properties"],
            "required": schema.get("required", []),
        },
        "strict": True,
    }
}

# ================== 客户端 ==================
client = OpenAI(
    api_key="API-KEY",
    base_url="https://api.deepseek.com"
)

system_prompt = """
你是情感分析助手，从用户的文字描述中提取人物信息，人物关系，以 JSON 格式输出：
"""

user_prompt = """
小明喜欢小姚，但是小姚喜欢小王。
刘备、关羽、张飞三人在桃园结为兄弟。
"""

messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": user_prompt},
]

# ================== 安全调用（带重试 + 异常兜底） ==================
MAX_RETRY = 3
response = None

for attempt in range(1, MAX_RETRY + 1):
    try:
        response = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=messages,
            tools=[tool],
            tool_choice="auto"
        )
        break  # ✅ 成功就跳出

    except AuthenticationError:
        print("❌ API Key 无效或已过期，请检查配置")
        break

    except BadRequestError as e:
        print(f"❌ 请求参数错误（400）：{e}")
        break

    except RateLimitError:
        print(f"⚠️ 触发限流，第 {attempt} 次重试...")
        time.sleep(2 * attempt)

    except APIConnectionError:
        print(f"⚠️ 网络连接失败，第 {attempt} 次重试...")
        time.sleep(2 * attempt)

    except APIStatusError as e:
        print(f"⚠️ API 返回异常状态 {e.status_code}，第 {attempt} 次重试...")
        time.sleep(2 * attempt)

    except Exception as e:
        print(f"❌ 未知错误：{type(e).__name__} - {e}")
        break

# ================== 结果解析兜底 ==================
if not response:
    print("🚫 无法获取模型响应，程序终止")
    exit(1)

# 检查是否有 tool_call
msg = response.choices[0].message

if not msg.tool_calls:
    print("⚠️ 模型未调用工具，返回内容如下：")
    print(msg.content)
    exit(1)

# 解析 JSON
try:
    raw_json = msg.tool_calls[0].function.arguments
    graph = CharacterGraph.model_validate_json(raw_json)

except (ValidationError, json.JSONDecodeError) as e:
    print("❌ 模型返回的 JSON 不符合 CharacterGraph 结构")
    print(f"错误详情：{e}")
    print(f"原始 JSON：{raw_json}")
    exit(1)

# ================== 打印结果 ==================
print("=" * 50)
print("人物列表")
print("=" * 50)
for i, p in enumerate(graph.persons, 1):
    print(f"  {i}. {p.name}")

print("\n" + "=" * 50)
print("关系列表")
print("=" * 50)
for i, r in enumerate(graph.relations, 1):
    print(f"  {i}. {r.source}  ──{r.relation}──  {r.target}")

print(f"\n共 {len(graph.persons)} 个人物，{len(graph.relations)} 条关系")

import os
import json
from openai import OpenAI

client = OpenAI(
    api_key="sk-lbzxuztychgdpwdcpccxsvavbmzdhyabryvxturikxpehsbi",
    base_url="https://api.siliconflow.cn/v1")

system_prompt = """
从用户的文字描述中提取人物信息，以 JSON数组格式输出，包含以下字段：
- source: 姓名
- relation: 关系
- target: 姓名

有多段关系的话要把每一段关系都输出
JSON 输出示例：

[
    {
        "source": "小明",
        "relation": "爱慕",
        "target": "小姚"
    }
]

注意：
1. 必须是数组 [] 格式，不能是对象 {}
2. 如果只找到一条关系，也要返回数组： [{"source": "...", "relation": "...", "target": "..."}]
3. 只输出JSON，不要有其他文字
"""

user_prompt = """
小明喜欢小姚，但是小姚喜欢小王。
"""

response = client.chat.completions.create(
    model="deepseek-ai/DeepSeek-V4-Flash",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ],
    #response_format={"type": "json_object"},
    max_tokens=500,
    temperature=0.0,
)



content = response.choices[0].message.content
data = json.loads(content)
print(json.dumps(data, ensure_ascii=False, indent=4))

print()

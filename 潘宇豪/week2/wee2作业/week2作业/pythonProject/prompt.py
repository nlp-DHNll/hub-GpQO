# Please install OpenAI SDK first: `pip3 install openai`
import os
from openai import OpenAI
import json
client = OpenAI(
    api_key=os.environ.get('DEEPSEEK_API_KEY'),
    base_url="https://api.deepseek.com")

def llm_call(system_prompt,user_prompt):
    response = client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        stream=False,
        reasoning_effort="high",
        extra_body={"thinking": {"type": "disabled"}}
    )
    return response

relation_list = [{"source":"张三",
        "relation":"打了",
        "target":"李四"}]

pretty_json = json.dumps(relation_list, indent=4, ensure_ascii=False)

system_prompt = f"""
#角色定位
 你是一名经验丰富的人物关系分析专家
#任务定义
 请从用户输入的句子中，提取人物之间的关系
#输出要求
 以json格式输出
#案例
用户输入：张三打了李四
你的输出：
{pretty_json}
"""

user_prompt = f"小明喜欢小姚，但是小姚喜欢小王"

response = llm_call(system_prompt,user_prompt)

print(response.choices[0].message.content)
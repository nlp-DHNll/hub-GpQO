import os
from openai import OpenAI
import json
import ast

client = OpenAI(
    api_key=os.environ.get('DEEPSEEK_API_KEY'),
    base_url="https://api.deepseek.com")

def to_json(source:str,relation:str,target:str):
    """将输入的参数组合起来转化为json格式"""
    data = [{"source":source,"relation":relation,"target":target}]
    return data


tools = [
    {
        "type":"function",
        "function":{
            "name":"to_json",
            "description":"将输入的参数组合起来，转化为json格式",
            "parameters":{
                "type":"object",
                "properties":{
                    "source":{
                        "type":"string",
                        "description":"人物关系主语"
                    },
                    "relation":{
                        "type":"string",
                        "description":"人物关系谓语",
                    },
                    "target":{
                        "type":"string",
                        "description":"人物关系宾语"
                    }
                },
                "required":["source","relation","target"]
            }
        }
    }
]


def llm_call(system_prompt,user_prompt):
    response = client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        stream=False,
        reasoning_effort="high",
        extra_body={"thinking": {"type": "disabled"}},
        tools = tools
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
注意：优先调用工具解决
"""

TOOL = {
    "to_json":to_json
    }


user_prompt = f"小明喜欢小姚"


choice = llm_call(system_prompt,user_prompt)
msg = choice.choices[0].message

if msg.tool_calls:
    name = msg.tool_calls[0].function.name
    arguments = msg.tool_calls[0].function.arguments
    arguments_tmp = json.loads(arguments)
    print(name)
    print(arguments_tmp)
    print(type(arguments_tmp))
else:
    print(msg)

result = TOOL[name](**arguments_tmp)
print(f"工具调用结果:{result}")
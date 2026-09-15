from openai import OpenAI
import json

from pyexpat.errors import messages

client = OpenAI(
    api_key = "sk-arnktcspsrcielntylldhaknxswkvpuqxqjzcwbzyeparuce",
    base_url = "https://api.siliconflow.cn/v1"
)

# 定义工具描述：
tools = [
    {
        "type" : "function",
        "function" : {
            "name" : "get_text_relation",
            "description":"提取文本中人与人之间的情感关系图",
            "parameters" : {
                "relations" : {
                    "type" : "array",
                    "items" : {
                        "type" : "object",
                        "properties" : {
                            "source" : {"type" : "string", "description" : "第一视角情感关系主体"},
                            "relation" : {"type" : "string", "description" : "情感关系，如爱慕，讨厌，喜欢，宠受，敬重等"},
                            "target" : {"type" : "string", "description" : "情感指向的对象人物"}
                        },
                        "required" : ["source", "relation", "target"]
                    }
                }
            }
        }
    }
]

messages = [
    {
        "role":"system",
        "content":"""你是一名非常优秀的情感关系分析专家，严格按照json 格式输出人物关系 ：{"source":"人物1","relation":"情感关系词","target":"人物2"}"""
    },
    {
        "role" : "user", "content": "小明从小到在就非常关心小红，呵护她"
    }
]

response = client.chat.completions.create(
    model = "Pro/deepseek-ai/DeepSeek-R1",
    messages = messages,
    tools = tools
)

print(response.choices[0].message.content)

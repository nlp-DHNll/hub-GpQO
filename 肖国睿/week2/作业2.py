from openai import OpenAI # 结合openai sdk 调用deepseek 模型
import json   #转换字符串


# llm 客户端


client = OpenAI(
    api_key="sk-86fec757d81a42bxxxabu514d55a9c7", # 大模型厂商后台页面 创建api key ，计费  / 并发 / 账单
    base_url="https://api.deepseek.com" # 服务地址，云端地址，运算大模型
)


# 定义抽取工具
TOOLS = [
    {
         "type": "function",   #函数调用
        "function": {
            "name": "build_relation_graph",   #关系图函数
            "description": "构建人物情感关系图谱",
            "parameters": {
                "type": "object",
                "属性": {
                    "relations": {
                        "type": "array",  #数组
                        "description": "人物情感关系数组",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source": {"type": "string", "description": "主体人物"},
                                "relation": {"type": "string", "description": "情感关系，如爱慕、讨厌、平淡"},
                                "target": {"type": "string", "description": "目标人物"}
                            },
                            "required": ["source", "relation", "target"]
                        },
                    },
                },
                "required": ["relations"]
            },
        },
    },


]

SYSTEM_PROMPT = "分析用户文本，调用build_relation_graph工具抽取所有人物情感关系。"

def emotion_agent(text: str):
    resp = client.chat.completions.create(
        model="deepseek-chat",
        tools=TOOLS,
        tool_choice={"type": "function", "function": {"name": "build_relation_graph"}},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text}
        ],
        temperature=0.0
    )
    tool_call = resp.choices[0].message.tool_calls[0]
    args = json.loads(tool_call.function.arguments)
    return args["relations"]


if __name__ == "__main__":
    user_input = "小明喜欢小姚，但是小姚喜欢小王，所以小明讨厌小王。"
    res = emotion_agent(user_input)
    print(json.dumps(res, ensure_ascii=False, indent=4))







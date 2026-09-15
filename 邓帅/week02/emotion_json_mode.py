from openai import OpenAI
from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.chat.chat_completion_tool_union_param import ChatCompletionToolUnionParam
from openai.types.shared_params.response_format_json_schema import JSONSchema
from dotenv import load_dotenv
from typing import List

import os
load_dotenv()

# 借助于llm tool call 或 json mode 能力，构建一个简单的情况情感分析智能体。提交实现代码。
# 输入：小明喜欢小姚，但是小姚喜欢小王。
# 输出：人物关系图谱
# [
#     {
#         "source": "小明",
#         "relation": "爱慕",
#         "target": "小姚"
#     }
# ]

system_prompt = """
# 角色
你是情感分析助手，你的任务是根据用户输入的内容，分析人物关系，构建人物关系图谱。

# 步骤
1. 判断用户输入的内容是否有可以分析的人物关系图谱，若不存在，输出一个空数组。
2. 若存在可以分析的人物关系，一步步对人物关系进行分析。
3. 根据分析结果输出人物关系图谱。
"""

emotion_json_schema: JSONSchema = {
    "name": "emotion_graph",
    "description": "对象数组，表示人物关系图谱",
    "strict": True,
    "schema": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
            "source": {
                "type": "string",
                "description": "情感主体（发起方）"
            },
            "relation": {
                "type": "string",
                "description": "情感关系类型（如“爱慕”、“厌恶”、“中立”等）"
            },
            "target": {
                "type": "string",
                "description": "情感对象（接收方）"
            }
            },
            "required": ["source", "relation", "target"],
            "additionalProperties": False
        },
        "minItems": 0
    }
}

# class EmotionAgent:
#     def __init__(self, model="deepseek-v4-flash") -> None:
#         self.client = OpenAI(
#             api_key=os.getenv("API_KEY"),
#             base_url=os.getenv("BASE_URL")
#         )
#         self.model = model
#         self.message: List[ChatCompletionMessageParam] = [
#             { "role": "system", "content": "你是情感分析助手" }
#         ]
#         pass


class LLM:
    def __init__(self, model="deepseek-v4-flash") -> None:
        self.client = OpenAI(
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("BASE_URL")
        )
        self.model = model
        self.message: List[ChatCompletionMessageParam] = [
            { "role": "system", "content": system_prompt }
        ]
        pass
    
    def append_user_msg(self, content: str):
        self.message.append({
            "role": "user", "content": content
        })
        pass
    
    def append_response_msg(self, msg: ChatCompletionMessage):
        self.message.append({
            "role": msg.role,
            "content": msg.content
        })
    
    def chat(self, content: str):
        self.append_user_msg(content)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=self.message,
            stream=False,
            response_format={"type": "json_schema", "json_schema": emotion_json_schema}
        )
        msg = response.choices[0].message
        self.append_response_msg(msg)
        return msg.content


if __name__ == "__main__":
    llm = LLM()
    msg_content = llm.chat("小明喜欢小姚，但是小姚喜欢小王。")
    print(msg_content)

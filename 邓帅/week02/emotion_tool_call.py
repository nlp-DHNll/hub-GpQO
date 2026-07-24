from openai import OpenAI
from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.chat.chat_completion_tool_union_param import ChatCompletionToolUnionParam
from openai.types.chat.chat_completion_message_tool_call import ChatCompletionMessageToolCall
from openai.types.shared_params.response_format_json_schema import JSONSchema
from dotenv import load_dotenv
from typing import List, Optional
import json
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

# 想不通用 tool call 怎么拆，练习了下怎么用 tool call

tools: List[ChatCompletionToolUnionParam] = [
    {
        "type": "function",
        "function": {
            "name": "emotion_classifier",
            "description": "人物关系图谱生成器，将人物关系说明以对象数组的形式返回",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "人物关系图谱说明",
                    },
                },
                "required": ["text"],
            }
        }
    }
]


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

class BaseChatModel:
    def __init__(self, system_prompt: str, model: str = "deepseek-v4-flash"):
        self.client = OpenAI(
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("BASE_URL")
        )
        self.model = model
        self.message: List[ChatCompletionMessageParam] = [
            { "role": "system", "content": system_prompt }
        ]

    def append_user_msg(self, content: str):
        self.message.append({
            "role": "user", "content": content
        })

    def append_response_msg(self, msg: ChatCompletionMessage):
        self.message.append({
            "role": msg.role,
            "content": msg.content
        })


class EmotionAgent(BaseChatModel):
    def __init__(self):
        super().__init__(system_prompt="你是人物关系图谱构建助手，你的任务是根据人物关系，构建人物关系图谱。")
        
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

def emotion_classifier(text: str):
    agent = EmotionAgent()
    return agent.chat(text) or ""

TOOLS_MAP = {
    "emotion_classifier": emotion_classifier
}


class LLM(BaseChatModel):
    def __init__(self):
        super().__init__(system_prompt="你是情感分析助手，你的任务是根据用户输入的内容，分析人物关系，构建人物关系图谱。")
    
    def tools_call(self, tool_calls: List[ChatCompletionMessageToolCall]):
        for tool in tool_calls:
            if tool.function.name in TOOLS_MAP:
                self.message.append({
                    "role": "tool",
                    "tool_call_id": tool.id,
                    "content": TOOLS_MAP[tool.function.name](**json.loads(tool.function.arguments))
                })

    def chat(self, content: str):
        self.append_user_msg(content)
        while True:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.message,
                stream=False,
                tools=tools,
            )
            msg = response.choices[0].message
            if msg.tool_calls:                    
                self.message.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                })
                self.tools_call(msg.tool_calls)
                continue
            self.append_response_msg(msg)
            return msg.content


if __name__ == "__main__":
    llm = LLM()
    msg_content = llm.chat("小明喜欢小姚，但是小姚喜欢小王。")
    print(msg_content)

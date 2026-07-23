import json
from openai import OpenAI
from typing import List, Dict

# 定义人物关系数据结构
RelationItem = Dict[str, str]
RelationResult = List[RelationItem]


class EmotionRelationAgent:
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com", model: str = "deepseek-v4-flash"):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        # 系统提示词：约束JSON结构与抽取规则
        self.system_prompt = """
你是人物情感关系抽取智能体，严格遵守规则：
1. 仅抽取人与人之间单向爱慕类情感关系；
2. 输出固定JSON数组格式，字段只能为 source(发起方), relation(关系词固定为"爱慕"), target(被爱慕方)；
3. 没有爱慕关系则返回空数组[]；
4. 禁止输出解释、备注、markdown代码块、多余文字，只返回纯净JSON；
5. 识别句式：A喜欢B = A爱慕B，单向关系，不生成反向关系。
"""

        # Tool Call 工具定义
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "extract_emotion_relation",
                    "description": "从文本抽取人物爱慕情感关系图谱",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "relation_list": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "source": {"type": "string", "description": "情感发起人物"},
                                        "relation": {"type": "string", "enum": ["爱慕"], "description": "固定关系词"},
                                        "target": {"type": "string", "description": "情感接收人物"}
                                    },
                                    "required": ["source", "relation", "target"]
                                }
                            }
                        },
                        "required": ["relation_list"]
                    }
                }
            }
        ]

    def run_json_mode(self, user_input: str) -> RelationResult:
        """方案1：使用LLM JSON Mode 强结构化输出"""
        resp = self.client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_input}
            ],
            temperature=0.0
        )
        raw_json = resp.choices[0].message.content
        parsed_data = json.loads(raw_json)
        # 兼容模型外层包裹key的情况，最终标准化为数组
        if isinstance(parsed_data, dict) and "relation_list" in parsed_data:
            return parsed_data["relation_list"]
        elif isinstance(parsed_data, list):
            return parsed_data
        return []

    def run_tool_call(self, user_input: str) -> RelationResult:
        """方案2：使用LLM Tool Call 工具调用抽取关系"""
        resp = self.client.chat.completions.create(
            model=self.model,
            tools=self.tools,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_input}
            ],
            temperature=0.0
        )
        tool_call = resp.choices[0].message.tool_calls[0]
        args = json.loads(tool_call.function.arguments)
        return args.get("relation_list", [])


if __name__ == "__main__":
    # 初始化智能体
    AGENT_API_KEY = "sk-86fec757d81a42b0bf6a8a514d55a9c7"
    agent = EmotionRelationAgent(api_key=AGENT_API_KEY)

    user_sentence = "小明喜欢小姚，但是小姚喜欢小王"

    # 方式1 JSON Mode 执行
    print("===== JSON Mode 输出人物关系图谱 =====")
    json_result = agent.run_json_mode(user_sentence)
    print(json.dumps(json_result, ensure_ascii=False, indent=4))

    # 方式2 Tool Call 工具调用执行
    print("\n===== Tool Call 输出人物关系图谱 =====")
    tool_result = agent.run_tool_call(user_sentence)
    print(json.dumps(tool_result, ensure_ascii=False, indent=4))
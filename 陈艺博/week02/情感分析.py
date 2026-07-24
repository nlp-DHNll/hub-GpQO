# 导包
import json
from openai import OpenAI


# 使用 硅基流动
client = OpenAI(
    api_key="sk-gxfmvalpdxxxabupekmvblrdbryshodzugct",
    base_url="https://api.siliconflow.cn/v1",
)


# 定义函数
def extract_relations(text: str) -> list:
    # 定义 tools
    tools = [
        {
            # 固定写法
            "type": "function",
            # 固定写法
            "function": {
                # 函数名
                "name": "record_relations",
                # 描述信息 供AI使用
                "description": "记录文本中所有人物之间的关系",
                # 调用函数时入参
                "parameters": {
                    # 固定写法 参数对象
                    "type": "object",
                    # 定义属性
                    "properties": {
                        # 属性名
                        "relations": {
                            # 参数对象 关系数组
                            "type": "array",
                            # 描述信息 供AI查看
                            "description": "关系列表",
                            # 数组中 列表
                            "items": {
                                # 每一个元素对象
                                "type": "object",
                                # 对象属性
                                "properties": {
                                    "source": {
                                        "type": "string",
                                        "description": "关系发起方人物名称"
                                    },
                                    "relation": {
                                        "type": "string",
                                        "description": "关系类型，例如'爱慕'、'讨厌'等"
                                    },
                                    "target": {
                                        "type": "string",
                                        "description": "关系接收方人物名称"
                                    }
                                },
                                # 必须返回的参数
                                "required": [
                                    "source",
                                    "relation",
                                    "target"
                                ]
                            }
                        }
                    },
                    # 必须返回的参数
                    "required": ["relations"]
                }
            }
        }
    ]
    messages = [
        {"role": "system", "content": "你是一个情感分析专家，请根据给定文本准确提取人物之间的情感关系。注意：请将'喜欢'统一表达为'爱慕'，将'不喜欢'表达为'讨厌'"},
        {"role": "user", "content": f"文本：{text}"}
    ]
    # 调用api
    response = client.chat.completions.create(
        model="deepseek-ai/DeepSeek-V4-Flash",
        messages=messages,
        tools=tools,
        # 强制调用
        tool_choice={"type": "function", "function": {"name": "record_relations"}},
        temperature=0.0,
    )

    # 返回的信息
    message = response.choices[0].message
    if message.tool_calls is None:
        raise ValueError("模型未返回工具调用，请检查提示词或模型能力。")

    tool_call = message.tool_calls[0]
    # 将JSON 字符串解析成 Python 字典
    arguments = json.loads(tool_call.function.arguments)
    return arguments.get("relations", [])

# 测试
if __name__ == "__main__":
    input_text = "小明喜欢小姚，小姚喜欢小王，但是小王不喜欢小姚。"
    relations = extract_relations(input_text)

    # 输出关系图谱（JSON 数组）  将 Python 列表转换为格式化的 JSON 字符串  ensure_ascii=False 保证中文正常显示  indent=2 进行缩进美化
    print(json.dumps(relations, ensure_ascii=False, indent=2))

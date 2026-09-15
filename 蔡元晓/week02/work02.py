##json mode
from openai import OpenAI
import json


# 初始化客户端
client = OpenAI(
    api_key="***",
    base_url="https://api.deepseek.com"
)


SYSTEM_PROMPT = """
你是一个人物情感关系抽取智能体。

你的任务：
从输入文本中识别人物之间的情感关系，并生成关系图谱。

输出JSON格式：

{
  "relations": [
    {
      "source": "人物名称",
      "relation": "人物关系",
      "target": "人物名称"
    }
  ]
}

规则：
1. source表示情感关系发起方
2. target表示情感关系接收方
3. relation表示两个人之间的情感关系
4. 例如：
   小明喜欢小姚

   输出：
   {
     "source": "小明",
     "relation": "爱慕",
     "target": "小姚"
   }

5. 只输出JSON，不要输出解释文字
"""


def extract_relation(input_text):

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": input_text
            }
        ],
        response_format={
            "type": "json_object"
        },
        stream=False
    )

    content = response.choices[0].message.content

    if content is None:
        raise ValueError("LLM返回为空")

    parsed_result = json.loads(content)

    return parsed_result


if __name__ == "__main__":

    text = "小明喜欢小姚，但是小姚喜欢小王。"

    result = extract_relation(text)

    print(
        json.dumps(
            result["relations"],
            ensure_ascii=False,
            indent=2
        )
    )
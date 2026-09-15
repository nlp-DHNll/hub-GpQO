"""
作业：借助 LLM 的 JSON Mode / Tool Call 能力，构建一个简单的情感（人物关系）分析智能体。

需求：
  输入：一段描述人物之间关系的自然语言文本。
        例如：小明喜欢小姚，但是小姚喜欢小王。
  输出：人物关系图谱（JSON 数组），每条关系包含：
        - source: 关系发起者
        - relation: 关系/情感类型（如 爱慕、暗恋、讨厌 等）
        - target: 关系指向者
        例如：
        [
            {"source": "小明", "relation": "爱慕", "target": "小姚"},
            {"source": "小姚", "relation": "爱慕", "target": "小王"}
        ]

实现思路：
  参考 04_Tools.py（工具调用）和 05_JsonMode.py（结构化 JSON 输出）。
  这里主要采用 JSON Mode 让模型直接输出结构化的关系三元组，
  同时提供一个基于 Tool Call 的等价实现作为对比。

参考：https://api-docs.deepseek.com/guides/json_mode
"""

import json
from openai import OpenAI

client = OpenAI(
    api_key="sk-e16dfcaa8c7e43xxxabu4d922f96c4a8f",
    base_url="https://api.deepseek.com",
)

MODEL = "deepseek-v4-flash"


# ═════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ═════════════════════════════════════════════════════════════════════════════

def safe_json_parse(text: str) -> dict | list | None:
    """安全解析 JSON，处理可能的空 content 和格式异常。"""
    if not text or not text.strip():
        print("    ⚠️  模型返回了空 content（JSON 模式偶发问题）")
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"    ⚠️  JSON 解析失败: {e}")
        # 尝试修复常见问题：删除 markdown 代码块标记
        cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            print(f"    原始内容: {text[:200]}")
            return None


def extract_relations(result) -> list:
    """从模型返回结果中提取关系数组，兼容多种外层包装形式。"""
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        # 兼容 {"relations": [...]} / {"graph": [...]} / {"data": [...]} 等
        for key in ("relations", "graph", "data", "items", "result"):
            if isinstance(result.get(key), list):
                return result[key]
    return []


# ═════════════════════════════════════════════════════════════════════════════
# 方案一：JSON Mode 实现（推荐）—— 让模型直接输出结构化关系三元组
# ═════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT_JSON = """
你是一个人物关系（情感）分析智能体。请从用户提供的文本中，抽取出人物之间的关系，
构建人物关系图谱，并以 JSON 格式输出。

要求：
- 输出一个 JSON 对象，包含字段 relations，其值为关系数组。
- 数组中每一条关系包含三个字段：
    - source:   关系的发起者（人物姓名）
    - relation: 关系或情感类型，用简洁的中文词语描述，如 爱慕、暗恋、喜欢、讨厌、朋友 等
    - target:   关系的指向者（人物姓名）
- 只抽取文本中明确表达的关系，不要臆造。
- 每一个方向的关系单独作为一条记录。

JSON 输出示例：
{
    "relations": [
        {"source": "小明", "relation": "爱慕", "target": "小姚"}
    ]
}
"""


def analyze_by_json_mode(text: str) -> list:
    """使用 JSON Mode 分析人物关系，返回关系数组。"""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_JSON},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
        max_tokens=800,
        temperature=0.0,
    )
    content = response.choices[0].message.content
    result = safe_json_parse(content)
    return extract_relations(result)


# ═════════════════════════════════════════════════════════════════════════════
# 方案二：Tool Call 实现 —— 让模型通过调用工具来"提交"关系图谱
# ═════════════════════════════════════════════════════════════════════════════

# 用于收集模型提交的关系图谱
_collected_graph: list = []


def submit_relation_graph(relations: list) -> str:
    """工具函数：接收模型抽取出的人物关系图谱。"""
    _collected_graph.clear()
    _collected_graph.extend(relations)
    return f"已收到 {len(relations)} 条关系。"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "submit_relation_graph",
            "description": "提交从文本中抽取出的人物关系图谱",
            "parameters": {
                "type": "object",
                "properties": {
                    "relations": {
                        "type": "array",
                        "description": "人物关系数组",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source": {"type": "string", "description": "关系发起者"},
                                "relation": {"type": "string", "description": "关系/情感类型，如 爱慕、讨厌"},
                                "target": {"type": "string", "description": "关系指向者"},
                            },
                            "required": ["source", "relation", "target"],
                        },
                    },
                },
                "required": ["relations"],
            },
        },
    },
]


def analyze_by_tool_call(text: str) -> list:
    """使用 Tool Call 分析人物关系，返回关系数组。"""
    _collected_graph.clear()
    messages = [
        {"role": "system", "content": "你是一个人物关系分析智能体，请抽取文本中的人物关系，"
                                      "并调用 submit_relation_graph 工具提交关系图谱。"},
        {"role": "user", "content": text},
    ]
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=TOOLS,
        tool_choice={"type": "function", "function": {"name": "submit_relation_graph"}},
        temperature=0.0,
        extra_body={"thinking": {"type": "disabled"}},
    )
    msg = response.choices[0].message
    if msg.tool_calls:
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            submit_relation_graph(args.get("relations", []))
    return list(_collected_graph)


# ═════════════════════════════════════════════════════════════════════════════
# 主程序：演示两种方案
# ═════════════════════════════════════════════════════════════════════════════

def print_graph(relations: list) -> None:
    """打印关系图谱。"""
    if not relations:
        print("  （未抽取到人物关系）")
        return
    for i, r in enumerate(relations, 1):
        print(f"  {i}. {r.get('source')} --[{r.get('relation')}]--> {r.get('target')}")
    print(f"\n  JSON 输出:\n{json.dumps(relations, ensure_ascii=False, indent=2)}")


if __name__ == "__main__":
    text = "大雄喜欢静香 讨厌胖虎 胖虎喜欢静香 羡慕大雄。"

    print("=" * 65)
    print("输入文本：", text)
    print("=" * 65)

    print("\n【方案一】JSON Mode")
    graph_json = analyze_by_json_mode(text)
    print_graph(graph_json)

    print("\n" + "=" * 65)
    print("\n【方案二】Tool Call")
    graph_tool = analyze_by_tool_call(text)
    print_graph(graph_tool)

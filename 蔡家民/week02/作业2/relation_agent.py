"""
情感分析智能体 — 人物关系图谱提取
====================================
作业2：借助 LLM 的 JSON Mode 能力，从一句话中提取人物之间的情感关系。

输入：小明喜欢小姚，但是小姚喜欢小王。
输出：
[
    {"source": "小明", "relation": "爱慕", "target": "小姚"},
    {"source": "小姚", "relation": "爱慕", "target": "小王"}
]

运行方式：
    conda run -n py312 python src/relation_agent.py
"""

import os
import json
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# ── 1. 加载 API 配置
_ENV_PATH = Path(__file__).resolve().parent.parent/ "llm.deepseek.env"
load_dotenv(_ENV_PATH)

client = OpenAI(
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL"),
)
MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")


# ── 2. 提示词：告诉模型怎么抽取关系，并给出 JSON 输出样例 ──────────────
SYSTEM_PROMPT = """
你是一个人物关系抽取助手。请从用户输入的文本中分析出人物之间的情感/社会关系。

要求：
1. 找出文本中所有人物两两之间明确表达的关系。
2. relation（关系类型）用简洁的中文词，例如："爱慕"、"喜欢"、"讨厌"、"朋友"、"敌人"、"父子"等。
3. 只输出一个 JSON 对象，格式为 {"relations": [...]}，不要输出多余文字。

JSON 输出示例：
{
    "relations": [
        {"source": "小明", "relation": "爱慕", "target": "小姚"},
        {"source": "小姚", "relation": "爱慕", "target": "小王"}
    ]
}
"""


def safe_json_parse(text: str):
    """安全解析 JSON，处理空返回和 markdown 代码块。"""
    if not text or not text.strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None


def extract_relations(text: str) -> list:
    """调用大模型，从文本中提取人物关系列表。"""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},  # 开启 JSON Mode
        max_tokens=800,
        temperature=0.0,
    )

    content = response.choices[0].message.content
    result = safe_json_parse(content)

    
    if not result:
        print("⚠️  模型返回内容无法解析为 JSON：", content)
        return []

    if isinstance(result, str):
        print("⚠️  模型返回了字符串而非 JSON 对象：", result)
        return []

    if isinstance(result, list):
        return result

    if isinstance(result, dict):
        return result.get("relations", [])

    return []


# ── 3. 命令行运行入口 ─────────────────────────────────────────────
if __name__ == "__main__":

    if not client.api_key or "sk-your" in client.api_key:
        print("⚠️  请先在 asserts/llm.deepseek.env 中配置 LLM_API_KEY")
        raise SystemExit(1)

    print(f"当前模型：{MODEL}\n")

    default_text = "小明喜欢小姚，但是小姚喜欢小王。"

    # 允许用户输入，直接回车则用默认句子；无交互环境下自动用默认句子
    try:
        user_input = input(f"请输入一句话（直接回车使用默认：{default_text}）：\n> ").strip()
    except EOFError:
        user_input = ""
    text = user_input if user_input else default_text

    print(f"\n输入：{text}")
    print("分析中...\n")

    relations = extract_relations(text)

    print("=" * 50)
    print("人物关系图谱：")
    print("=" * 50)
    print(json.dumps(relations, ensure_ascii=False, indent=4))

    print("\n可读版本：")
    for r in relations:
        print(f"  {r.get('source')} --[{r.get('relation')}]--> {r.get('target')}")
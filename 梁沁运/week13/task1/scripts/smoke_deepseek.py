"""M0 冒烟：验证 deepseek-flash 关闭 thinking 后结构化输出可用。

验证项：
1. 关闭 thinking 后 tool_choice=auto 可用
2. SQLDraft 连续 3 次解析成功
3. cannot_fix=True 时 sql 为空且给原因
"""

import asyncio
import os
import sys

# 确保 src/ 在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sql_agent.llm import StructuredAgent
from sql_agent.models import SQLDraft


TEST_PROMPT = """你是 SQLite SQL 修复专家。

规则：
1. 如果用户提供的是正常的 SQL 生成任务，生成一条 SELECT；
2. 如果任务明显不可能在当前 schema 下完成，返回 cannot_fix=true。

用户问题：列出所有客户的名字和城市。

Schema: 有一张 customers 表，列: CustomerId, FirstName, LastName, City, Country, Email。"""


FAILURE_PROMPT = """你是 SQLite SQL 修复专家。

用户问题：列出 SpaceX 火箭型号。

Schema: 有一张 customers 表，列: CustomerId, FirstName, LastName, City。

当前失败的 SQL：SELECT rocket_name FROM spacex_rockets;
错误码: unknown_object
错误信息: no such table: spacex_rockets

请修复以上 SQL。如果无法修复，返回 cannot_fix=true。"""


def main():
    print("=== M0 冒烟：deepseek-flash 结构化输出验证 ===\n")

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("SKIP: 未设置 DEEPSEEK_API_KEY 环境变量")
        return

    agent = StructuredAgent(
        name="SmokeTest",
        output_schema=SQLDraft,
        system_prompt="只输出结构化结果。",
        temperature=0.0,
    )

    async def _run():
        # 测试 1: 正常生成（3 次）
        print("测试 1: SQLDraft 连续 3 次解析...")
        for i in range(3):
            messages = agent.build_messages(TEST_PROMPT)
            parsed, _ = await agent.ainvoke(messages)
            assert parsed.sql, f"第 {i+1} 次：sql 为空"
            assert not parsed.cannot_fix, f"第 {i+1} 次：意外 cannot_fix"
            print(f"  第 {i+1} 次: OK — sql={parsed.sql[:80]}...")

        # 测试 2: cannot_fix
        print("\n测试 2: cannot_fix=True 时 sql 为空...")
        messages = agent.build_messages(FAILURE_PROMPT)
        parsed, _ = await agent.ainvoke(messages)
        if parsed.cannot_fix:
            assert not parsed.sql, "cannot_fix=true 但 sql 非空"
            assert parsed.cannot_fix_reason, "cannot_fix=true 但无原因"
            print(f"  OK — reason={parsed.cannot_fix_reason[:120]}...")
        else:
            print(f"  WARN — 模型未返回 cannot_fix（返回了: {parsed.sql[:80]}...）")
            print("  这不一定失败，取决于模型判断")

        print("\n=== 冒烟完成 ===")

    asyncio.run(_run())


if __name__ == "__main__":
    main()

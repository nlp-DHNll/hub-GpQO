"""week12 job2：用 LangChain(LCEL) 的多 Agent 架构重构 week11 的 DB 查询方案。

链路：
    SchemaAgent（选表）
      -> SqlGeneratorAgent（生成 SQL）
      -> SqlGuard（只读校验 + EXPLAIN 试跑）
      -> SqlCriticAgent（语义审查）
      -> SqlRepairAgent（不通过时修复）
      -> SqlExecutor（执行）
      -> AnalystAgent（解读结果）

具体实现都在 project/ 包里，本文件只负责发起查询与处理未配置 Key 的情况。

用法：
    python job2.py                      # 跑文件里的默认问题
    python job2.py "问题内容"            # 跑指定问题
"""

import sys
from pathlib import Path

# 允许直接 `python job2.py` 运行：把当前目录加入模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from project import DB_PATH, describe_database, is_key_configured, run_query

# 默认问题：需要 tracks + genres 两张表 JOIN + 聚合排序
QUESTION = "每种音乐类型（genre）下有多少首曲目？请按数量从多到少给出前 5 名。"

# 其他验证用例（取消注释即可切换）：
# 单表场景：只需 invoices 的 BillingCountry
# QUESTION = "哪个国家（BillingCountry）的订单总金额最高？给出国家和总金额。"
# 四表链路：playlists + playlist_track + tracks + genres
# QUESTION = "播放列表 'Music' 里包含哪些曲目？列出前 10 首的曲名和它们的音乐类型。"


def main() -> None:
    """发起一次查询；未配置 API Key 时退化为只展示数据库结构。"""
    question = sys.argv[1] if len(sys.argv) > 1 else QUESTION

    print(f"数据库：{DB_PATH}")
    if not is_key_configured():
        print("\n[提示] 尚未配置 DEEPSEEK_API_KEY，以下仅展示数据库解析结果；")
        print("       设置环境变量 DEEPSEEK_API_KEY，或修改 project/config.py 后重新运行。\n")
        print(describe_database())
        return

    result = run_query(question)

    print("\n---------- 运行摘要 ----------")
    print(f"选中表：{result['tables']}")
    print(f"轮次：{result['rounds']}")
    print(f"SQL：{result['sql']}")


if __name__ == "__main__":
    main()

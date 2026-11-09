"""week13 job1：用 LangGraph 重构的 SQL 检索智能体（CLI 入口）。

链路：
    Router（相关性路由）
      -> Refuse（不相关问题拒绝）或 Schema（选表）
      -> Generate（生成 SQL）-> Guard（只读守卫）-> Critic（语义审查）
      -> Repair（失败时修复）-> Execute（执行）-> Analyze（解读）

具体实现都在 sql_agent/ 包里，本文件只负责发起查询与处理未配置 Key 的情况。

用法：
    python main.py                        # 跑默认问题
    python main.py "问题内容"              # 跑指定问题
    python main.py --show-graph           # 打印图结构（节点与边）
"""

import sys
from pathlib import Path

# 允许直接 `python main.py` 运行：把当前目录加入模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sql_agent import DB_PATH, build_graph, describe_database, is_key_configured, run_agent

# 默认问题：需要 tracks + genres 两张表 JOIN + 聚合排序
QUESTION = "每种音乐类型（genre）下有多少首曲目？请按数量从多到少给出前 5 名。"

# 其他验证用例（取消注释即可切换）：
# 拒绝用例：验证业务范围拦截
# QUESTION = "帮我写一首浪漫的情诗"
# 单表场景：只需 invoices 的 BillingCountry
# QUESTION = "哪个国家（BillingCountry）的订单总金额最高？给出国家和总金额。"
# 四表链路：playlists + playlist_track + tracks + genres
# QUESTION = "播放列表 'Music' 里包含哪些曲目？列出前 10 首的曲名和它们的音乐类型。"


def _print_graph() -> None:
    """打印 LangGraph 图结构。

    仅展示节点与边，不发起任何 LLM 调用；
    因此用占位 Key 构建模型即可（ChatOpenAI 构建时不发网络请求）。
    """
    graph = build_graph(api_key="graph-preview-only")
    drawable = graph.get_graph()
    print("\n[节点]")
    for node in sorted(drawable.nodes):
        print(f"  - {node}")
    print("\n[边]")
    for edge in drawable.edges:
        print(f"  {edge.source} -> {edge.target}")


def main() -> None:
    """发起一次查询；未配置 API Key 时退化为只展示数据库结构。"""
    args = sys.argv[1:]

    if "--show-graph" in args:
        _print_graph()
        return

    question = " ".join(a for a in args if not a.startswith("-")) or QUESTION

    print(f"数据库：{DB_PATH}")
    if not is_key_configured():
        print("\n[提示] 尚未配置 DEEPSEEK_API_KEY，以下仅展示数据库解析结果；")
        print("       设置环境变量 DEEPSEEK_API_KEY、创建 .env，")
        print("       或修改 sql_agent/config.py 占位处后重新运行。\n")
        print(describe_database())
        return

    result = run_agent(question, echo=True)

    print("\n---------- 运行摘要 ----------")
    print(f"被拒绝：{result['rejected']}")
    print(f"选中表：{result['tables']}")
    print(f"轮次：{result['rounds']}")
    print(f"SQL：{result['sql']}")
    print(f"\n最终答案：\n{result['answer']}")


if __name__ == "__main__":
    main()

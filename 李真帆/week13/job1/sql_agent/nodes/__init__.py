"""图节点层：每个节点一个文件，由 graph.py 装配。

节点统一为工厂函数 ``make_xxx_node(...)``，返回签名
``(state: GraphState, config: RunnableConfig) -> dict`` 的可调用对象。
"""

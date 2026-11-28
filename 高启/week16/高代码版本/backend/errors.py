"""Agent 可记录和展示的业务错误。"""


class RunFailure(Exception):
    """可直接向用户说明的运行失败，例如搜索服务鉴权错误。"""


class SourceRejected(Exception):
    """一条候选资料无法核验，筛选时记录原因并检查下一条。"""

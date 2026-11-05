"""作业二：SQL Agent 网页聊天后端。

模块划分：

* ``paths``     —— 让作业二直接复用作业一里的 ``sql_agent_lg``；
* ``config``    —— Web 层自己的环境变量；
* ``schemas``   —— 前后端 JSON 契约；
* ``service``   —— 多轮改写 + 图执行 + 结果转换；
* ``demo``      —— 无 API Key 的离线演示；
* ``main``      —— FastAPI 应用工厂、REST 与 SSE 路由。
"""

# 先执行 paths：把同级目录「作业一」加入 sys.path，
# 后面的模块才能 import sql_agent_lg。
from . import paths as _paths  # noqa: F401
from .main import create_app

__all__ = ["create_app"]

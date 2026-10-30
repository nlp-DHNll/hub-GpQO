"""SQL Agent（LangChain 版）——把 week11 的 openai-agents 实现复刻一遍。

对外只需两个名字：
    SQLAgentWorkflow   编排器
    WorkflowOutput     最终 JSON 契约
"""

from .models import WorkflowOutput
from .workflow import SQLAgentWorkflow

__version__ = "1.0.0"

__all__ = ["SQLAgentWorkflow", "WorkflowOutput", "__version__"]

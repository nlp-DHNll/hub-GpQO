"""
基础Agent类，定义所有Agent的公共接口和行为
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
import json
import logging
from datetime import datetime

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Agent执行结果的数据类"""
    success: bool
    data: Any
    metadata: Dict[str, Any] = None
    error: Optional[str] = None
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    def to_json(self) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class BaseAgent(ABC):
    """基础Agent抽象类"""

    def __init__(self, name: str, description: str):
        """
        初始化Agent

        Args:
            name: Agent名称
            description: Agent描述
        """
        self.name = name
        self.description = description
        self.execution_history: List[Dict[str, Any]] = []
        logger.info(f"初始化Agent: {name} - {description}")

    @abstractmethod
    async def execute(self, input_data: Any, context: Dict[str, Any] = None) -> AgentResult:
        """
        执行Agent的主要任务

        Args:
            input_data: 输入数据
            context: 执行上下文

        Returns:
            AgentResult: 执行结果
        """
        pass

    def log_execution(self, input_data: Any, result: AgentResult, context: Dict[str, Any] = None):
        """
        记录执行历史

        Args:
            input_data: 输入数据
            result: 执行结果
            context: 执行上下文
        """
        execution_record = {
            "agent_name": self.name,
            "timestamp": datetime.now().isoformat(),
            "input": input_data,
            "result": result.to_dict(),
            "context": context or {}
        }
        self.execution_history.append(execution_record)
        logger.info(f"Agent {self.name} 执行记录已保存")

    def get_execution_history(self) -> List[Dict[str, Any]]:
        """
        获取执行历史

        Returns:
            执行历史列表
        """
        return self.execution_history

    def clear_history(self):
        """清空执行历史"""
        self.execution_history.clear()
        logger.info(f"Agent {self.name} 执行历史已清空")

    def __str__(self) -> str:
        """字符串表示"""
        return f"Agent(name={self.name}, description={self.description})"

    def __repr__(self) -> str:
        """表示"""
        return f"BaseAgent(name={self.name}, description={self.description})"
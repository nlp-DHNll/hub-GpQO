# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

这是一个深度研究助手系统，支持自动化研究流程。输入研究主题，系统自动完成检索、阅读、迭代、综合，产出结构化研究报告。

## 项目结构

```
deep-research-assistant/
├── base_agent.py          # 基础Agent抽象类和数据结构
├── keyword_agent.py       # 关键词生成Agent
├── quality_agent.py       # 质量判断Agent
├── summarization_agent.py # 内容总结Agent
├── report_agent.py        # 报告生成Agent
├── research_assistant.py  # 主应用和工作流管理
├── example_usage.py       # 使用示例和演示
├── requirements.txt       # 项目依赖（备注）
├── README.md             # 项目文档
└── outputs/              # 输出目录（自动创建）
```

## 架构设计

系统采用Agent-based架构：
- **BaseAgent**: 所有Agent的基类，定义执行接口和历史记录
- **KeywordGeneratorAgent**: 生成搜索关键词，支持迭代优化
- **QualityJudgmentAgent**: 判断内容质量（相关性、权威性、时效性）
- **SummarizationAgent**: 总结搜索结果，识别信息缺口
- **ReportGeneratorAgent**: 生成结构化研究报告
- **ResearchWorkflow**: 管理工作流，协调Agent执行

## 常用命令

### 运行示例
```bash
# 显示系统功能和示例
python example_usage.py

# 交互式使用研究助手  
python research_assistant.py

# 直接研究特定主题
python research_assistant.py "Python数据分析工具竞品对比"
```

### 开发命令
```bash
# 运行所有Agent的独立测试（在每个Agent文件末尾都有测试代码）
python keyword_agent.py  # 测试关键词生成
python quality_agent.py  # 测试质量判断
python summarization_agent.py  # 测试内容总结
python report_agent.py   # 测试报告生成
```

## Agent执行流程

1. **初始化**: `ResearchWorkflow()` 创建所有Agent实例
2. **研究执行**: `execute_research()` 启动多轮迭代研究
3. **单轮迭代**:
   - 关键词生成 (`KeywordGeneratorAgent`)
   - 模拟搜索 (`_simulate_search_process`)
   - 质量判断 (`QualityJudgmentAgent`) 
   - 内容总结 (`SummarizationAgent`)
4. **报告生成**: `ReportGeneratorAgent` 整合所有迭代结果
5. **输出**: 保存到 `outputs/` 目录

## 关键文件说明

### base_agent.py
- `BaseAgent` 抽象基类，所有Agent必须继承
- `AgentResult` 数据类，标准化Agent执行结果
- 提供执行历史记录、日志记录功能

### keyword_agent.py
- `KeywordGeneratorAgent` 生成搜索关键词
- 支持多轮迭代优化关键词
- 提供关键词分类（核心概念、技术术语、竞品名称等）
- 生成搜索策略建议

### quality_agent.py  
- `QualityJudgmentAgent` 评估内容质量
- 评估维度：相关性、权威性、时效性
- 为搜索结果、中间内容、最终报告提供质量判断

### summarization_agent.py
- `SummarizationAgent` 总结内容
- 对搜索结果进行分类和筛选
- 提取关键洞察，构建知识图谱（简化版）
- 识别信息缺口

### report_agent.py
- `ReportGeneratorAgent` 生成研究报告
- 输出四种产物：结构报告、来源列表、研究记录、置信说明
- 验证报告完整性和质量
- 支持Markdown等多种格式导出

### research_assistant.py
- `ResearchWorkflow` 管理工作流的主类
- 控制多轮迭代研究过程
- 提供命令行接口和API接口
- 输出格式转换和文件保存

## 扩展指南

### 集成真实搜索引擎
当前使用模拟搜索结果，需要在 `research_assistant.py` 中修改 `_simulate_search_process` 函数：
- 替换为Google Custom Search API
- 或DuckDuckGo Search API
- 或学术数据库API (IEEE Xplore, CNKI等)

### 集成LLM增强
可以在各个Agent的execute方法中集成LLM：
- 使用OpenAI GPT进行内容分析
- 使用Claude进行质量判断
- 使用本地模型生成报告

### 添加数据库存储
扩展 `_save_research_history` 方法，支持：
- SQLite 本地存储
- PostgreSQL 生产环境
- MongoDB 文档存储

## 调试技巧

### 日志级别
```python
import logging
logging.basicConfig(level=logging.DEBUG)  # 调试信息
```

### Agent独立测试
每个Agent文件都有独立的测试代码，在文件末尾：
```bash
python keyword_agent.py  # 测试关键词生成
```

### 查看历史记录
研究过程记录保存在 `research_history` 列表中，可以通过 `ResearchWorkflow` 访问。

## 性能考虑

1. **并行处理**: 使用 `asyncio.gather()` 并行执行多Agent任务
2. **缓存结果**: 重复关键词搜索应缓存结果
3. **增量更新**: 只处理新的或修改过的内容
4. **资源限制**: 设置每个阶段的最大处理数量

## 设计原则

1. **模块化**: 每个Agent职责单一，可独立测试
2. **可扩展**: 易于添加新Agent或扩展现有功能
3. **错误恢复**: Agent执行失败不影响整个工作流
4. **可追溯**: 所有结论都有来源引用
5. **质量保证**: 每个步骤都有质量控制和验证

## 注意事项

1. **目前使用模拟数据**: 搜索结果是模拟的，需要替换为真实API
2. **无外部依赖**: 当前仅使用Python标准库
3. **中文优先**: 关键词生成和报告输出主要支持中文
4. **迭代优化**: 系统支持多轮迭代改进搜索结果
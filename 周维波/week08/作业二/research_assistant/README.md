# 深度研究助手 (Deep Research Assistant)

一个自动化的深度研究工具，支持竞品分析、行业趋势、技术选型、政策解读等多种研究类型。

## 🎯 核心功能

- **完全自动化研究流程**: 输入研究主题，自动完成检索、分析、迭代、综合
- **四类输出产物**:
  1. 结构化研究报告（摘要、分节正文、关键结论、遗留问题）
  2. 来源列表（每条结论关联URL/标题/来源，可追溯）
  3. 研究过程记录（检索关键词、阅读页面、迭代轮次）
  4. 置信度说明（结论可靠性、信息截止时间、模型推断标注）
- **多轮迭代优化**: 根据每轮结果自动调整关键词和搜索策略
- **质量控制系统**: 自动评估相关性、权威性、时效性

## 🏗️ 系统架构

```
研究主题
    ↓
关键词生成Agent → 相关关键词，搜索策略建议
    ↓
信息检索API → 搜索结果（可替换为真实搜索API）
    ↓
质量判断Agent → 相关性、权威性、时效性评估
    ↓
内容总结Agent → 结构化总结，知识图谱，信息缺口识别
    ↓
报告生成Agent → 完整研究报告，包含四类输出产物
    ↓
多轮迭代优化
```

### Agent设计

```python
# 基类
BaseAgent
├─ 基础Agent类，定义了所有Agent的公共接口和行为
├─ 支持执行历史记录、结果标准化、错误处理

# 具体Agent
├─ KeywordGeneratorAgent         # 关键词生成Agent
│   ├─ 根据研究主题生成搜索关键词
│   ├─ 支持多轮迭代优化
│   └─ 生成搜索策略建议
├─ QualityJudgmentAgent          # 质量判断Agent
│   ├─ 判断搜索结果相关性和内容质量
│   ├─ 评估权威性、时效性
│   └─ 给出处理建议
├─ SummarizationAgent            # 内容总结Agent
│   ├─ 对搜索结果进行总结和提炼
│   ├─ 构建知识图谱
│   └─ 识别信息缺口
└─ ReportGeneratorAgent          # 报告生成Agent
    ├─ 生成结构化研究报告
    ├─ 整合四类输出产物
    └─ 验证报告质量
```

## 🚀 快速开始

### 安装

```bash
# 克隆项目
git clone <repository-url>
cd deep-research-assistant

# 确保已安装Python 3.8+
python --version

# 直接运行（系统使用标准库，无需额外依赖）
python research_assistant.py
```

### 基本使用

```bash
# 通过命令行参数指定研究主题
python research_assistant.py "Python数据分析工具竞品对比"

# 交互式使用
python research_assistant.py
# 输入研究主题: 人工智能在医疗行业的应用趋势
# 输入关键词: AI医疗, 智能诊断, 药物研发 (可选)
# 迭代轮次: 3 (可选)
```

### Python API使用

```python
from research_assistant import ResearchWorkflow
import asyncio

async def run_research():
    workflow = ResearchWorkflow()
    result = await workflow.execute_research(
        research_topic="新能源汽车技术发展趋势",
        initial_keywords=["电动车", "电池技术", "自动驾驶"],
        max_iterations=3
    )
    
    # 显示研究摘要
    print(workflow.display_research_summary(result))
    
    # 导出报告
    formats = workflow.export_report_formats(result)
    if "markdown" in formats:
        with open("report.md", "w", encoding="utf-8") as f:
            f.write(formats["markdown"])

asyncio.run(run_research())
```

### 运行示例

```bash
# 展示系统功能和样例
python example_usage.py
```

## 📁 项目结构

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

## 🔧 配置与定制

### 修改搜索来源

目前系统使用模拟搜索结果。要连接真实搜索引擎：

```python
# 在research_assistant.py中修改_simulate_search_process函数
async def _simulate_search_process(self, keywords, research_topic, iteration):
    # 替换为真实搜索API调用，例如：
    # - Google Custom Search API
    # - DuckDuckGo Search
    # - 学术数据库API (IEEE Xplore, CNKI等)
    # - 新闻API
    pass
```

### 调整迭代策略

```python
# 修改_max_iterations控制最大迭代轮次
self.max_iterations = 3  # 默认3轮

# 修改_should_stop_iteration控制停止条件
def _should_stop_iteration(self, iteration_result, iteration):
    # 自定义停止条件
    high_quality_count = iteration_result.get("high_quality_count", 0)
    if high_quality_count >= 5:  # 当高质量结果达到5个时停止
        return True
    return False
```

### 自定义报告模板

```python
# 在report_agent.py中修改report_template
self.report_template = {
    "metadata": {},
    "summary": {},
    "structured_content": {},
    "key_conclusions": [],
    "open_questions": [],
    "sources": {},
    "confidence_statements": [],
    "research_process": {}
}
```

## 📊 支持的研究类型

### 1. 竞品分析
- **输入示例**: "CRM系统竞品对比"
- **关键词生成**: Salesforce vs HubSpot, CRM功能对比, 用户评价
- **输出重点**: 功能对比表, 优劣势分析, 适用场景建议

### 2. 行业趋势
- **输入示例**: "人工智能在金融行业应用趋势"
- **关键词生成**: AI金融, 智能投顾, 风险控制, 发展趋势
- **输出重点**: 技术应用现状, 市场预测, 发展方向

### 3. 技术选型
- **输入示例**: "前端开发框架技术选型"
- **关键词生成**: React vs Vue, 性能对比, 学习曲线, 生态成熟度
- **输出重点**: 技术对比, 选型建议, 迁移成本评估

### 4. 政策解读
- **输入示例**: "数据安全法合规要求解读"
- **关键词生成**: 数据安全法条款, 监管要求, 合规指南, 企业应对
- **输出重点**: 政策要点, 合规建议, 实施步骤

## 🔍 工作原理

### 迭代式研究流程

1. **第一轮迭代**
   - 生成基础关键词
   - 广度优先搜索
   - 建立知识基础

2. **第二轮迭代**
   - 基于反馈优化关键词
   - 深度优先搜索
   - 填补信息缺口

3. **第三轮迭代**
   - 精准优化关键词
   - 验证关键信息
   - 综合分析和整合

### 质量控制机制

- **相关性评估**: 关键词匹配度, 语义相似度
- **权威性评估**: 来源域名, 作者资质, 机构背景
- **时效性评估**: 发布日期, 更新频率, 信息新鲜度
- **完整性验证**: 报告结构, 证据支持, 结论逻辑

## 🚧 扩展功能

### 集成真实搜索引擎

```python
# 示例：集成Google Custom Search API
import requests

async def google_search(keywords, api_key, cse_id):
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "q": " ".join(keywords),
        "key": api_key,
        "cx": cse_id
    }
    response = requests.get(url, params=params)
    return response.json()
```

### 添加LLM增强

```python
# 示例：集成OpenAI GPT进行内容分析
import openai

async def analyze_with_gpt(content, research_topic):
    prompt = f"基于以下内容分析'{research_topic}'的关键发现：\n\n{content}"
    response = await openai.ChatCompletion.acreate(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content
```

### 数据库集成

```python
# 示例：将研究结果保存到SQLite
import sqlite3

def save_to_database(research_result):
    conn = sqlite3.connect("research.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS research_results (
            id INTEGER PRIMARY KEY,
            topic TEXT,
            iteration INTEGER,
            total_results INTEGER,
            high_quality_count INTEGER,
            report_json TEXT,
            created_at TIMESTAMP
        )
    """)
    # 插入数据...
```

## 📈 性能优化建议

1. **缓存搜索结果**: 避免重复搜索相同关键词
2. **并行处理**: 使用asyncio.gather并行处理多个Agent
3. **增量更新**: 只对新的或修改过的内容进行重新分析
4. **资源限制**: 设置每个阶段的最大处理数量

## 🐛 故障排除

### 常见问题

1. **"没有可总结的搜索结果"**
   - 检查关键词是否过于特异或错误
   - 增加关键词数量或范围
   - 调整质量判断阈值

2. **"内容总结失败"**
   - 确保输入数据格式正确
   - 检查字符串编码问题
   - 简化总结级别从"详细摘要"改为"要点列表"

3. **"报告验证失败"**
   - 手动检查_report_template结构
   - 验证是否有必要字段缺失
   - 增加调试日志输出

### 调试模式

```python
# 在research_assistant.py中添加
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 🤝 贡献指南

### 开发环境设置

```bash
# 建议使用Python 3.8+
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
# 安装开发依赖
pip install pytest pytest-asyncio
```

### 运行测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest test_keyword_agent.py

# 带详细输出
pytest -v
```

### 代码规范

- 遵循PEP 8编码规范
- 使用类型注解
- 添加函数和类的docstring
- 关键功能添加单元测试

## 📄 许可证

MIT License

## 📞 支持

- 报告问题：[GitHub Issues](链接)
- 功能请求：[GitHub Discussions](链接)
- 文档改进：[Pull Requests](链接)

## 🎨 演示案例

查看完整演示：

```bash
python example_usage.py
```

这将展示：
- 系统架构和Agent功能
- 多个研究主题示例
- 自定义工作流演示
- 输出报告示例

---

**深度研究助手** - 让复杂的研究工作变得简单智能
"""
深度研究助手使用示例

这个文件展示了如何使用深度研究助手系统进行自动化研究。
系统支持竞品分析、行业趋势、技术选型、政策解读等多种研究类型。
"""

import asyncio
import json
import sys
import os

# 将当前目录添加到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from research_assistant import ResearchWorkflow


async def example_basic_usage():
    """基本使用示例"""
    print("=" * 80)
    print("示例1：基本使用 - 竞品分析")
    print("=" * 80)

    workflow = ResearchWorkflow()

    research_topic = "Python数据分析工具竞品对比"
    initial_keywords = ["Pandas", "NumPy", "DataFrames", "数据处理"]

    try:
        result = await workflow.execute_research(
            research_topic=research_topic,
            initial_keywords=initial_keywords,
            max_iterations=2
        )

        # 显示研究摘要
        summary = workflow.display_research_summary(result)
        print(summary)

        # 导出报告
        formats = workflow.export_report_formats(result)
        if "markdown" in formats:
            os.makedirs("outputs", exist_ok=True)
            filename = "outputs/example_report_basic.md"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(formats["markdown"])
            print(f"\nMarkdown报告已保存到: {filename}")

        return result

    except Exception as e:
        print(f"示例执行失败: {e}")
        return None


async def example_multiple_topics():
    """多个研究主题示例"""
    print("\n" + "=" * 80)
    print("示例2：多个研究主题 - 行业趋势分析")
    print("=" * 80)

    research_topics = [
        "人工智能在医疗行业的应用趋势",
        "新能源汽车技术发展趋势",
        "远程办公软件市场分析"
    ]

    results = {}

    for topic in research_topics[:2]:  # 只测试前两个主题
        print(f"\n研究主题: {topic}")
        print("-" * 40)

        workflow = ResearchWorkflow()

        try:
            result = await workflow.execute_research(
                research_topic=topic,
                max_iterations=1  # 快速测试
            )

            results[topic] = result

            # 显示简要信息
            iteration_count = len(result.get("iterations", []))
            hq_total = sum(
                iter_data.get("high_quality_count", 0)
                for iter_data in result.get("iterations", [])
            )
            print(f"迭代轮次: {iteration_count}")
            print(f"高质量结果: {hq_total}个")
            print(f"状态: {result.get('status', '未知')}")

        except Exception as e:
            print(f"主题 '{topic}' 研究失败: {e}")
            results[topic] = {"error": str(e)}

    return results


async def example_custom_workflow():
    """自定义工作流示例"""
    print("\n" + "=" * 80)
    print("示例3：自定义工作流 - 政策解读")
    print("=" * 80)

    workflow = ResearchWorkflow()

    # 自定义研究主题和参数
    research_topic = "数据隐私保护政策解读"
    custom_context = {
        "research_topic": research_topic,
        "iteration": 1,
        "policy_focus": True,
        "jurisdiction": "中国"
    }

    # 手动执行各阶段
    print(f"研究主题: {research_topic}")
    print("执行步骤:")
    print("1. 生成关键词")
    print("2. 模拟搜索")
    print("3. 质量评估")
    print("4. 内容总结")
    print("5. 生成报告")

    try:
        # 1. 生成关键词
        from keyword_agent import KeywordGeneratorAgent
        keyword_agent = KeywordGeneratorAgent()
        keyword_result = await keyword_agent.execute(research_topic, custom_context)

        if keyword_result.success:
            keywords = keyword_result.data.get("keywords", [])
            print(f"✓ 生成 {len(keywords)} 个关键词")
        else:
            print("✗ 关键词生成失败")

        # 2. 模拟搜索 (在实际应用中，这里会调用真实搜索API)
        from research_assistant import ResearchWorkflow as RW
        temp_workflow = RW()
        search_results = await temp_workflow._simulate_search_process(
            keywords[:5], research_topic, 1
        )
        print(f"✓ 模拟搜索获得 {len(search_results)} 个结果")

        # 3. 质量评估
        from quality_agent import QualityJudgmentAgent
        quality_agent = QualityJudgmentAgent()
        quality_results = []

        for result in search_results[:3]:  # 评估前3个结果
            quality_result = await quality_agent.execute(result, custom_context)
            if quality_result.success:
                quality_results.append(quality_result.data)

        print(f"✓ 完成 {len(quality_results)} 个结果的质量评估")

        # 4. 内容总结
        from summarization_agent import SummarizationAgent
        summary_agent = SummarizationAgent()
        summary_result = await summary_agent.execute(search_results, custom_context)

        if summary_result.success:
            print("✓ 完成内容总结")

        # 5. 生成报告
        from report_agent import ReportGeneratorAgent
        report_agent = ReportGeneratorAgent()

        research_data = {
            "summaries": [search_results],
            "conclusions": ["基于政策分析的关键发现"],
            "sources": search_results[:3]
        }

        report_result = await report_agent.execute(research_data, custom_context)

        if report_result.success:
            report = report_result.data.get("report", {})
            title = report.get("metadata", {}).get("title", "政策研究报告")
            conclusions = len(report.get("key_conclusions", []))
            print(f"✓ 报告生成完成: {title}")
            print(f"  包含 {conclusions} 个关键结论")

            # 保存报告
            os.makedirs("outputs", exist_ok=True)
            filename = "outputs/example_policy_report.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(report_result.data, f, ensure_ascii=False, indent=2)
            print(f"  报告已保存到: {filename}")

    except Exception as e:
        print(f"自定义工作流执行失败: {e}")
        import traceback
        traceback.print_exc()

    return {"status": "完成"}


def demonstrate_agent_capabilities():
    """展示各个Agent的功能"""
    print("\n" + "=" * 80)
    print("Agent功能展示")
    print("=" * 80)

    capabilities = {
        "BaseAgent": {
            "功能": "所有Agent的基础类",
            "特点": ["抽象接口", "执行历史记录", "结果标准化"],
            "输入输出": "支持多种数据格式"
        },
        "KeywordGeneratorAgent": {
            "功能": "关键词生成",
            "特点": ["多轮迭代优化", "关键词分类", "搜索策略建议"],
            "适用场景": ["竞品分析", "趋势研究", "技术选型"]
        },
        "QualityJudgmentAgent": {
            "功能": "质量判断",
            "特点": ["相关性评估", "权威性评分", "时效性检查"],
            "适用场景": ["结果筛选", "质量评估", "可信度分析"]
        },
        "SummarizationAgent": {
            "功能": "内容总结",
            "特点": ["结构化总结", "知识图谱", "信息缺口识别"],
            "适用场景": ["信息浓缩", "快速理解", "知识映射"]
        },
        "ReportGeneratorAgent": {
            "功能": "报告生成",
            "特点": ["结构化报告", "来源引用", "置信度说明"],
            "适用场景": ["研究总结", "决策支持", "知识存档"]
        },
        "ResearchWorkflow": {
            "功能": "工作流管理",
            "特点": ["多轮迭代", "自动优化", "结果整合"],
            "适用场景": ["自动化研究", "深度分析", "系统集成"]
        }
    }

    for agent_name, info in capabilities.items():
        print(f"\n{agent_name}:")
        print(f"  功能: {info['功能']}")
        print(f"  特点: {', '.join(info['特点'])}")
        print(f"  适用场景: {', '.join(info['适用场景'])}")


async def run_all_examples():
    """运行所有示例"""
    print("\n" + "=" * 80)
    print("深度研究助手系统演示")
    print("=" * 80)
    print("本演示展示系统的核心功能和典型使用场景。")
    print("\n系统架构:")
    print("  1. 关键词生成 → 信息检索 → 质量评估 → 内容总结 → 报告生成")
    print("  2. 多轮迭代自动优化")
    print("  3. 完整的来源追溯和置信度说明")
    print("\n开始演示...")

    # 展示Agent功能
    demonstrate_agent_capabilities()

    # 运行示例
    print("\n" + "=" * 80)
    print("运行实际示例...")

    # 示例1：基本使用
    example1_result = await example_basic_usage()

    # 示例2：多个主题
    example2_results = await example_multiple_topics()

    # 示例3：自定义工作流
    example3_result = await example_custom_workflow()

    print("\n" + "=" * 80)
    print("演示完成!")
    print("=" * 80)

    # 输出总结
    print("\n演示总结:")
    print(f"  1. 基本使用示例: {'成功' if example1_result else '失败'}")
    print(f"  2. 多主题示例: {len(example2_results)} 个主题完成")
    print(f"  3. 自定义工作流示例: '完成'")

    print("\n输出文件:")
    if os.path.exists("outputs"):
        for file in os.listdir("outputs"):
            print(f"  - outputs/{file}")

    print("\n下一步:")
    print("  1. 修改 research_assistant.py 使用真实搜索API")
    print("  2. 扩展Agent功能（如集成LLM）")
    print("  3. 添加更多研究类型支持")
    print("  4. 优化报告模板和输出格式")

    return {
        "example1": bool(example1_result),
        "example2": len(example2_results),
        "example3": example3_result
    }


def quick_start():
    """快速开始指南"""
    guide = """
深度研究助手 - 快速开始指南
================================

1. 安装依赖
   pip install -r requirements.txt

2. 基本使用
   python research_assistant.py "您的研突主题"

3. 带关键词使用
   python research_assistant.py "Python数据分析工具"
   > 输入关键词: Pandas, NumPy, SciPy

4. 交互式使用
   python research_assistant.py
   > 输入研突主题: 新能源汽车市场趋势
   > 输入关键词: 电动车, 电池技术, 自动驾驶
   > 迭代轮次: 3

5. API使用
   ```
   from research_assistant import ResearchWorkflow
   import asyncio

   async def run_research():
       workflow = ResearchWorkflow()
       result = await workflow.execute_research(
           research_topic="人工智能在金融行业的应用",
           initial_keywords=["AI", "金融科技", "风险评估"],
           max_iterations=3
       )
       print(workflow.display_research_summary(result))

   asyncio.run(run_research())
   ```

6. 自定义Agent
   ```
   from keyword_agent import KeywordGeneratorAgent

   agent = KeywordGeneratorAgent()
   result = await agent.execute("云原生技术趋势")
   print(result.data.get('keywords', []))
   ```

7. 扩展功能
   - 替换模拟搜索为真实搜索引擎
   - 集成大型语言模型（LLM）
   - 添加数据库存储
   - 支持更多输出格式（PDF, HTML, PPT）

系统特点:
- 全自动工作流: 关键词生成 → 搜索 → 分析 → 报告
- 多轮迭代优化: 自动调整关键词，提高结果质量
- 完整追溯: 每条结论都有来源引用
- 质量控制: 相关性、权威性、时效性评估
- 可扩展架构: 方便添加新的Agent和功能

支持的研究类型:
1. 竞品分析: 比较不同产品的功能、性能、优劣势
2. 行业趋势: 分析行业发展方向和未来预测
3. 技术选型: 评估不同技术方案的适用性和成本
4. 政策解读: 解读政策法规的影响和合规要求
5. 市场分析: 分析市场规模、竞争格局、用户需求
    """
    return guide


if __name__ == "__main__":
    # 设置日志
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 运行演示
    asyncio.run(run_all_examples())

    # 显示快速开始指南
    print("\n" + "=" * 80)
    print("快速开始指南")
    print("=" * 80)
    print(quick_start())

    # 显示文件夹结构
    print("\n" + "=" * 80)
    print("项目文件结构")
    print("=" * 80)
    print("研究助手项目包含以下文件:")
    print("""
  D:\\test\\
  ├── base_agent.py         # 基础Agent类和数据结构
  ├── keyword_agent.py      # 关键词生成Agent
  ├── quality_agent.py      # 质量判断Agent
  ├── summarization_agent.py # 内容总结Agent
  ├── report_agent.py       # 报告生成Agent
  ├── research_assistant.py # 主应用和整合工作流
  ├── example_usage.py      # 使用示例（本文件）
  ├── requirements.txt      # 项目依赖
  └── outputs/              # 输出目录（自动创建）
  """)

    print("\n要立即试用，请运行:")
    print("  python research_assistant.py \"Python数据分析工具竞品对比\"")
"""
深度研究助手主应用 - 整合所有Agent，提供完整研究工作流
"""
import asyncio
import json
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
import sys
import os

# 导入各个Agent
from base_agent import BaseAgent, AgentResult
from keyword_agent import KeywordGeneratorAgent
from quality_agent import QualityJudgmentAgent
from summarization_agent import SummarizationAgent
from report_agent import ReportGeneratorAgent

logger = logging.getLogger(__name__)


class ResearchWorkflow:
    """研究工作流管理器"""

    def __init__(self):
        """初始化研究工作流"""
        self.agents = {}
        self.initialize_agents()
        self.research_history = []
        self.current_iteration = 1
        self.max_iterations = 3  # 最大迭代轮次

    def initialize_agents(self):
        """初始化所有Agent"""
        logger.info("初始化研究助手Agent...")
        self.agents = {
            "keyword_generator": KeywordGeneratorAgent(),
            "quality_judgment": QualityJudgmentAgent(),
            "summarization": SummarizationAgent(),
            "report_generator": ReportGeneratorAgent()
        }
        logger.info(f"成功初始化 {len(self.agents)} 个Agent")

    async def execute_research(self, research_topic: str,
                              initial_keywords: Optional[List[str]] = None,
                              max_iterations: Optional[int] = None) -> Dict[str, Any]:
        """
        执行完整的研究工作流

        Args:
            research_topic: 研究主题
            initial_keywords: 初始关键词（可选）
            max_iterations: 最大迭代轮次（可选）

        Returns:
            包含所有研究成果的字典
        """
        logger.info(f"开始研究工作流，主题: {research_topic}")

        if max_iterations:
            self.max_iterations = max_iterations

        research_result = {
            "research_topic": research_topic,
            "start_time": datetime.now().isoformat(),
            "iterations": [],
            "final_report": None,
            "all_keywords": [],
            "search_results": [],
            "summaries": [],
            "status": "进行中"
        }

        context = {
            "research_topic": research_topic,
            "iteration": self.current_iteration,
            "research_history": self.research_history
        }

        try:
            # 执行迭代式研究
            for iteration in range(1, self.max_iterations + 1):
                logger.info(f"开始第 {iteration} 轮研究迭代")

                iteration_result = await self.execute_iteration(
                    research_topic=research_topic,
                    iteration=iteration,
                    context=context.copy(),
                    iteration_keywords=initial_keywords if iteration == 1 else None
                )

                research_result["iterations"].append(iteration_result)

                # 更新上下文
                context.update({
                    "iteration": iteration,
                    "previous_keywords": iteration_result.get("generated_keywords", {}).get("keywords", []),
                    "previous_results": iteration_result.get("search_results", []),
                    "previous_summary": iteration_result.get("content_summary", {}),
                    "research_history": self.research_history
                })

                # 检查是否已达到满意的结果
                if self._should_stop_iteration(iteration_result, iteration):
                    logger.info(f"在第 {iteration} 轮迭代后达到满意结果")
                    break

            # 生成最终报告
            final_report = await self.generate_final_report(research_result)
            research_result["final_report"] = final_report
            research_result["status"] = "完成"

        except Exception as e:
            logger.error(f"研究工作流执行失败: {e}")
            research_result["status"] = f"失败: {str(e)}"

        research_result["end_time"] = datetime.now().isoformat()
        research_result["total_iterations"] = len(research_result["iterations"])

        # 保存研究历史
        self._save_research_history(research_topic, research_result)

        return research_result

    async def execute_iteration(self, research_topic: str,
                               iteration: int,
                               context: Dict[str, Any],
                               iteration_keywords: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        执行单轮研究迭代

        Args:
            research_topic: 研究主题
            iteration: 迭代轮次
            context: 执行上下文
            iteration_keywords: 迭代关键词（可选）

        Returns:
            迭代结果
        """
        iteration_result = {
            "iteration": iteration,
            "start_time": datetime.now().isoformat(),
            "tasks": []
        }

        try:
            # 1. 生成或优化关键词
            keywords_task = await self._execute_keyword_generation(
                research_topic, iteration, context, iteration_keywords
            )
            iteration_result["keywords_task"] = keywords_task
            iteration_result["tasks"].append("关键词生成")

            # 2. (模拟)搜索过程 - 在实际应用中这里会调用搜索API
            search_results = await self._simulate_search_process(
                keywords_task.get("data", {}).get("keywords", []),
                research_topic,
                iteration
            )
            iteration_result["search_results"] = search_results
            iteration_result["search_count"] = len(search_results)
            iteration_result["tasks"].append("信息检索")

            # 3. 搜索结果质量判断
            if search_results:
                quality_task = await self._execute_quality_judgment(
                    search_results, research_topic, iteration
                )
                iteration_result["quality_task"] = quality_task
                iteration_result["tasks"].append("质量评估")

                # 筛选高质量结果
                high_quality_results = self._filter_high_quality_results(
                    search_results, quality_task
                )
                iteration_result["high_quality_results"] = high_quality_results
                iteration_result["high_quality_count"] = len(high_quality_results)

                # 4. 内容总结
                if high_quality_results:
                    summary_task = await self._execute_content_summarization(
                        high_quality_results, research_topic, iteration
                    )
                    iteration_result["content_summary"] = summary_task
                    iteration_result["tasks"].append("内容总结")

            # 5. 分析迭代结果
            iteration_analysis = self._analyze_iteration_results(iteration_result)
            iteration_result["analysis"] = iteration_analysis

        except Exception as e:
            logger.error(f"第 {iteration} 轮迭代执行失败: {e}")
            iteration_result["error"] = str(e)
            iteration_result["status"] = "失败"

        iteration_result["end_time"] = datetime.now().isoformat()
        iteration_result["status"] = iteration_result.get("status", "成功")

        # 记录到历史
        self.research_history.append({
            "iteration": iteration,
            "result": iteration_result,
            "timestamp": datetime.now().isoformat()
        })

        return iteration_result

    async def _execute_keyword_generation(self, research_topic: str,
                                        iteration: int,
                                        context: Dict[str, Any],
                                        custom_keywords: Optional[List[str]] = None) -> Dict[str, Any]:
        """执行关键词生成任务"""
        agent = self.agents["keyword_generator"]

        input_data = research_topic
        if custom_keywords:
            input_data = {
                "research_topic": research_topic,
                "custom_keywords": custom_keywords
            }

        execution_context = {
            "research_topic": research_topic,
            "iteration": iteration,
            "previous_keywords": context.get("previous_keywords", []),
            "previous_results": context.get("previous_results", [])
        }

        result = await agent.execute(input_data, execution_context)

        if result.success:
            logger.info(f"第 {iteration} 轮迭代生成 {len(result.data.get('keywords', []))} 个关键词")
            return {
                "status": "成功",
                "generated_keywords": result.data,
                "metadata": result.metadata
            }
        else:
            logger.warning(f"关键词生成失败: {result.error}")
            # 返回默认关键词
            default_keywords = {
                "research_topic": research_topic,
                "keywords": [{"keyword": research_topic, "weight": 1.0, "category": "核心概念"}]
            }
            return {
                "status": "失败，使用默认关键词",
                "generated_keywords": default_keywords,
                "error": result.error
            }

    async def _simulate_search_process(self, keywords: List[Dict[str, Any]],
                                      research_topic: str,
                                      iteration: int) -> List[Dict[str, Any]]:
        """模拟搜索过程（实际应用中应调用真实搜索API）"""
        # 这里模拟一些搜索结果
        # 在实际应用中，这里应该调用Google Search API、学术数据库API等

        logger.info(f"模拟搜索过程，使用 {len(keywords)} 个关键词")

        # 提取关键词文本
        keyword_texts = []
        for kw in keywords[:10]:  # 限制前10个关键词
            if isinstance(kw, dict):
                keyword_texts.append(kw.get("keyword", str(kw)))
            else:
                keyword_texts.append(str(kw))

        # 生成模拟搜索结果
        simulated_results = []
        base_topics = [
            "现状与背景", "技术特点", "市场竞争", "发展趋势",
            "应用场景", "用户反馈", "政策影响", "成本分析"
        ]

        for i, keyword in enumerate(keyword_texts[:8]):
            result = {
                "id": f"result_{i:03d}",
                "title": f"{keyword}研究分析报告",
                "content": f"本报告针对{keyword}进行了深入研究。分析了当前市场现状、技术特点、发展趋势等关键信息。研究表明，该领域正在快速发展，技术创新和市场拓展是主要驱动力。",
                "summary": f"关于{keyword}的详细分析，涵盖多个关键维度",
                "url": f"https://example.com/research/{i}",
                "source": "模拟研究机构" if i % 2 == 0 else "技术分析平台",
                "date": "2023-12-01" if i % 3 == 0 else "2024-01-15",
                "relevance_score": 0.7 + (i * 0.05),  # 模拟相关性分数
                "quality_score": 0.6 + (i * 0.04),
                "keywords_used": [keyword]
            }

            # 添加特定主题的内容
            topic_index = i % len(base_topics)
            topic = base_topics[topic_index]

            result["content"] += f" 在{topic}方面，展示了显著的特征和发展潜力。"
            simulated_results.append(result)

        # 添加一些高质量结果
        high_quality_results = [
            {
                "id": "result_hq_001",
                "title": f"{research_topic}综合研究报告",
                "content": f"本报告全面分析了{research_topic}的关键问题。通过大量数据收集和分析，揭示了行业发展的核心趋势和技术创新的重要方向。报告提供了详细的对比数据和前瞻性预测。",
                "summary": "最全面的研究报告，覆盖所有关键方面",
                "url": "https://example.com/comprehensive-report",
                "source": "权威研究机构",
                "date": "2024-02-01",
                "relevance_score": 0.9,
                "quality_score": 0.85,
                "keywords_used": keyword_texts[:3]
            },
            {
                "id": "result_hq_002",
                "title": f"{research_topic}技术白皮书",
                "content": f"这份技术白皮书深入探讨了{research_topic}的技术实现方案和最佳实践。提供了详细的技术架构、性能评估和实施建议。",
                "summary": "关键技术细节和实施方案",
                "url": "https://example.com/whitepaper",
                "source": "技术标准组织",
                "date": "2023-11-15",
                "relevance_score": 0.85,
                "quality_score": 0.8,
                "keywords_used": keyword_texts[2:5]
            }
        ]

        simulated_results.extend(high_quality_results)

        logger.info(f"生成 {len(simulated_results)} 个模拟搜索结果")
        return simulated_results

    async def _execute_quality_judgment(self, search_results: List[Dict[str, Any]],
                                       research_topic: str,
                                       iteration: int) -> Dict[str, Any]:
        """执行搜索结果质量判断"""
        agent = self.agents["quality_judgment"]

        # 批量判断或样本判断（这里使用样本判断）
        sample_results = search_results[:5]  # 只判断前5个结果以减少计算量

        quality_results = []
        for result in sample_results:
            context = {
                "research_topic": research_topic,
                "iteration": iteration,
                "batch_position": len(quality_results) + 1
            }

            result_quality = await agent.execute(result, context)
            if result_quality.success:
                quality_results.append(result_quality.data)

        return {
            "evaluated_count": len(quality_results),
            "quality_assessments": quality_results,
            "average_relevance": sum(r.get("judgments", {}).get("relevance_score", 0)
                                   for r in quality_results) / max(1, len(quality_results)),
            "status": "成功" if quality_results else "失败"
        }

    def _filter_high_quality_results(self, search_results: List[Dict[str, Any]],
                                    quality_task: Dict[str, Any]) -> List[Dict[str, Any]]:
        """筛选高质量结果"""
        if not quality_task.get("quality_assessments"):
            return search_results[:3]  # 返回前3个作为默认

        # 获取高质量结果ID
        high_quality_ids = []
        for assessment in quality_task["quality_assessments"]:
            if assessment.get("judgments", {}).get("overall_score", 0) >= 0.6:
                high_quality_ids.append(assessment.get("result_id"))

        # 筛选结果
        filtered_results = []
        for result in search_results:
            if result.get("id") in high_quality_ids:
                filtered_results.append(result)

        # 如果没有筛选到结果，返回质量分数较高的前几个
        if not filtered_results and search_results:
            if quality_task.get("quality_assessments"):
                # 按质量排序
                sorted_assessments = sorted(quality_task["quality_assessments"],
                                           key=lambda x: x.get("judgments", {}).get("overall_score", 0),
                                           reverse=True)
                top_ids = [a.get("result_id") for a in sorted_assessments[:3]]
                filtered_results = [r for r in search_results if r.get("id") in top_ids]
            else:
                filtered_results = search_results[:3]

        return filtered_results

    async def _execute_content_summarization(self, high_quality_results: List[Dict[str, Any]],
                                           research_topic: str,
                                           iteration: int) -> Dict[str, Any]:
        """执行内容总结任务"""
        agent = self.agents["summarization"]

        context = {
            "research_topic": research_topic,
            "iteration": iteration,
            "summary_level": "详细摘要" if iteration == 1 else "要点列表",
            "keywords": [{"keyword": research_topic, "weight": 1.0}]
        }

        result = await agent.execute(high_quality_results, context)

        if result.success:
            return {
                "status": "成功",
                "summary_data": result.data,
                "metadata": result.metadata
            }
        else:
            logger.warning(f"内容总结失败: {result.error}")
            # 生成简单总结
            simple_summary = {
                "research_topic": research_topic,
                "summary": f"基于{len(high_quality_results)}个高质量搜索结果的分析。",
                "key_points": [
                    f"收集到{len(high_quality_results)}个相关研究资料",
                    "主要信息覆盖了关键技术和发展趋势",
                    "需要进一步综合分析"
                ]
            }
            return {
                "status": "失败，使用简单总结",
                "summary_data": simple_summary,
                "error": result.error
            }

    def _analyze_iteration_results(self, iteration_result: Dict[str, Any]) -> Dict[str, Any]:
        """分析迭代结果"""
        high_quality_count = iteration_result.get("high_quality_count", 0)
        search_count = iteration_result.get("search_count", 0)

        analysis = {
            "high_quality_ratio": high_quality_count / search_count if search_count > 0 else 0,
            "progress_assessment": self._assess_progress(iteration_result),
            "keyword_effectiveness": self._assess_keyword_effectiveness(iteration_result),
            "next_iteration_suggestions": self._generate_next_iteration_suggestions(iteration_result),
            "knowledge_coverage": self._assess_knowledge_coverage(iteration_result)
        }

        return analysis

    def _assess_progress(self, iteration_result: Dict[str, Any]) -> str:
        """评估迭代进展"""
        iteration_num = iteration_result.get("iteration", 1)
        high_quality_count = iteration_result.get("high_quality_count", 0)

        if iteration_num == 1:
            if high_quality_count >= 3:
                return "良好进展，发现大量高质量信息"
            elif high_quality_count >= 1:
                return "正常进展，找到部分有用信息"
            else:
                return "进展有限，需要调整搜索策略"

        elif iteration_num >= 2:
            if high_quality_count >= 5:
                return "显著进展，信息丰富"
            elif high_quality_count >= 2:
                return "稳步进展，信息逐渐完善"
            else:
                return "进展缓慢，需要重新评估研究策略"

        return "进展评估中"

    def _assess_keyword_effectiveness(self, iteration_result: Dict[str, Any]) -> Dict[str, Any]:
        """评估关键词效果"""
        keywords_task = iteration_result.get("keywords_task", {})
        keyword_data = keywords_task.get("generated_keywords", {})
        keywords = keyword_data.get("keywords", [])

        effectiveness = {
            "total_keywords": len(keywords),
            "high_priority_count": len([k for k in keywords if isinstance(k, dict) and k.get("priority", 0) > 0.7]),
            "category_distribution": {},
            "keyword_types": set()
        }

        # 统计分类分布
        for kw in keywords:
            if isinstance(kw, dict):
                category = kw.get("category", "未知")
                effectiveness["category_distribution"][category] = \
                    effectiveness["category_distribution"].get(category, 0) + 1
                effectiveness["keyword_types"].add(category)

        return effectiveness

    def _generate_next_iteration_suggestions(self, iteration_result: Dict[str, Any]) -> List[str]:
        """生成下一轮迭代建议"""
        suggestions = []
        iteration_num = iteration_result.get("iteration", 1)

        if iteration_num == 1:
            suggestions.append("扩大搜索范围，尝试更多关键词组合")
            suggestions.append("增加特定领域的关键词，如技术细节、案例研究")

        if iteration_result.get("high_quality_count", 0) < 3:
            suggestions.append("调整关键词，提高结果相关性")
            suggestions.append("尝试不同的搜索引擎或数据库")

        if iteration_num >= 2:
            suggestions.append("深入分析已有高质量信息")
            suggestions.append("补充缺少的数据，如市场数字、用户反馈")

        return suggestions

    def _assess_knowledge_coverage(self, iteration_result: Dict[str, Any]) -> Dict[str, Any]:
        """评估知识覆盖度"""
        coverage = {
            "technical_coverage": "部分覆盖",
            "market_coverage": "基本覆盖",
            "case_coverage": "缺乏案例",
            "policy_coverage": "无政策信息",
            "overall_coverage": "中等"
        }

        search_results = iteration_result.get("search_results", [])
        summary_data = iteration_result.get("content_summary", {}).get("summary_data", {})

        # 分析内容中的关键词类型
        all_text = " ".join(str(r.get("title", "")) + " " + str(r.get("summary", ""))
                           for r in search_results[:5])

        if "技术" in all_text or "架构" in all_text or "算法" in all_text:
            coverage["technical_coverage"] = "良好"

        if "市场" in all_text or "规模" in all_text or "竞争" in all_text:
            coverage["market_coverage"] = "充分"

        if "案例" in all_text or "实践" in all_text or "实施" in all_text:
            coverage["case_coverage"] = "部分案例"

        if "政策" in all_text or "法规" in all_text or "标准" in all_text:
            coverage["policy_coverage"] = "有政策信息"

        # 更新整体覆盖度
        positive_count = sum(1 for v in coverage.values() if v in ["良好", "充分", "部分案例", "有政策信息"])
        if positive_count >= 4:
            coverage["overall_coverage"] = "全面"
        elif positive_count >= 2:
            coverage["overall_coverage"] = "中等"
        else:
            coverage["overall_coverage"] = "有限"

        return coverage

    def _should_stop_iteration(self, iteration_result: Dict[str, Any], iteration: int) -> bool:
        """判断是否应该停止迭代"""
        # 如果已经达到最大迭代轮次
        if iteration >= self.max_iterations:
            return True

        # 如果有足够的高质量结果
        high_quality_count = iteration_result.get("high_quality_count", 0)
        if high_quality_count >= 5:
            logger.info(f"高质量结果充足 ({high_quality_count}个)，准备停止迭代")
            return True

        # 如果连续两轮进展很小
        if iteration >= 2:
            # 检查前一轮的结果
            if len(self.research_history) >= 2:
                prev_result = self.research_history[-2]["result"]
                current_hq = iteration_result.get("high_quality_count", 0)
                prev_hq = prev_result.get("high_quality_count", 0)

                if current_hq <= prev_hq + 1:  # 进展很小
                    logger.info("连续两轮进展有限，准备停止迭代")
                    return True

        return False

    async def generate_final_report(self, research_result: Dict[str, Any]) -> Dict[str, Any]:
        """生成最终研究报告"""
        agent = self.agents["report_generator"]

        # 提取所有研究数据
        all_summaries = []
        all_keywords = []
        all_results = []

        for iteration in research_result["iterations"]:
            if "content_summary" in iteration:
                summary_data = iteration["content_summary"].get("summary_data", {})
                if summary_data:
                    all_summaries.append(summary_data)

            if "keywords_task" in iteration:
                keyword_data = iteration["keywords_task"].get("generated_keywords", {})
                if keyword_data:
                    all_keywords.append(keyword_data)

            if "search_results" in iteration:
                all_results.extend(iteration["search_results"])

        # 准备研究数据
        research_data = {
            "research_topic": research_result["research_topic"],
            "summaries": all_summaries,
            "search_results": all_results,
            "iteration_data": research_result["iterations"],
            "total_iterations": len(research_result["iterations"])
        }

        context = {
            "research_topic": research_result["research_topic"],
            "iteration": len(research_result["iterations"]),
            "research_history": self.research_history,
            "keywords": all_keywords
        }

        logger.info("生成最终研究报告...")
        result = await agent.execute(research_data, context)

        if result.success:
            logger.info("最终报告生成成功")
            return result.data
        else:
            logger.error(f"最终报告生成失败: {result.error}")
            return {
                "error": result.error,
                "status": "报告生成失败",
                "fallback_content": {
                    "summary": f"关于{research_result['research_topic']}的研究分析报告",
                    "conclusions": ["研究过程遇到技术问题"],
                    "sources": []
                }
            }

    def _save_research_history(self, research_topic: str, research_result: Dict[str, Any]):
        """保存研究历史到文件"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"research_history_{research_topic[:20]}_{timestamp}.json"

            # 创建outputs目录
            output_dir = "outputs"
            os.makedirs(output_dir, exist_ok=True)
            filepath = os.path.join(output_dir, filename)

            # 准备保存数据
            data_to_save = {
                "research_topic": research_topic,
                "timestamp": timestamp,
                "result": research_result,
                "agents_used": list(self.agents.keys())
            }

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, ensure_ascii=False, indent=2)

            logger.info(f"研究历史已保存到: {filepath}")
            research_result["saved_filename"] = filepath

        except Exception as e:
            logger.error(f"保存研究历史失败: {e}")

    def display_research_summary(self, research_result: Dict[str, Any]) -> str:
        """显示研究摘要"""
        summary = []
        summary.append("=" * 80)
        summary.append("深度研究助手 - 研究摘要")
        summary.append("=" * 80)
        summary.append(f"研究主题: {research_result.get('research_topic', '未知')}")
        summary.append(f"研究状态: {research_result.get('status', '未知')}")
        summary.append(f"迭代轮次: {research_result.get('total_iterations', 0)}")

        if research_result.get("iterations"):
            total_results = 0
            total_hq_results = 0

            for i, iteration in enumerate(research_result["iterations"], 1):
                results = iteration.get("search_count", 0)
                hq_results = iteration.get("high_quality_count", 0)
                total_results += results
                total_hq_results += hq_results

                summary.append(f"\n第 {i} 轮迭代:")
                summary.append(f"  - 搜索结果: {results} 个")
                summary.append(f"  - 高质量结果: {hq_results} 个")
                summary.append(f"  - 状态: {iteration.get('status', '未知')}")

            summary.append(f"\n总计:")
            summary.append(f"  - 搜索结果总数: {total_results} 个")
            summary.append(f"  - 高质量结果总数: {total_hq_results} 个")

        if research_result.get("final_report"):
            report = research_result["final_report"]
            if isinstance(report, dict):
                if "report" in report:
                    summary.append(f"\n最终报告已生成，包含 {len(report.get('report', {}).get('key_conclusions', []))} 个关键结论")
                elif "metadata" in report:
                    summary.append(f"\n最终报告标题: {report.get('metadata', {}).get('title', '未知')}")

        if research_result.get("saved_filename"):
            summary.append(f"\n详细结果已保存到: {research_result['saved_filename']}")

        summary.append("\n" + "=" * 80)
        return "\n".join(summary)

    def export_report_formats(self, research_result: Dict[str, Any]) -> Dict[str, Any]:
        """导出不同格式的报告"""
        formats = {}

        # JSON格式
        if research_result.get("final_report"):
            formats["json"] = json.dumps(research_result, ensure_ascii=False, indent=2)

        # 文本摘要格式
        formatted_text = self.display_research_summary(research_result)
        formats["text_summary"] = formatted_text

        # 如果最终报告存在，提取结构化内容
        if research_result.get("final_report"):
            report_data = research_result["final_report"]
            if isinstance(report_data, dict) and "report" in report_data:
                report = report_data["report"]

                # Markdown格式
                markdown_content = self._format_report_as_markdown(report)
                formats["markdown"] = markdown_content

                # 简单要点格式
                bullet_points = self._format_report_as_bullets(report)
                formats["bullets"] = bullet_points

        return formats

    def _format_report_as_markdown(self, report: Dict[str, Any]) -> str:
        """将报告格式化为Markdown"""
        md_lines = []

        # 标题
        metadata = report.get("metadata", {})
        md_lines.append(f"# {metadata.get('title', '研究报告')}\n")

        # 摘要
        summary = report.get("summary", {})
        if summary:
            md_lines.append("## 摘要")
            md_lines.append(summary.get("executive_summary", ""))

        # 结构化内容
        structured = report.get("structured_content", {})
        for section, content in structured.items():
            md_lines.append(f"\n## {section}")
            if isinstance(content, dict) and "content" in content:
                md_lines.append(content["content"])

                # 子标题
                for subsection in content.get("subsections", []):
                    md_lines.append(f"\n### {subsection}")

        # 关键结论
        conclusions = report.get("key_conclusions", [])
        if conclusions:
            md_lines.append("\n## 关键结论")
            for i, conc in enumerate(conclusions, 1):
                if isinstance(conc, dict):
                    statement = conc.get("statement", "")
                    md_lines.append(f"{i}. {statement}")

        # 来源
        sources = report.get("sources", {})
        if sources:
            md_lines.append("\n## 参考文献")
            primary_sources = sources.get("primary_sources", [])
            for source in primary_sources[:10]:
                if isinstance(source, dict):
                    title = source.get("title", "")
                    author = source.get("author", "")
                    year = source.get("year", "")
                    if title:
                        md_lines.append(f"- {title} ({author}, {year})")

        return "\n".join(md_lines)

    def _format_report_as_bullets(self, report: Dict[str, Any]) -> str:
        """将报告格式化为要点列表"""
        bullets = []

        # 标题
        metadata = report.get("metadata", {})
        bullets.append(f"报告标题：{metadata.get('title', '研究报告')}")

        # 关键结论
        conclusions = report.get("key_conclusions", [])
        if conclusions:
            bullets.append("\n关键结论：")
            for i, conc in enumerate(conclusions[:5], 1):
                if isinstance(conc, dict):
                    statement = conc.get("statement", "")
                    bullets.append(f"  {i}. {statement}")

        # 来源数量
        sources = report.get("sources", {})
        source_count = 0
        if sources:
            primary = sources.get("primary_sources", [])
            secondary = sources.get("secondary_sources", [])
            source_count = len(primary) + len(secondary)

        bullets.append(f"\n参考来源：{source_count} 个")

        # 遗留问题
        questions = report.get("open_questions", [])
        if questions:
            bullets.append(f"\n遗留问题：{len(questions)} 个")

        return "\n".join(bullets)


async def main():
    """主程序入口"""
    print("=" * 80)
    print("深度研究助手 - 自动研究工具")
    print("=" * 80)

    # 获取研究主题
    if len(sys.argv) > 1:
        research_topic = " ".join(sys.argv[1:])
    else:
        print("请输入研究主题（例如：Python数据分析工具竞品对比）：")
        research_topic = input("> ").strip()

    if not research_topic:
        print("错误：研究主题不能为空")
        return

    # 可选参数
    print("\n可选：输入初始关键词（用逗号分隔，直接回车跳过）：")
    initial_keywords_input = input("> ").strip()
    initial_keywords = [kw.strip() for kw in initial_keywords_input.split(",") if kw.strip()] if initial_keywords_input else None

    print("\n可选：输入最大迭代轮次（默认3，直接回车使用默认）：")
    max_iterations_input = input("> ").strip()
    max_iterations = int(max_iterations_input) if max_iterations_input.isdigit() else None

    print(f"\n开始研究: {research_topic}")
    if initial_keywords:
        print(f"使用初始关键词: {', '.join(initial_keywords)}")
    print("-" * 80)

    # 创建工作流并执行研究
    workflow = ResearchWorkflow()

    try:
        research_result = await workflow.execute_research(
            research_topic=research_topic,
            initial_keywords=initial_keywords,
            max_iterations=max_iterations
        )

        # 显示摘要
        summary = workflow.display_research_summary(research_result)
        print(summary)

        # 询问是否导出报告
        print("\n" + "-" * 80)
        print("是否导出详细报告？ (y/n):")
        export_choice = input("> ").lower()

        if export_choice == 'y':
            formats = workflow.export_report_formats(research_result)

            if "markdown" in formats:
                # 保存Markdown文件
                import time
                timestamp = int(time.time())
                md_filename = f"outputs/report_{timestamp}.md"

                os.makedirs("outputs", exist_ok=True)
                with open(md_filename, 'w', encoding='utf-8') as f:
                    f.write(formats["markdown"])

                print(f"\nMarkdown报告已保存到: {md_filename}")

            # 显示文本摘要
            print("\n文本摘要:")
            print("-" * 40)
            if "text_summary" in formats:
                print(formats["text_summary"])

    except KeyboardInterrupt:
        print("\n\n研究被用户中断")
    except Exception as e:
        print(f"\n研究过程中发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 运行主程序
    asyncio.run(main())
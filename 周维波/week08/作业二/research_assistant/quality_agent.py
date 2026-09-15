"""
质量判断Agent - 判断搜索结果相关性和报告质量
"""
from typing import Dict, Any, List, Tuple
import logging
from .base_agent import BaseAgent, AgentResult

logger = logging.getLogger(__name__)


class QualityJudgmentAgent(BaseAgent):
    """质量判断Agent"""

    def __init__(self):
        super().__init__(
            name="quality_judgment",
            description="判断搜索结果相关性、内容质量和报告质量"
        )
        self.relevance_factors = [
            "主题匹配度", "时效性", "权威性", "深度", "证据支持"
        ]
        self.quality_factors = [
            "结构完整性", "逻辑一致性", "语言质量", "数据准确性", "引用完整性"
        ]

    async def execute(self, input_data: Any, context: Dict[str, Any] = None) -> AgentResult:
        """
        执行质量判断

        Args:
            input_data: 需要判断的内容（搜索结果、研究报告等）
            context: 执行上下文（研究主题、历史结果等）

        Returns:
            AgentResult: 包含质量评估结果
        """
        try:
            # 解析输入类型
            content_type, content = self._parse_input(input_data)
            logger.info(f"质量判断Agent开始执行，内容类型: {content_type}")

            # 获取上下文
            research_topic = context.get("research_topic", "未知主题") if context else "未知主题"
            iteration = context.get("iteration", 1) if context else 1

            # 根据不同内容类型进行评估
            if content_type == "search_result":
                result = self._judge_search_result(content, research_topic, iteration)
            elif content_type == "intermediate_content":
                result = self._judge_intermediate_content(content, research_topic, iteration)
            elif content_type == "final_report":
                result = self._judge_final_report(content, research_topic, iteration)
            else:
                result = self._judge_unknown_content(content, research_topic, iteration)

            agent_result = AgentResult(
                success=True,
                data=result,
                metadata={
                    "content_type": content_type,
                    "research_topic": research_topic,
                    "iteration": iteration,
                    "judgment_method": "rule_based",  # 未来可改为"llm_based"
                    "timestamp": self._get_timestamp()
                }
            )

            self.log_execution(input_data, agent_result, context)
            return agent_result

        except Exception as e:
            logger.error(f"质量判断Agent执行失败: {e}")
            return AgentResult(
                success=False,
                data=None,
                error=str(e),
                metadata={
                    "input_type": type(input_data).__name__,
                    "error_type": type(e).__name__
                }
            )

    def _parse_input(self, input_data: Any) -> Tuple[str, Any]:
        """解析输入类型和内容"""
        if isinstance(input_data, dict):
            # 检查是否为搜索结果
            if any(field in input_data for field in ["url", "title", "content", "summary"]):
                return "search_result", input_data
            # 检查是否为研究报告
            elif any(field in input_data for field in ["report", "document", "analysis", "conclusions"]):
                return "final_report", input_data
            # 检查是否为中间内容
            elif any(field in input_data for field in ["text", "content", "draft", "intermediate"]):
                return "intermediate_content", input_data
            else:
                return "unknown", input_data
        elif isinstance(input_data, str):
            if input_data.startswith("http://") or input_data.startswith("https://"):
                return "url", input_data
            else:
                return "text", input_data
        elif isinstance(input_data, list):
            # 如果是列表，假设是搜索结果列表
            return "search_results_list", input_data
        else:
            return "unknown", input_data

    def _judge_search_result(self, result: Dict[str, Any],
                            research_topic: str,
                            iteration: int) -> Dict[str, Any]:
        """判断单个搜索结果的质量"""
        judgments = {}

        # 基本字段检查
        judgments["has_title"] = bool(result.get("title"))
        judgments["has_url"] = bool(result.get("url"))
        judgments["has_content"] = bool(result.get("content") or result.get("summary"))

        # 相关性评估
        relevance_score, relevance_details = self._assess_relevance(result, research_topic)
        judgments["relevance_score"] = relevance_score
        judgments["relevance_details"] = relevance_details

        # 质量评估
        quality_score, quality_details = self._assess_search_quality(result)
        judgments["quality_score"] = quality_score
        judgments["quality_details"] = quality_details

        # 权威性评估
        authority_score, authority_details = self._assess_authority(result)
        judgments["authority_score"] = authority_score
        judgments["authority_details"] = authority_details

        # 时效性评估
        recency_score, recency_details = self._assess_recency(result)
        judgments["recency_score"] = recency_score
        judgments["recency_details"] = recency_details

        # 综合评分（加权平均）
        weights = {
            "relevance": 0.4,
            "quality": 0.3,
            "authority": 0.2,
            "recency": 0.1
        }

        overall_score = (
            relevance_score * weights["relevance"] +
            quality_score * weights["quality"] +
            authority_score * weights["authority"] +
            recency_score * weights["recency"]
        )

        judgments["overall_score"] = overall_score
        judgments["recommendation"] = self._get_recommendation(overall_score)
        judgments["confidence"] = self._calculate_confidence(judgments)

        # 添加处理建议
        judgments["suggested_actions"] = self._get_suggested_actions(judgments)

        return {
            "judgment_type": "search_result",
            "result_id": result.get("id", "unknown"),
            "url": result.get("url"),
            "title": result.get("title", "无标题"),
            "judgments": judgments,
            "should_keep": overall_score >= 0.5,  # 阈值可调整
            "priority": self._calculate_priority(judgments, iteration)
        }

    def _assess_relevance(self, result: Dict[str, Any], research_topic: str) -> Tuple[float, Dict[str, Any]]:
        """评估相关性"""
        # 提取文本进行分析
        title = result.get("title", "").lower()
        content = result.get("content", "").lower()
        summary = result.get("summary", "").lower()
        topics = research_topic.lower()

        # 关键词匹配
        topic_words = set(topics.split())
        content_words = set((title + " " + content + " " + summary).split())

        # 计算词重叠
        relevant_words = topic_words.intersection(content_words)
        relevance_ratio = len(relevant_words) / max(1, len(topic_words))

        # 增强匹配度（包含短语匹配）
        direct_match_score = 0.0
        if research_topic in title or research_topic in content:
            direct_match_score = 0.3

        semantic_match_score = self._assess_semantic_match(title + " " + content, research_topic)

        # 综合相关性分数
        relevance_score = min(1.0, (
            relevance_ratio * 0.3 +
            direct_match_score * 0.3 +
            semantic_match_score * 0.4
        ))

        details = {
            "relevant_words": list(relevant_words),
            "relevance_ratio": relevance_ratio,
            "direct_match": direct_match_score > 0,
            "semantic_match_score": semantic_match_score,
            "total_topic_words": len(topic_words),
            "matched_words": len(relevant_words)
        }

        return relevance_score, details

    def _assess_semantic_match(self, text: str, research_topic: str) -> float:
        """评估语义匹配（简化版）"""
        # 这里应该使用更复杂的语义匹配算法
        # 当前使用简单的关键词扩展匹配

        topic_lower = research_topic.lower()
        text_lower = text.lower()

        # 定义语义相关词集
        semantic_groups = {
            "竞品": ["竞争", "对手", "替代品", "comparative", "competitive"],
            "分析": ["研究", "调查", "评估", "analysis", "research"],
            "趋势": ["方向", "发展", "未来", "trend", "direction"],
            "技术": ["科技", "方法", "方案", "technology", "solution"],
            "政策": ["法规", "法律", "合规", "policy", "regulation"]
        }

        match_score = 0.0
        matches = []

        for key_term, related_terms in semantic_groups.items():
            if key_term in topic_lower:
                # 检查相关词在文本中的出现
                for related in related_terms:
                    if related in text_lower:
                        match_score += 0.1
                        matches.append(related)
                        break

        return min(1.0, match_score)

    def _assess_search_quality(self, result: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
        """评估搜索结果质量"""
        title = result.get("title", "")
        content = result.get("content", "")
        summary = result.get("summary", "")

        total_text = title + " " + content + " " + summary

        # 长度检查
        content_length = len(total_text)
        length_score = min(1.0, content_length / 1000)  # 按1000字符标准化

        # 结构检查
        has_numbers = any(char.isdigit() for char in total_text)
        has_bullets = any(char in total_text for char in ["•", "-", "*"])
        has_headings = any(tag in content for tag in ["<h", "##", "标题"])

        structure_score = 0.0
        if content_length > 200:
            structure_score += 0.2
        if has_numbers:
            structure_score += 0.2
        if has_bullets or has_headings:
            structure_score += 0.3

        structure_score = min(1.0, structure_score)

        # 语言质量检查（简化）
        unique_words = len(set(total_text.split()))
        diversity_score = min(1.0, unique_words / max(1, len(total_text.split())))

        # 综合质量分数
        quality_score = (length_score * 0.4 +
                        structure_score * 0.4 +
                        diversity_score * 0.2)

        details = {
            "content_length": content_length,
            "length_score": length_score,
            "has_structure": structure_score > 0.5,
            "structure_score": structure_score,
            "diversity_score": diversity_score,
            "has_numbers": has_numbers,
            "has_headings": has_headings
        }

        return quality_score, details

    def _assess_authority(self, result: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
        """评估权威性"""
        url = result.get("url", "").lower()
        title = result.get("title", "").lower()
        source = result.get("source", "").lower()

        authority_score = 0.0
        authority_indicators = []

        # 域名权威性
        trusted_domains = [
            ".edu", ".gov", ".org", "academic", "university",
            "research", "institute", "lab", "official"
        ]

        for domain in trusted_domains:
            if domain in url or domain in source:
                authority_score += 0.3
                authority_indicators.append(f"信任域名: {domain}")

        # 标题权威性关键词
        authority_terms = [
            "大学", "学院", "研究院", "实验室", "政府",
            "官方", "白皮书", "研究报告", "学术"
        ]

        for term in authority_terms:
            if term in title or term in source:
                authority_score += 0.2
                authority_indicators.append(f"权威标题词: {term}")
                break

        # 来源显示
        if source:
            authority_score += 0.2
            authority_indicators.append("有明确来源")

        # 限制分数在0-1
        authority_score = min(1.0, authority_score)

        details = {
            "authority_score": authority_score,
            "indicators": authority_indicators,
            "url": url[:100],
            "source": source
        }

        return authority_score, details

    def _assess_recency(self, result: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
        """评估时效性"""
        date_str = result.get("date", "").lower()
        current_year = 2024  # 应该动态获取

        recency_score = 0.0
        date_details = {}

        if date_str:
            # 尝试解析日期字符串
            year_matches = []
            for year in range(2020, current_year + 5):
                if str(year) in date_str:
                    year_matches.append(year)

            if year_matches:
                latest_year = max(year_matches)
                age = current_year - latest_year
                if age == 0:
                    recency_score = 1.0
                elif age == 1:
                    recency_score = 0.8
                elif age == 2:
                    recency_score = 0.6
                elif age == 3:
                    recency_score = 0.4
                else:
                    recency_score = 0.2

                date_details = {
                    "parsed_year": latest_year,
                    "age_years": age,
                    "original_date": date_str
                }
        else:
            # 无日期信息，使用默认评分
            recency_score = 0.3
            date_details = {"no_date_info": True}

        details = {
            "recency_score": recency_score,
            "date_info": date_details
        }

        return recency_score, details

    def _get_recommendation(self, overall_score: float) -> str:
        """根据分数给出推荐"""
        if overall_score >= 0.8:
            return "强烈推荐：高质量高相关性内容"
        elif overall_score >= 0.6:
            return "推荐：质量较好的相关内容"
        elif overall_score >= 0.4:
            return "谨慎考虑：质量一般或相关性有限"
        else:
            return "不推荐：质量差或相关性低"

    def _calculate_confidence(self, judgments: Dict[str, Any]) -> float:
        """计算判断的置信度"""
        confidence = 0.5  # 基础置信度

        # 基于评估完整性
        factors_checked = 0
        required_factors = ["relevance_score", "quality_score", "authority_score", "recency_score"]

        for factor in required_factors:
            if factor in judgments:
                factors_checked += 1

        completeness = factors_checked / len(required_factors)
        confidence += completeness * 0.3

        # 基于分数一致性
        scores = [
            judgments.get("relevance_score", 0.5),
            judgments.get("quality_score", 0.5),
            judgments.get("authority_score", 0.5),
            judgments.get("recency_score", 0.5)
        ]

        score_variance = max(scores) - min(scores)
        if score_variance <= 0.3:
            confidence += 0.1
        else:
            confidence -= 0.1

        return min(1.0, max(0.0, confidence))

    def _get_suggested_actions(self, judgments: Dict[str, Any]) -> List[Dict[str, Any]]:
        """获取处理建议"""
        actions = []

        # 基于相关性
        relevance_score = judgments.get("relevance_score", 0)
        if relevance_score < 0.4:
            actions.append({
                "action": "重新搜索",
                "reason": "相关性太低",
                "priority": "高"
            })
        elif relevance_score < 0.7:
            actions.append({
                "action": "补充额外信息",
                "reason": "相关性一般",
                "priority": "中"
            })

        # 基于质量
        quality_score = judgments.get("quality_score", 0)
        if quality_score < 0.5:
            actions.append({
                "action": "查找更权威来源",
                "reason": "内容质量不佳",
                "priority": "高"
            })

        # 基于时效性
        recency_score = judgments.get("recency_score", 0)
        if recency_score < 0.4:
            actions.append({
                "action": "更新数据来源",
                "reason": "信息可能过时",
                "priority": "中"
            })

        # 如果没有行动建议，添加默认建议
        if not actions:
            actions.append({
                "action": "直接使用",
                "reason": "各项指标均合格",
                "priority": "低"
            })

        return actions

    def _calculate_priority(self, judgments: Dict[str, Any], iteration: int) -> str:
        """计算处理优先级"""
        overall_score = judgments.get("overall_score", 0)
        confidence = judgments.get("confidence", 0.5)

        priority_score = overall_score * confidence

        # 早期迭代关注广度，后期关注深度
        iteration_factor = 1.0 - (iteration * 0.1)  # 每轮降低10%
        final_score = priority_score * iteration_factor

        if final_score >= 0.6:
            return "高"
        elif final_score >= 0.3:
            return "中"
        else:
            return "低"

    def _judge_intermediate_content(self, content: Dict[str, Any],
                                  research_topic: str,
                                  iteration: int) -> Dict[str, Any]:
        """判断中间内容质量"""
        # 这里应该评估文本内容的质量
        # 当前返回简化版本

        text = content.get("text", content.get("content", str(content)))
        text_length = len(str(text))

        judgments = {
            "content_type": "intermediate",
            "text_length": text_length,
            "has_structure": any(marker in str(text) for marker in ["##", "#", "标题", "段落"]),
            "estimated_quality": min(1.0, text_length / 500),  # 简单评估
            "recommendation": "继续处理" if text_length > 100 else "需补充内容",
            "should_keep": text_length > 50
        }

        return judgments

    def _judge_final_report(self, report: Dict[str, Any],
                           research_topic: str,
                           iteration: int) -> Dict[str, Any]:
        """判断最终报告质量"""
        judgments = {
            "report_type": "final",
            "has_structure": self._check_report_structure(report),
            "completeness": self._check_report_completeness(report),
            "evidence_support": self._check_evidence_support(report),
            "recommendations": self._get_report_recommendations(report)
        }

        # 计算总体质量
        scores = [
            1.0 if judgments["has_structure"] else 0.0,
            judgments["completeness"],
            judgments["evidence_support"]
        ]
        overall_quality = sum(scores) / len(scores)

        judgments["overall_quality"] = overall_quality
        judgments["status"] = "达标" if overall_quality >= 0.7 else "需改进"
        judgments["confidence"] = min(1.0, overall_quality * 1.2)

        return judgments

    def _check_report_structure(self, report: Dict[str, Any]) -> bool:
        """检查报告结构"""
        required_sections = ["摘要", "正文", "结论"]
        optional_sections = ["引言", "方法", "参考文献", "附录"]

        report_str = str(report).lower()

        found_required = 0
        for section in required_sections:
            if section in report_str:
                found_required += 1

        return found_required >= len(required_sections) - 1  # 允许缺失一个

    def _check_report_completeness(self, report: Dict[str, Any]) -> float:
        """检查报告完整性"""
        completeness = 0.0

        # 检查各部分的长度
        content = report.get("content", report.get("text", str(report)))
        content_length = len(str(content))

        if content_length > 1000:
            completeness += 0.3
        elif content_length > 500:
            completeness += 0.2
        else:
            completeness += 0.1

        # 检查是否有结论部分
        if "结论" in str(report) or "conclusion" in str(report).lower():
            completeness += 0.3

        # 检查是否有引用
        if "引用" in str(report) or "reference" in str(report).lower():
            completeness += 0.3

        # 检查是否有数据/图表
        if "数据" in str(report) or "图表" in str(report):
            completeness += 0.1

        return min(1.0, completeness)

    def _check_evidence_support(self, report: Dict[str, Any]) -> float:
        """检查证据支持"""
        content = str(report).lower()

        # 检查是否有引用标记
        citation_markers = ["[1]", "[2]", "[3]", "source:", "cite:", "reference:", "引用"]
        citation_count = sum(1 for marker in citation_markers if marker in content)

        citation_score = min(1.0, citation_count / 5)  # 最多5个引用

        # 检查是否有数据支持
        data_markers = ["数据", "统计", "数字", "百分比", "数据表", "图表"]
        has_data = any(marker in content for marker in data_markers)
        data_score = 0.3 if has_data else 0.0

        return min(1.0, citation_score * 0.7 + data_score * 0.3)

    def _get_report_recommendations(self, report: Dict[str, Any]) -> List[str]:
        """获取报告改进建议"""
        recommendations = []

        content = str(report)
        content_lower = content.lower()

        # 结构建议
        if "摘要" not in content:
            recommendations.append("添加摘要部分")
        if "结论" not in content_lower and "conclusion" not in content_lower:
            recommendations.append("添加结论部分")

        # 内容建议
        if len(content) < 1000:
            recommendations.append("内容不够详细，需要更多阐述")

        # 引用建议
        citation_count = sum(1 for marker in ["[1]", "[2]", "[3]"] if marker in content)
        if citation_count < 3:
            recommendations.append(f"增加引用数量（当前{citation_count}个，建议至少3个）")

        return recommendations

    def _judge_unknown_content(self, content: Any,
                              research_topic: str,
                              iteration: int) -> Dict[str, Any]:
        """判断未知类型内容"""
        content_str = str(content)

        return {
            "judgment_type": "unknown",
            "content_preview": content_str[:200] + ("..." if len(content_str) > 200 else ""),
            "content_length": len(content_str),
            "recommendation": "无法判断类型，请检查输入格式",
            "confidence": 0.1,
            "should_keep": False
        }

    def _get_timestamp(self) -> str:
        """获取时间戳"""
        from datetime import datetime
        return datetime.now().isoformat()


if __name__ == "__main__":
    # 测试代码
    import asyncio

    async def test():
        agent = QualityJudgmentAgent()

        # 测试搜索结果判断
        search_result = {
            "id": "result_001",
            "url": "https://example.com/research",
            "title": "数据分析竞品对比研究报告",
            "content": "本文对Python数据分析工具进行了全面对比...",
            "summary": "针对主流Python数据分析工具的功能对比",
            "date": "2023-10-15",
            "source": "科技研究院"
        }

        context = {
            "research_topic": "Python数据分析竞品对比",
            "iteration": 1
        }

        result = await agent.execute(search_result, context)
        print("搜索结果质量判断:")
        print(result.to_json())

    asyncio.run(test())
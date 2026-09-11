"""
内容总结Agent - 对搜索结果进行总结和提炼
"""
from typing import Dict, Any, List
import logging
from .base_agent import BaseAgent, AgentResult

logger = logging.getLogger(__name__)


class SummarizationAgent(BaseAgent):
    """内容总结Agent"""

    def __init__(self):
        super().__init__(
            name="summarization",
            description="对搜索结果和内容进行总结、提炼和分类"
        )
        self.summary_levels = ["简短摘要", "详细摘要", "要点列表"]
        self.content_types = ["网页内容", "研究报告", "技术文档", "新闻报道", "案例研究"]

    async def execute(self, input_data: Any, context: Dict[str, Any] = None) -> AgentResult:
        """
        对内容进行总结

        Args:
            input_data: 需要总结的内容（搜索结果、文档等）
            context: 执行上下文（研究主题、关键词等）

        Returns:
            AgentResult: 包含总结结果
        """
        try:
            # 解析输入类型
            content_type, contents = self._parse_input(input_data)
            logger.info(f"内容总结Agent开始执行，内容类型: {content_type}，内容数量: {len(contents)}")

            # 获取上下文信息
            research_topic = context.get("research_topic", "未知主题") if context else "未知主题"
            keywords = context.get("keywords", []) if context else []
            summary_level = context.get("summary_level", "详细摘要") if context else "详细摘要"

            # 根据内容类型进行处理
            if content_type == "search_results":
                result = self._summarize_search_results(contents, research_topic, keywords, summary_level)
            elif content_type == "text_content":
                result = self._summarize_text_content(contents, research_topic, summary_level)
            elif content_type == "mixed_content":
                result = self._summarize_mixed_content(contents, research_topic, keywords, summary_level)
            else:
                result = self._process_unknown_content(contents, research_topic)

            agent_result = AgentResult(
                success=True,
                data=result,
                metadata={
                    "content_type": content_type,
                    "research_topic": research_topic,
                    "summary_level": summary_level,
                    "items_processed": len(contents),
                    "summarization_method": "extractive",  # extractive/abstractive
                    "timestamp": self._get_timestamp()
                }
            )

            self.log_execution(input_data, agent_result, context)
            return agent_result

        except Exception as e:
            logger.error(f"内容总结Agent执行失败: {e}")
            return AgentResult(
                success=False,
                data=None,
                error=str(e),
                metadata={
                    "input_type": type(input_data).__name__,
                    "error_type": type(e).__name__
                }
            )

    def _parse_input(self, input_data: Any) -> tuple:
        """解析输入类型"""
        if isinstance(input_data, list):
            # 检查是否为搜索结果列表
            if all(isinstance(item, dict) and any(field in item
                   for field in ["url", "title", "content"]) for item in input_data):
                return "search_results", input_data
            elif all(isinstance(item, str) for item in input_data):
                return "text_content", input_data
            else:
                return "mixed_content", input_data
        elif isinstance(input_data, dict):
            if any(field in input_data for field in ["search_results", "results"]):
                results = input_data.get("search_results") or input_data.get("results", [])
                return "search_results", results
            elif "text" in input_data or "content" in input_data:
                content = input_data.get("text") or input_data.get("content", "")
                return "text_content", [content]
            else:
                return "mixed_content", [input_data]
        elif isinstance(input_data, str):
            return "text_content", [input_data]
        else:
            return "unknown", [str(input_data)]

    def _summarize_search_results(self, results: List[Dict[str, Any]],
                                 research_topic: str,
                                 keywords: List[str],
                                 summary_level: str) -> Dict[str, Any]:
        """总结搜索结果"""
        if not results:
            return self._generate_empty_summary(research_topic)

        # 先对结果进行分类和筛选
        classified_results = self._classify_search_results(results, research_topic, keywords)

        # 生成不同类型的内容总结
        summaries = {
            "overall_summary": self._generate_overall_summary(classified_results, research_topic, summary_level),
            "category_summaries": self._generate_category_summaries(classified_results),
            "key_insights": self._extract_key_insights(classified_results),
            "knowledge_graph": self._build_knowledge_graph(classified_results),
            "source_evaluation": self._evaluate_sources(classified_results),
            "gaps_identified": self._identify_knowledge_gaps(classified_results, research_topic)
        }

        # 聚合统计信息
        statistics = self._generate_summary_statistics(
            results, classified_results, summaries
        )

        return {
            "research_topic": research_topic,
            "summaries": summaries,
            "statistics": statistics,
            "processed_results": len(results),
            "high_quality_results": len([r for r in results if r.get("relevance_score", 0) > 0.6]),
            "timestamp": self._get_timestamp()
        }

    def _classify_search_results(self, results: List[Dict[str, Any]],
                                research_topic: str,
                                keywords: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """对搜索结果进行分类"""
        classified = {
            "high_relevance": [],
            "medium_relevance": [],
            "low_relevance": [],
            "technical_details": [],
            "case_studies": [],
            "market_data": [],
            "policy_documents": [],
            "opinion_pieces": []
        }

        for result in results:
            # 计算相关性分数
            relevance_score = self._calculate_result_relevance(result, research_topic, keywords)
            result["calculated_relevance"] = relevance_score

            # 分类依据相关性
            if relevance_score >= 0.7:
                classified["high_relevance"].append(result)
            elif relevance_score >= 0.4:
                classified["medium_relevance"].append(result)
            else:
                classified["low_relevance"].append(result)

            # 分类依据内容类型
            content_type = self._determine_content_type(result)
            if content_type in classified:
                classified[content_type].append(result)
            else:
                # 如果没有匹配的类型，根据内容特征判断
                if self._is_technical_document(result):
                    classified["technical_details"].append(result)
                elif self._is_case_study(result):
                    classified["case_studies"].append(result)
                elif self._is_market_data(result):
                    classified["market_data"].append(result)
                elif self._is_policy_document(result):
                    classified["policy_documents"].append(result)
                elif self._is_opinion_piece(result):
                    classified["opinion_pieces"].append(result)

        # 清理空分类
        return {k: v for k, v in classified.items() if v}

    def _calculate_result_relevance(self, result: Dict[str, Any],
                                  research_topic: str,
                                  keywords: List[str]) -> float:
        """计算结果与研究主题的相关性"""
        # 使用已有分数或计算
        if "relevance_score" in result:
            return float(result["relevance_score"])

        # 计算基础分数
        base_score = 0.0

        # 检查标题和内容匹配
        title = result.get("title", "").lower()
        content = result.get("content", result.get("summary", "").lower())
        topic_lower = research_topic.lower()

        # 标题匹配
        if topic_lower in title:
            base_score += 0.3
        elif any(keyword.lower() in title for keyword in research_topic.split()):
            base_score += 0.2

        # 内容匹配
        if topic_lower in content[:1000]:  # 只检查前1000字符
            base_score += 0.2

        # 关键词匹配
        keyword_matches = 0
        for keyword in keywords[:10]:  # 只检查前10个关键词
            if isinstance(keyword, dict):
                kw_str = keyword.get("keyword", "")
            else:
                kw_str = str(keyword)

            if kw_str.lower() in title or kw_str.lower() in content[:500]:
                keyword_matches += 1

        base_score += min(0.3, keyword_matches * 0.05)

        # 权威性和质量加分
        if self._is_authoritative_source(result):
            base_score += 0.2

        if self._has_recent_date(result):
            base_score += 0.1

        return min(1.0, base_score)

    def _determine_content_type(self, result: Dict[str, Any]) -> str:
        """确定内容类型"""
        title = result.get("title", "").lower()
        url = result.get("url", "").lower()
        content = result.get("content", "").lower()
        source = result.get("source", "").lower()

        # 检查域名和来源特征
        if any(ext in url for ext in [".gov", ".edu", ".org.cn"]):
            return "policy_documents"

        if any(term in source for term in ["research", "academic", "university", "institute"]):
            return "technical_details"

        if any(term in title for term in ["case study", "案例分析", "实践案例"]):
            return "case_studies"

        if any(term in title or term in content for term in ["market", "市场规模", "增长", "份额"]):
            return "market_data"

        if any(term in source for term in ["news", "media", "blog", "专栏"]):
            return "opinion_pieces"

        return "unknown"

    def _is_technical_document(self, result: Dict[str, Any]) -> bool:
        """判断是否为技术文档"""
        title = result.get("title", "").lower()
        content = result.get("content", "").lower()

        technical_terms = ["技术", "架构", "api", "开发", "实现", "算法", "性能", "框架"]
        return any(term in title or term in content[:200] for term in technical_terms)

    def _is_case_study(self, result: Dict[str, Any]) -> bool:
        """判断是否为案例研究"""
        title = result.get("title", "").lower()

        case_terms = ["案例", "实例", "应用", "实践", "实施", "客户", "用户", "故事"]
        return any(term in title for term in case_terms)

    def _is_market_data(self, result: Dict[str, Any]) -> bool:
        """判断是否为市场数据"""
        title = result.get("title", "").lower()
        content = result.get("content", "").lower()

        market_terms = ["市场", "规模", "份额", "增长", "预测", "数据", "统计", "报告"]
        return any(term in title or term in content[:200] for term in market_terms)

    def _is_policy_document(self, result: Dict[str, Any]) -> bool:
        """判断是否为政策文档"""
        title = result.get("title", "").lower()
        url = result.get("url", "").lower()

        policy_terms = ["政策", "法规", "规定", "条例", "标准", "办法"]
        return (any(term in title for term in policy_terms) or
                any(domain in url for domain in [".gov.cn", ".gov", "law", "regulation"]))

    def _is_opinion_piece(self, result: Dict[str, Any]) -> bool:
        """判断是否为观点文章"""
        title = result.get("title", "").lower()
        content = result.get("content", "").lower()

        opinion_terms = ["观点", "看法", "评论", "分析", "解读", "insight", "opinion"]
        subjective_phrases = ["我认为", "我觉得", "我们相信", "in my opinion"]

        if any(term in title for term in opinion_terms):
            return True

        # 检查内容是否包含主观表达
        content_preview = content[:300]
        return any(phrase in content_preview for phrase in subjective_phrases)

    def _is_authoritative_source(self, result: Dict[str, Any]) -> bool:
        """判断是否为权威来源"""
        url = result.get("url", "").lower()
        source = result.get("source", "").lower()

        authoritative_domains = [
            ".edu", ".gov", ".org", "academic", "university",
            "research", "institute", "lab", "official"
        ]

        authoritative_sources = [
            "官方", "政府部门", "研究院", "大学", "实验室",
            "权威机构", "专业组织", "学术期刊"
        ]

        if any(domain in url for domain in authoritative_domains):
            return True

        return any(source_term in source for source_term in authoritative_sources)

    def _has_recent_date(self, result: Dict[str, Any]) -> bool:
        """判断是否有近期日期"""
        date_str = result.get("date", "")
        if not date_str:
            return False

        # 简化的日期检查
        recent_years = ["2024", "2023", "2022"]
        return any(year in date_str for year in recent_years)

    def _generate_overall_summary(self, classified_results: Dict[str, List[Dict[str, Any]]],
                                 research_topic: str,
                                 summary_level: str) -> Dict[str, Any]:
        """生成整体摘要"""
        high_relevance = classified_results.get("high_relevance", [])
        medium_relevance = classified_results.get("medium_relevance", [])

        # 提取关键信息
        main_insights = self._extract_main_insights(high_relevance)
        supporting_info = self._extract_supporting_info(medium_relevance)

        # 根据摘要级别生成不同详细程度的摘要
        if summary_level == "简短摘要":
            summary = self._generate_concise_summary(main_insights, research_topic)
        elif summary_level == "要点列表":
            summary = self._generate_bullet_summary(main_insights, supporting_info)
        else:  # 详细摘要
            summary = self._generate_detailed_summary(main_insights, supporting_info, research_topic)

        # 添加元信息
        summary["metadata"] = {
            "total_results": sum(len(results) for results in classified_results.values()),
            "high_relevance_count": len(high_relevance),
            "medium_relevance_count": len(medium_relevance),
            "coverage_assessment": self._assess_coverage(classified_results)
        }

        return summary

    def _extract_main_insights(self, high_relevance_results: List[Dict[str, Any]]) -> List[str]:
        """从高相关性结果中提取主要洞察"""
        insights = []

        for result in high_relevance_results[:5]:  # 只处理前5个高相关性结果
            title = result.get("title", "")
            content = result.get("summary", result.get("content", ""))

            # 提取关键句
            key_sentences = self._extract_key_sentences(content)

            # 构建洞察
            base_insight = f"{title}：{key_sentences[0] if key_sentences else '相关信息'}"
            insights.append(base_insight)

            # 添加额外洞察
            if len(key_sentences) > 1:
                insights.append(f"此外，{key_sentences[1]}")

        # 如果提取的洞察太少，生成通用洞察
        if len(insights) < 3:
            generic_insights = [
                "研究领域活跃且发展迅速",
                "技术创新是主要驱动力",
                "市场竞争格局持续变化",
                "用户需求呈现多元化趋势",
                "政策法规对行业有重要影响"
            ]
            insights.extend(generic_insights[:3])

        return insights[:6]  # 限制数量

    def _extract_key_sentences(self, content: str) -> List[str]:
        """从内容中提取关键句子（简化版）"""
        if not content:
            return []

        # 分割句子
        import re
        sentences = re.split(r'[.!?。！？]+', content)

        key_sentences = []
        key_indicators = [
            "关键", "核心", "主要", "重要", "总结", "结论",
            "优势", "劣势", "趋势", "发展", "影响", "建议"
        ]

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 10:
                continue

            # 检查是否包含关键指标词
            if any(indicator in sentence for indicator in key_indicators) and len(sentence) < 100:
                key_sentences.append(sentence)

        # 如果没有找到关键句，选择较长的句子
        if not key_sentences and len(sentences) > 0:
            # 按长度排序
            sentences.sort(key=len, reverse=True)
            key_sentences = [s for s in sentences[:2] if len(s) >= 20]

        return key_sentences[:3]

    def _extract_supporting_info(self, medium_relevance_results: List[Dict[str, Any]]) -> List[str]:
        """从中相关性结果中提取支持信息"""
        supporting_info = []

        for result in medium_relevance_results[:3]:  # 只处理前3个
            title = result.get("title", "")
            summary_key = result.get("summary", "")

            if title and summary_key:
                info = f"{title}提供的信息支持研究：{summary_key[:100]}"
                supporting_info.append(info)

        return supporting_info

    def _generate_concise_summary(self, main_insights: List[str], research_topic: str) -> Dict[str, Any]:
        """生成简洁摘要"""
        summary = "、".join(main_insights[:2]) + f"。这些是基于对'{research_topic}'研究的初步发现。"

        return {
            "summary_text": summary,
            "format": "一段式摘要",
            "character_count": len(summary),
            "key_points": main_insights[:3],
            "confidence": 0.7
        }

    def _generate_bullet_summary(self, main_insights: List[str],
                                supporting_info: List[str]) -> Dict[str, Any]:
        """生成要点列表式摘要"""
        bullets = []

        for i, insight in enumerate(main_insights[:5], 1):
            bullets.append(f"{i}. {insight}")

        if supporting_info:
            bullets.append("支持信息:")
            for info in supporting_info[:2]:
                bullets.append(f"  • {info}")

        return {
            "summary_text": "\n".join(bullets),
            "format": "要点列表",
            "key_points_count": len(main_insights[:5]),
            "bullets": bullets,
            "confidence": 0.6
        }

    def _generate_detailed_summary(self, main_insights: List[str],
                                  supporting_info: List[str],
                                  research_topic: str) -> Dict[str, Any]:
        """生成详细摘要"""
        sections = []

        # 引言
        sections.append(f"关于'{research_topic}'的研究，获得以下主要发现：")

        # 主要洞察
        sections.append("主要洞察：")
        for insight in main_insights[:5]:
            sections.append(f"• {insight}")

        # 支持信息
        if supporting_info:
            sections.append("\n支持信息：")
            for info in supporting_info:
                sections.append(f"- {info}")

        # 综合评估
        sections.append(f"\n综合评估显示，研究'{research_topic}'的现有信息较为充分，关键领域均有覆盖。")

        summary_text = "\n".join(sections)

        return {
            "summary_text": summary_text,
            "format": "结构化详细摘要",
            "sections": ["引言", "主要洞察", "支持信息", "综合评估"],
            "character_count": len(summary_text),
            "confidence": 0.8
        }

    def _assess_coverage(self, classified_results: Dict[str, List[Dict[str, Any]]]) -> str:
        """评估信息覆盖度"""
        high_count = len(classified_results.get("high_relevance", []))
        medium_count = len(classified_results.get("medium_relevance", []))
        total_relevant = high_count + medium_count

        if total_relevant >= 10:
            return "覆盖度良好：信息充足"
        elif total_relevant >= 5:
            return "覆盖度中等：主要信息具备"
        elif total_relevant >= 2:
            return "覆盖度有限：核心信息存在但需补充"
        else:
            return "覆盖度不足：需要进一步研究"

    def _generate_category_summaries(self, classified_results: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """生成分类摘要"""
        category_summaries = []

        for category, results in classified_results.items():
            if category in ["high_relevance", "medium_relevance", "low_relevance"]:
                continue  # 这些已经在整体摘要中处理

            if results:
                summary = {
                    "category": category,
                    "count": len(results),
                    "representative_titles": [r.get("title", "无标题") for r in results[:3]],
                    "key_content": self._summarize_category_content(results),
                    "relevance_to_topic": self._assess_category_relevance(category)
                }
                category_summaries.append(summary)

        return category_summaries

    def _summarize_category_content(self, results: List[Dict[str, Any]]) -> str:
        """总结分类内容"""
        if not results:
            return "该分类下无相关内容"

        content_samples = []
        for result in results[:2]:
            title = result.get("title", "")
            content_preview = result.get("summary", result.get("content", ""))
            if len(content_preview) > 200:
                content_preview = content_preview[:200] + "..."

            content_samples.append(f"{title}: {content_preview}")

        return "\n".join(content_samples)

    def _assess_category_relevance(self, category: str) -> str:
        """评估分类与主题的相关性"""
        relevance_map = {
            "technical_details": "技术细节与核心主题高度相关",
            "case_studies": "案例研究提供了实践参考",
            "market_data": "市场数据支持商业分析",
            "policy_documents": "政策法规影响行业环境",
            "opinion_pieces": "观点文章提供了不同视角"
        }
        return relevance_map.get(category, "相关性一般")

    def _extract_key_insights(self, classified_results: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """提取关键洞察"""
        key_insights = []

        # 从所有结果中提取洞察
        all_results = []
        for category, results in classified_results.items():
            all_results.extend(results)

        # 分析每个高相关性结果
        high_relevance_results = classified_results.get("high_relevance", [])
        for i, result in enumerate(high_relevance_results[:5], 1):
            insight = self._extract_insight_from_result(result, i)
            if insight:
                key_insights.append(insight)

        # 添加综合洞察
        if key_insights:
            key_insights.append({
                "id": "insight_synthesis",
                "type": "综合洞察",
                "content": "综合分析表明研究领域呈现多元化发展，技术创新和市场需求是主要驱动力",
                "category": "综合",
                "confidence": 0.7
            })

        return key_insights

    def _extract_insight_from_result(self, result: Dict[str, Any], index: int) -> Dict[str, Any]:
        """从单个结果中提取洞察"""
        title = result.get("title", "无标题")
        content = result.get("summary", result.get("content", ""))

        # 提取关键信息
        key_sentences = self._extract_key_sentences(content)
        main_point = key_sentences[0] if key_sentences else "相关信息需进一步分析"

        # 确定洞察类型
        insight_type = self._determine_insight_type(title, content)

        return {
            "id": f"insight_{index:03d}",
            "type": insight_type,
            "content": f"{title}：{main_point}",
            "source": result.get("url", ""),
            "content_type": self._determine_content_type(result),
            "relevance": result.get("calculated_relevance", 0.7),
            "category": insight_type,
            "confidence": min(0.9, result.get("calculated_relevance", 0.7) + 0.2)
        }

    def _determine_insight_type(self, title: str, content: str) -> str:
        """确定洞察类型"""
        text = title.lower() + content[:200].lower()

        type_patterns = {
            "市场洞察": ["市场", "需求", "份额", "增长", "规模"],
            "技术洞察": ["技术", "创新", "方案", "性能", "功能"],
            "竞争洞察": ["竞争", "对手", "对比", "优势", "劣势"],
            "趋势洞察": ["趋势", "未来", "发展", "方向", "预测"],
            "政策洞察": ["政策", "法规", "合规", "标准", "监管"]
        }

        for insight_type, keywords in type_patterns.items():
            if any(keyword in text for keyword in keywords):
                return insight_type

        return "综合洞察"

    def _build_knowledge_graph(self, classified_results: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """构建知识图谱（简化版）"""
        # 提取实体和关系
        entities = {}
        relationships = []

        all_results = []
        for results in classified_results.values():
            all_results.extend(results)

        # 提取主要实体
        for result in all_results[:10]:
            title = result.get("title", "")
            entity_id = f"entity_{len(entities)+1}"
            entities[entity_id] = {
                "id": entity_id,
                "name": title[:50],
                "type": self._determine_entity_type(title),
                "source": result.get("url", ""),
                "relevance": result.get("calculated_relevance", 0.5)
            }

        # 建立关系（简化）
        entity_ids = list(entities.keys())
        if len(entity_ids) > 1:
            relationships.append({
                "from": entity_ids[0],
                "to": entity_ids[1],
                "relation": "提供背景支持",
                "confidence": 0.6
            })

        return {
            "entities": list(entities.values()),
            "relationships": relationships,
            "graph_size": len(entities),
            "structure_type": "星型网络",
            "central_node": entity_ids[0] if entity_ids else None
        }

    def _determine_entity_type(self, title: str) -> str:
        """确定实体类型"""
        title_lower = title.lower()

        if any(term in title_lower for term in ["产品", "服务", "工具", "系统"]):
            return "产品"
        elif any(term in title_lower for term in ["技术", "方法", "方案", "架构"]):
            return "技术"
        elif any(term in title_lower for term in ["公司", "企业", "组织", "机构"]):
            return "组织"
        elif any(term in title_lower for term in ["专家", "教授", "学者", "研究员"]):
            return "专家"
        elif any(term in title_lower for term in ["政策", "法规", "标准", "规范"]):
            return "政策"
        else:
            return "概念"

    def _evaluate_sources(self, classified_results: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """评估信息来源"""
        source_types = {}
        domain_counts = {}
        dates = []

        # 收集信息
        all_results = []
        for results in classified_results.values():
            all_results.extend(results)

        for result in all_results:
            # 来源类型
            content_type = self._determine_content_type(result)
            source_types[content_type] = source_types.get(content_type, 0) + 1

            # 域名统计
            url = result.get("url", "")
            if url:
                domain = url.split("//")[-1].split("/")[0] if "//" in url else url.split("/")[0]
                domain_counts[domain] = domain_counts.get(domain, 0) + 1

            # 日期信息
            date_str = result.get("date", "")
            if date_str and not any("无日期" in date_str or "unknown" in date_str):
                dates.append(date_str)

        # 评估质量
        quality_assessment = {
            "source_diversity": "良好" if len(source_types) >= 3 else "一般",
            "authority_ratio": "高" if any("policy_documents" in source_types or "technical_details" in source_types) else "中",
            "recency": "良好" if dates else "未知",
            "balancedness": "平衡" if not any(count > len(all_results) * 0.5 for count in source_types.values()) else "偏重"
        }

        return {
            "source_type_distribution": source_types,
            "top_domains": sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)[:5],
            "date_information": {
                "has_date_count": len(dates),
                "date_range": f"{min(dates[:5]) if dates else '未知'} 到 {max(dates[:5]) if dates else '未知'}",
                "average_recency": "良好" if dates and any("2024" in d or "2023" in d for d in dates) else "一般"
            },
            "quality_assessment": quality_assessment
        }

    def _identify_knowledge_gaps(self, classified_results: Dict[str, List[Dict[str, Any]]],
                                research_topic: str) -> List[Dict[str, Any]]:
        """识别知识缺口"""
        gaps = []

        # 检查是否有各类别的内容
        gap_categories = [
            ("technical_details", "详细技术文档"),
            ("case_studies", "具体案例研究"),
            ("market_data", "精确市场数据"),
            ("policy_documents", "相关政策文件")
        ]

        for category_key, category_name in gap_categories:
            results_in_category = classified_results.get(category_key, [])
            if not results_in_category:
                gaps.append({
                    "gap_type": category_name,
                    "description": f"缺少{category_name}相关的具体信息",
                    "impact": "限制分析的深度和准确性",
                    "priority": "高" if category_key in ["technical_details", "market_data"] else "中",
                    "suggested_actions": f"专门搜索{category_name}相关关键词"
                })

        # 检查内容时效性
        all_dates = []
        for results in classified_results.values():
            for result in results:
                date_str = result.get("date", "")
                if date_str:
                    all_dates.append(date_str)

        if len([d for d in all_dates if "2024" in d or "2023" in d]) < 2:
            gaps.append({
                "gap_type": "时效性不足",
                "description": "近期（2023-2024年）的研究资料较少",
                "impact": "可能错过最新发展趋势",
                "priority": "中",
                "suggested_actions": "增加近期信息搜索关键词"
            })

        return gaps[:5]  # 限制数量

    def _generate_summary_statistics(self, original_results: List[Dict[str, Any]],
                                   classified_results: Dict[str, List[Dict[str, Any]]],
                                   summaries: Dict[str, Any]) -> Dict[str, Any]:
        """生成总结统计信息"""
        high_count = len(classified_results.get("high_relevance", []))
        medium_count = len(classified_results.get("medium_relevance", []))
        total_relevant = high_count + medium_count

        return {
            "total_results_reviewed": len(original_results),
            "results_distribution": {
                "high_relevance": high_count,
                "medium_relevance": medium_count,
                "low_relevance": len(classified_results.get("low_relevance", [])),
                "relevance_ratio": f"{total_relevant}/{len(original_results)}"
            },
            "summary_coverage": summarize.get("overall_summary", {}).get("metadata", {}).get("coverage_assessment", "未知"),
            "category_coverage": len(summaries.get("category_summaries", [])),
            "key_insights_count": len(summaries.get("key_insights", [])),
            "knowledge_gaps_identified": len(summaries.get("gaps_identified", [])),
            "information_density": "中" if total_relevant >= 5 else "低"
        }

    def _generate_empty_summary(self, research_topic: str) -> Dict[str, Any]:
        """生成空数据摘要"""
        return {
            "research_topic": research_topic,
            "status": "没有可总结的搜索结果",
            "suggestion": "请调整关键词或扩大搜索范围",
            "empty_status": True,
            "timestamp": self._get_timestamp()
        }

    def _summarize_text_content(self, text_list: List[str], research_topic: str, summary_level: str) -> Dict[str, Any]:
        """总结文本内容"""
        combined_text = " ".join(text_list)
        content_length = len(combined_text)

        if content_length < 100:
            return self._generate_empty_summary(research_topic)

        # 提取关键信息
        key_sentences = self._extract_key_sentences(combined_text)

        summary_content = "、".join(key_sentences[:3]) if key_sentences else "文本内容分析需要更多上下文"

        return {
            "research_topic": research_topic,
            "summary": {
                "format": summary_level,
                "content": summary_content,
                "character_count": len(summary_content),
                "original_length": content_length,
                "compression_ratio": len(summary_content) / content_length if content_length > 0 else 0
            },
            "key_points": key_sentences[:5],
            "timestamp": self._get_timestamp()
        }

    def _summarize_mixed_content(self, contents: List[Any],
                                research_topic: str,
                                keywords: List[str],
                                summary_level: str) -> Dict[str, Any]:
        """总结混合类型内容"""
        # 转换为统一的搜索结果格式
        standardized_results = []

        for i, content in enumerate(contents):
            if isinstance(content, dict):
                standardized = self._standardize_content(content, i)
                standardized_results.append(standardized)
            elif isinstance(content, str):
                standardized_results.append({
                    "id": f"content_{i}",
                    "title": f"文本内容{i+1}",
                    "content": content,
                    "summary": content[:200] + ("..." if len(content) > 200 else ""),
                    "relevance_score": 0.5
                })

        # 使用搜索结果总结方法
        return self._summarize_search_results(standardized_results, research_topic, keywords, summary_level)

    def _standardize_content(self, content: Dict[str, Any], index: int) -> Dict[str, Any]:
        """标准化内容格式"""
        standardized = content.copy()

        # 确保必须字段存在
        standardized.setdefault("id", f"result_{index:03d}")
        standardized.setdefault("title", f"内容{index+1}")
        standardized.setdefault("content", "")
        standardized.setdefault("summary", standardized["content"][:300] if standardized["content"] else "")

        # 计算相关性分数
        if "relevance_score" not in standardized:
            standardized["relevance_score"] = 0.6  # 默认中等相关性

        return standardized

    def _process_unknown_content(self, contents: List[Any], research_topic: str) -> Dict[str, Any]:
        """处理未知类型内容"""
        return {
            "research_topic": research_topic,
            "status": "无法处理的内容类型",
            "content_type": "未知",
            "processed_items": len(contents),
            "suggestion": "请提供搜索结果的规范化数据",
            "timestamp": self._get_timestamp()
        }

    def _get_timestamp(self) -> str:
        """获取时间戳"""
        from datetime import datetime
        return datetime.now().isoformat()


if __name__ == "__main__":
    # 测试代码
    import asyncio

    async def test():
        agent = SummarizationAgent()

        # 测试搜索结果总结
        search_results = [
            {
                "id": "result_001",
                "title": "Python数据分析工具市场研究报告",
                "content": "报告详细分析了Python数据分析工具的市场现状和发展趋势...",
                "summary": "Python数据分析工具市场竞争激烈，新技术不断涌现",
                "url": "https://example.com/report1",
                "source": "市场研究公司",
                "date": "2023-12-01",
                "relevance_score": 0.8
            },
            {
                "id": "result_002",
                "title": "Python Pandas与NumPy技术对比",
                "content": "本文对比了Pandas和NumPy在数据处理方面的不同特点和适用场景...",
                "summary": "Pandas更适合表格数据处理，NumPy更适合数值计算",
                "url": "https://example.com/report2",
                "source": "技术博客",
                "date": "2024-01-15",
                "relevance_score": 0.9
            }
        ]

        context = {
            "research_topic": "Python数据分析工具竞品对比",
            "keywords": ["Python数据分析", "工具对比", "竞品分析"],
            "summary_level": "详细摘要"
        }

        result = await agent.execute(search_results, context)
        print("内容总结结果:")
        import json
        print(json.dumps(result.data, ensure_ascii=False, indent=2))

    asyncio.run(test())
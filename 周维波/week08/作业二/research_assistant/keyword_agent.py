"""
关键词生成Agent - 根据研究主题生成搜索关键词
"""
from typing import Dict, Any, List
import logging
from .base_agent import BaseAgent, AgentResult

logger = logging.getLogger(__name__)


class KeywordGeneratorAgent(BaseAgent):
    """关键词生成Agent"""

    def __init__(self):
        super().__init__(
            name="keyword_generator",
            description="根据研究主题生成搜索关键词，支持多轮迭代优化"
        )
        self.keyword_categories = [
            "核心概念", "技术术语", "竞品名称", "行业术语",
            "政策文件", "发展趋势", "常见问题", "最佳实践"
        ]

    async def execute(self, input_data: Any, context: Dict[str, Any] = None) -> AgentResult:
        """
        生成搜索关键词

        Args:
            input_data: 研究主题（字符串）
            context: 执行上下文（可能包含历史关键词、迭代轮数等）

        Returns:
            AgentResult: 包含生成的关键词
        """
        try:
            # 解析输入
            research_topic = self._parse_input(input_data)
            logger.info(f"关键词生成Agent开始执行，研究主题: {research_topic}")

            # 获取上下文信息
            iteration = context.get("iteration", 1) if context else 1
            previous_keywords = context.get("previous_keywords", []) if context else []
            previous_results = context.get("previous_results", []) if context else []

            # 生成关键词
            keywords = self._generate_keywords(
                research_topic=research_topic,
                iteration=iteration,
                previous_keywords=previous_keywords,
                previous_results=previous_results
            )

            # 组织结果
            result = {
                "research_topic": research_topic,
                "keywords": keywords,
                "total_keywords": len(keywords),
                "iteration": iteration,
                "categories": self._categorize_keywords(keywords),
                "suggested_search_strategies": self._generate_search_strategies(keywords),
                "variations": self._generate_keyword_variations(keywords)
            }

            agent_result = AgentResult(
                success=True,
                data=result,
                metadata={
                    "iteration": iteration,
                    "generation_method": "rule_based",  # 未来可改为"llm_based"
                    "categories_used": len(self.keyword_categories),
                    "timestamp": self._get_timestamp()
                }
            )

            self.log_execution(input_data, agent_result, context)
            return agent_result

        except Exception as e:
            logger.error(f"关键词生成Agent执行失败: {e}")
            return AgentResult(
                success=False,
                data=None,
                error=str(e),
                metadata={"research_topic": str(input_data)[:50]}
            )

    def _parse_input(self, input_data: Any) -> str:
        """解析输入数据"""
        if isinstance(input_data, str):
            return input_data.strip()
        elif isinstance(input_data, dict):
            return input_data.get("research_topic", str(input_data))
        else:
            return str(input_data)

    def _generate_keywords(self, research_topic: str, iteration: int = 1,
                          previous_keywords: List[str] = None,
                          previous_results: List[Dict] = None) -> List[Dict[str, Any]]:
        """生成关键词"""
        keywords = []

        # 第一轮：基础关键词
        if iteration == 1:
            keywords.extend(self._generate_basic_keywords(research_topic))

        # 后续轮次：基于反馈优化
        else:
            keywords.extend(self._optimize_keywords(
                research_topic, previous_keywords, previous_results
            ))

        # 添加分类信息
        categorized_keywords = []
        for i, kw in enumerate(keywords, 1):
            if isinstance(kw, dict):
                keyword_entry = kw
            else:
                keyword_entry = {"keyword": kw, "weight": 1.0}

            # 确保有基本字段
            keyword_entry.setdefault("keyword", str(kw))
            keyword_entry.setdefault("weight", 1.0)
            keyword_entry.setdefault("category", self._assign_category(kw))
            keyword_entry.setdefault("priority", self._calculate_priority(kw, iteration))
            keyword_entry["id"] = f"kw_{i:03d}"

            categorized_keywords.append(keyword_entry)

        # 按优先级排序
        categorized_keywords.sort(key=lambda x: x["priority"], reverse=True)

        return categorized_keywords

    def _generate_basic_keywords(self, research_topic: str) -> List[str]:
        """生成基础关键词"""
        keywords = []

        # 主题本身
        keywords.append(research_topic)

        # 分割主题词
        words = research_topic.split()

        # 添加核心词
        for word in words:
            if len(word) > 3:  # 忽略太短的词
                keywords.append(word)

        # 添加常见变体
        topic_lower = research_topic.lower()

        # 根据主题类型添加相关关键词
        if any(term in topic_lower for term in ["竞品", "竞争", "对比", "vs"]):
            keywords.extend(["竞品分析", "市场份额", "竞争优势", "产品差异"])

        if any(term in topic_lower for term in ["行业", "趋势", "发展", "未来"]):
            keywords.extend(["行业报告", "市场趋势", "发展预测", "市场规模"])

        if any(term in topic_lower for term in ["技术", "方案", "选型", "工具"]):
            keywords.extend(["技术对比", "方案评估", "选型指南", "性能比较"])

        if any(term in topic_lower for term in ["政策", "法规", "法律", "合规"]):
            keywords.extend(["政策解读", "法规分析", "合规要求", "政府文件"])

        # 添加常见修饰词
        modifiers = ["最新", "2024", "2025", "分析", "研究", "报告", "白皮书", "指南"]
        base_keywords = keywords.copy()

        for base in base_keywords:
            for modifier in modifiers:
                keywords.append(f"{base} {modifier}")

        # 去重并返回
        seen = set()
        unique_keywords = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique_keywords.append(kw)

        return unique_keywords[:50]  # 限制数量

    def _optimize_keywords(self, research_topic: str,
                          previous_keywords: List[str],
                          previous_results: List[Dict]) -> List[str]:
        """基于反馈优化关键词"""
        optimized_keywords = []

        # 分析之前的结果
        if previous_results:
            successful_keywords = self._analyze_successful_keywords(previous_results)
            optimized_keywords.extend(successful_keywords)

        # 保留之前有效的关键词
        if previous_keywords:
            # 这里应该分析哪些关键词效果好，暂时保留所有
            optimized_keywords.extend(previous_keywords)

        # 生成新的扩展关键词
        for keyword in set(optimized_keywords):
            # 添加同义词
            synonyms = self._get_synonyms(keyword)
            optimized_keywords.extend(synonyms)

            # 添加相关术语
            related_terms = self._get_related_terms(keyword, research_topic)
            optimized_keywords.extend(related_terms)

        # 去重
        seen = set()
        unique_keywords = []
        for kw in optimized_keywords:
            if isinstance(kw, dict):
                kw_str = kw.get("keyword", str(kw))
            else:
                kw_str = str(kw)

            if kw_str not in seen:
                seen.add(kw_str)
                unique_keywords.append(kw_str)

        return unique_keywords[:60]  # 限制数量

    def _analyze_successful_keywords(self, previous_results: List[Dict]) -> List[str]:
        """分析哪些关键词搜索效果好"""
        successful_keywords = []

        for result in previous_results:
            if isinstance(result, dict):
                relevance = result.get("relevance_score", 0)
                if relevance > 0.7:  # 高相关性结果
                    keywords_used = result.get("keywords_used", [])
                    successful_keywords.extend(keywords_used)

        return list(set(successful_keywords))

    def _get_synonyms(self, keyword: str) -> List[str]:
        """获取同义词（简化版）"""
        synonyms_map = {
            "分析": ["研究", "调查", "解析", "剖析"],
            "报告": ["文档", "白皮书", "研究", "论文"],
            "趋势": ["动向", "方向", "发展", "演变"],
            "技术": ["科技", "技巧", "方法", "方案"],
            "竞品": ["竞争对手", "竞争产品", "同类产品"],
            "政策": ["法规", "法律", "规定", "条例"]
        }

        synonyms = []
        for term, syn_list in synonyms_map.items():
            if term in keyword:
                for syn in syn_list:
                    synonyms.append(keyword.replace(term, syn))

        return synonyms

    def _get_related_terms(self, keyword: str, research_topic: str) -> List[str]:
        """获取相关术语"""
        related_terms = []

        # 根据关键词类型添加相关词
        keyword_lower = keyword.lower()

        if any(term in keyword_lower for term in ["python", "java", "c++", "javascript"]):
            related_terms.extend(["编程", "开发", "代码", "框架", "库"])

        if any(term in keyword_lower for term in ["数据", "分析", "统计"]):
            related_terms.extend(["大数据", "机器学习", "人工智能", "可视化"])

        if any(term in keyword_lower for term in ["市场", "商业", "经济"]):
            related_terms.extend(["营销", "销售", "客户", "收入", "利润"])

        return related_terms

    def _assign_category(self, keyword: Any) -> str:
        """分配关键词类别"""
        if isinstance(keyword, dict):
            kw_str = keyword.get("keyword", str(keyword))
        else:
            kw_str = str(keyword)

        kw_lower = kw_str.lower()

        # 匹配类别
        category_rules = {
            "核心概念": ["竞品", "分析", "趋势", "技术", "政策"],
            "技术术语": ["api", "框架", "算法", "架构", "协议"],
            "竞品名称": ["vs", "对比", "competitor", "alternative"],
            "行业术语": ["市场", "行业", "垂直", "细分", "b2b", "b2c"],
            "政策文件": ["法规", "法律", "合规", "标准", "规范"],
            "发展趋势": ["未来", "预测", "趋势", "方向", "新兴"],
            "常见问题": ["问题", "挑战", "难点", "痛点", "faq"],
            "最佳实践": ["最佳", "实践", "指南", "方法", "经验"]
        }

        for category, terms in category_rules.items():
            if any(term in kw_lower for term in terms):
                return category

        return "其他"

    def _calculate_priority(self, keyword: Any, iteration: int) -> float:
        """计算关键词优先级（0-1）"""
        if isinstance(keyword, dict):
            kw_str = keyword.get("keyword", str(keyword))
            weight = keyword.get("weight", 1.0)
        else:
            kw_str = str(keyword)
            weight = 1.0

        priority = 0.5 * weight

        # 长度因素：中等长度的关键词通常更好
        length = len(kw_str)
        if 3 <= length <= 20:
            priority += 0.2
        elif length > 30:
            priority -= 0.1

        # 迭代轮次：后续轮次的新关键词优先级较低
        if iteration > 1:
            priority -= 0.1 * (iteration - 1)

        return max(0.1, min(1.0, priority))

    def _categorize_keywords(self, keywords: List[Dict]) -> Dict[str, List[str]]:
        """按类别组织关键词"""
        categorized = {category: [] for category in self.keyword_categories}
        categorized["其他"] = []

        for kw in keywords:
            category = kw.get("category", "其他")
            keyword_text = kw.get("keyword", str(kw))

            if category in categorized:
                categorized[category].append(keyword_text)
            else:
                categorized["其他"].append(keyword_text)

        # 移除空类别
        return {k: v for k, v in categorized.items() if v}

    def _generate_search_strategies(self, keywords: List[Dict]) -> List[Dict[str, Any]]:
        """生成搜索策略"""
        strategies = []

        # 策略1: 精确搜索
        top_keywords = [k["keyword"] for k in keywords[:5]]
        strategies.append({
            "name": "精确搜索",
            "description": "使用核心关键词进行精确匹配",
            "keywords": top_keywords,
            "suggested_operators": ['" "', "site:.edu", "filetype:pdf"],
            "platforms": ["Google", "百度", "学术数据库"]
        })

        # 策略2: 组合搜索
        combinations = []
        for i in range(0, min(3, len(top_keywords))):
            for j in range(i + 1, min(5, len(top_keywords))):
                combinations.append(f'{top_keywords[i]} AND {top_keywords[j]}')

        strategies.append({
            "name": "组合搜索",
            "description": "多个关键词组合搜索",
            "keyword_combinations": combinations[:5],
            "suggested_operators": ["AND", "OR"],
            "platforms": ["Google Scholar", "CNKI", "IEEE Xplore"]
        })

        # 策略3: 扩展搜索
        technical_terms = [k["keyword"] for k in keywords if k.get("category") == "技术术语"]
        if technical_terms:
            strategies.append({
                "name": "技术深入搜索",
                "description": "针对技术细节的深入搜索",
                "keywords": technical_terms[:5],
                "suggested_operators": ["intitle:", "inurl:"],
                "platforms": ["Stack Overflow", "GitHub", "技术博客"]
            })

        return strategies

    def _generate_keyword_variations(self, keywords: List[Dict]) -> List[Dict[str, Any]]:
        """生成关键词变体"""
        variations = []

        for kw in keywords[:10]:  # 只处理前10个
            keyword = kw["keyword"]
            variations_for_kw = {
                "base_keyword": keyword,
                "language_variations": self._get_language_variations(keyword),
                "time_variations": self._get_time_variations(keyword),
                "format_variations": self._get_format_variations(keyword),
                "scope_variations": self._get_scope_variations(keyword)
            }
            variations.append(variations_for_kw)

        return variations

    def _get_language_variations(self, keyword: str) -> List[str]:
        """获取语言变体"""
        variations = []

        # 中英文混合（简化版）
        translations = {
            "分析": "analysis",
            "报告": "report",
            "趋势": "trend",
            "技术": "technology",
            "竞品": "competitor",
            "政策": "policy"
        }

        for chinese, english in translations.items():
            if chinese in keyword:
                variations.append(keyword.replace(chinese, english))
                variations.append(keyword.replace(chinese, f"{chinese}({english})"))

        return variations

    def _get_time_variations(self, keyword: str) -> List[str]:
        """获取时间变体"""
        time_terms = ["最新", "2024", "2023", "近期", "年度", "季度"]
        variations = []

        for term in time_terms:
            variations.append(f"{keyword} {term}")
            variations.append(f"{term} {keyword}")

        return variations

    def _get_format_variations(self, keyword: str) -> List[str]:
        """获取格式变体"""
        formats = ["PDF", "白皮书", "研究报告", "学术论文", "博客文章", "视频教程"]
        variations = []

        for fmt in formats:
            variations.append(f"{keyword} {fmt}")
            variations.append(f"{fmt} {keyword}")

        return variations

    def _get_scope_variations(self, keyword: str) -> List[str]:
        """获取范围变体"""
        scopes = ["中国", "全球", "美国", "欧洲", "亚洲", "国内市场", "国际市场"]
        variations = []

        for scope in scopes:
            variations.append(f"{keyword} {scope}")
            variations.append(f"{scope} {keyword}")

        return variations

    def _get_timestamp(self) -> str:
        """获取时间戳"""
        from datetime import datetime
        return datetime.now().isoformat()


if __name__ == "__main__":
    # 测试代码
    import asyncio

    async def test():
        agent = KeywordGeneratorAgent()

        # 测试关键词生成
        research_topic = "Python数据分析竞品对比"
        result = await agent.execute(research_topic)
        print("关键词生成结果:")
        print(result.to_json())

    asyncio.run(test())
const DIMENSIONS = [
  {
    key: "overview",
    label: "概况与现状",
    queries: ["概述", "现状", "整体情况", "关键发现"],
    keywords: ["现状", "概述", "整体", "行业", "发展", "领域", "市场规模"]
  },
  {
    key: "market",
    label: "市场规模与数据",
    queries: ["市场规模", "行业数据", "统计", "份额", "增长"],
    keywords: ["市场", "规模", "亿元", "万亿", "增长率", "份额", "数据", "增长"]
  },
  {
    key: "players",
    label: "主要玩家与竞品",
    queries: ["主要玩家", "头部企业", "竞品分析", "对标公司", "代表产品"],
    keywords: ["公司", "企业", "厂商", "竞品", "平台", "品牌", "玩家", "头部"]
  },
  {
    key: "technology",
    label: "技术方案与趋势",
    queries: ["技术方案", "核心技术", "行业趋势", "路线图", "架构"],
    keywords: ["技术", "架构", "算法", "模型", "趋势", "方案", "解决方案", "平台"]
  },
  {
    key: "policy",
    label: "政策法规与风险",
    queries: ["政策", "法规", "监管", "合规风险", "挑战"],
    keywords: ["政策", "法规", "监管", "合规", "风险", "挑战", "安全", "标准"]
  },
  {
    key: "recent",
    label: "近期动态",
    queries: ["最新进展", "近期动态", "2026", "报告发布", "融资合作"],
    keywords: ["发布", "融资", "合作", "最新", "2026", "更新", "上线"]
  }
];

const BOCHA_ENDPOINT = "https://api.bocha.cn/v1/web-search";
const DEFAULT_API_KEY = "sk-3d2293ad83aa4823a7c7ce8dd5ff8c72";

function buildQueries(topic) {
  return DIMENSIONS.flatMap((dimension) => {
    const primary = `${topic} ${dimension.queries[0]}`;
    const secondary = `${topic} ${dimension.queries[1] || dimension.label}`;
    return [
      { query: primary, dimension: dimension.key },
      { query: secondary, dimension: dimension.key }
    ];
  });
}

function buildGapQueries(topic, dimension) {
  return [
    `${topic} ${dimension.label} 数据`,
    `${topic} ${dimension.queries[2] || dimension.queries[0]} 案例`
  ];
}

function extractBochaResults(payload) {
  const candidates = [
    payload?.data?.webPages?.value,
    payload?.data?.webPages,
    payload?.webPages?.value,
    payload?.webPages,
    payload?.data?.results,
    payload?.results,
    payload?.data
  ];
  const list = candidates.find((entry) => Array.isArray(entry)) || [];
  return list
    .map((item, index) => {
      const title = item.title || item.name || item.headline || "";
      const url = item.url || item.link || item.sourceUrl || "";
      const site = item.siteName || item.site || item.host || "";
      const summary =
        item.summary ||
        item.snippet ||
        item.description ||
        item.content ||
        item.text ||
        "";
      const date = item.dateLastCrawled || item.publishTime || item.date || "";
      return {
        id: url ? `src-${index}` : "",
        title,
        url,
        site,
        summary,
        date,
        sourceKind: "搜索摘要"
      };
    })
    .filter((item) => item.title || item.url || item.summary);
}

function scoreEvidence(result, keywords) {
  const text = `${result.title} ${result.summary} ${result.site}`;
  return keywords.reduce((score, keyword) => {
    return score + (text.includes(keyword) ? 1 : 0);
  }, 0);
}

function assignToDimension(result) {
  let best = DIMENSIONS[0];
  let bestScore = -1;
  for (const dimension of DIMENSIONS) {
    const score = scoreEvidence(result, dimension.keywords);
    if (score > bestScore) {
      best = dimension;
      bestScore = score;
    }
  }
  return { dimension: best.key, score: bestScore };
}

function todayString() {
  const now = new Date();
  const pad = (num) => String(num).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function truncate(text, max = 140) {
  const clean = (text || "").replace(/\s+/g, " ").trim();
  return clean.length > max ? `${clean.slice(0, max)}...` : clean;
}

async function searchBocha(query, options = {}) {
  const apiKey = process.env.BOCHA_API_KEY || DEFAULT_API_KEY;
  const count = options.count || 10;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 25000);
  try {
    const response = await fetch(BOCHA_ENDPOINT, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        query,
        summary: true,
        count
      }),
      signal: controller.signal
    });
    const payload = await response.json();
    return {
      ok: response.ok && !!payload,
      results: extractBochaResults(payload),
      raw: payload,
      status: response.status
    };
  } catch (error) {
    return {
      ok: false,
      results: [],
      raw: null,
      status: 0,
      error: error.message
    };
  } finally {
    clearTimeout(timeout);
  }
}

function computeCoverage(evidenceByDimension, totalSources) {
  const coverage = DIMENSIONS.map((d) => {
    const items = evidenceByDimension[d.key] || [];
    return {
      key: d.key,
      label: d.label,
      count: items.length,
      covered: items.length >= 2
    };
  });
  const sourceFactor = totalSources < 6 ? 0.55 : totalSources < 12 ? 0.8 : 1;
  const dimensionFactor =
    coverage.filter((c) => c.covered).length / Math.max(1, DIMENSIONS.length);
  const score = Math.min(
    100,
    Math.round((dimensionFactor * 70 + sourceFactor * 30) * 100) / 100
  );
  if (score >= 75) return { level: "高", score };
  if (score >= 50) return { level: "中", score };
  return { level: "低", score };
}

async function runResearch(topic) {
  const startedAt = new Date();
  const queries = buildQueries(topic);
  const allSources = [];
  const rounds = [];

  async function executeRound(queryList, roundNo) {
    const roundKeywords = queryList.map((item) => item.query);
    const pageResults = [];

    const settled = await Promise.allSettled(
      queryList.map((item) => searchBocha(item.query, { count: 10 }))
    );

    settled.forEach((item, index) => {
      const value = item.value || {};
      const results = value.ok ? value.results : [];
      const shortQuery = queryList[index].query;
      const dimension = queryList[index].dimension;
      results.forEach((page) => {
        page.matchedQuery = shortQuery;
        page.dimension = dimension;
        pageResults.push(page);
      });
    });

    rounds.push({
      round: roundNo,
      keywords: roundKeywords,
      results_count: pageResults.length,
      pages: pageResults.map((page) => ({
        title: truncate(page.title, 90),
        url: page.url,
        summary: truncate(page.summary, 120),
        dimension: page.dimension
      })),
      failed_queries:
        queryList.length -
        settled.filter((r) => r.status === "fulfilled" && r.value?.ok).length
    });

    return pageResults;
  }

  const firstRoundPages = await executeRound(queries, 1);
  allSources.push(...firstRoundPages);

  const evidenceByDimension = {};
  allSources.forEach((page) => {
    const key = page.dimension || assignToDimension(page).dimension;
    page.dimension = key;
    if (!evidenceByDimension[key]) evidenceByDimension[key] = [];
    evidenceByDimension[key].push(page);
  });

  const gaps = DIMENSIONS.filter(
    (d) => (evidenceByDimension[d.key] || []).length < 2
  );
  const supplementaryQueries = [];
  gaps.forEach((d) => {
    buildGapQueries(topic, d).forEach((query) => {
      supplementaryQueries.push({ query, dimension: d.key });
    });
  });

  let supplementalRoundPages = [];
  if (supplementaryQueries.length && rounds.length < 3) {
    supplementalRoundPages = await executeRound(
      supplementaryQueries.slice(0, 8),
      2
    );
    allSources.push(...supplementalRoundPages);
    supplementalRoundPages.forEach((page) => {
      const key = page.dimension || assignToDimension(page).dimension;
      page.dimension = key;
      if (!evidenceByDimension[key]) evidenceByDimension[key] = [];
      evidenceByDimension[key].push(page);
    });
  }

  const uniqueSources = dedupeSources(allSources).map((source, index) => ({
    ...source,
    _index: index + 1
  }));
  const totalReads = uniqueSources.length;
  const sourceByUrl = new Map(uniqueSources.map((src) => [src.url, src]));

  const coverage = computeCoverage(evidenceByDimension, uniqueSources.length);
  const cutoffDate = todayString();
  const sections = buildSections(evidenceByDimension, sourceByUrl);
  const openQuestions = buildOpenQuestions(evidenceByDimension, coverage);
  const conclusions = buildConclusions(sections, uniqueSources);

  const summaryText = buildSummary(
    topic,
    uniqueSources,
    sections,
    coverage,
    cutoffDate
  );
  const generatedAt = startedAt.toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour12: false
  });

  return {
    topic,
    generatedAt,
    cutoffDate,
    summary: summaryText,
    sections,
    conclusions,
    openQuestions,
    confidence: {
      level: coverage.level,
      score: coverage.score,
      explanation: buildConfidenceExplanation(
        coverage,
        uniqueSources.length,
        cutoffDate
      )
    },
    sources: uniqueSources.map((source) => ({
      title: source.title,
      url: source.url,
      site: source.site || "未知来源",
      summary: truncate(source.summary, 160),
      matchedQuery: source.matchedQuery || source.query || ""
    })),
    process: {
      iterations: rounds.length,
      totalKeywords: rounds.reduce((sum, r) => sum + r.keywords.length, 0),
      totalReads,
      rounds
    }
  };
}

function dedupeSources(sources) {
  const map = new Map();
  sources.forEach((source) => {
    if (!source.url) return;
    if (!map.has(source.url)) {
      map.set(source.url, source);
      return;
    }
    const existing = map.get(source.url);
    if (source.summary.length > (existing.summary || "").length) {
      map.set(source.url, source);
    }
  });
  return Array.from(map.values());
}

function buildSections(evidenceByDimension, sourceByUrl) {
  return DIMENSIONS.map((dimension) => {
    const evidence = (evidenceByDimension[dimension.key] || [])
      .slice()
      .sort((a, b) => (b.summary || "").length - (a.summary || "").length)
      .slice(0, 5);

    const body = evidence.length
      ? evidence
          .map((item, index) => {
            return `${item.title || "未命名来源"}：${truncate(
              item.summary,
              260
            )} [来源 ${sourceIndex(item.url, sourceByUrl) || index + 1}]`;
          })
          .join(" ")
      : "这一方向暂未从公开检索结果中获得足够直接材料，以下内容属于模型推断，需要进一步验证。";

    return {
      key: dimension.key,
      label: dimension.label,
      body,
      evidence: evidence.map((item) => ({
        title: item.title,
        url: item.url,
        site: item.site,
        summary: truncate(item.summary, 200),
        matchedQuery: item.matchedQuery
      })),
      source_count: evidence.length
    };
  });
}

function sourceIndex(url, sourceByUrl) {
  const src = sourceByUrl.get(url);
  return src ? src._index || src.index || src.id : null;
}

function buildConclusions(sections) {
  const conclusions = [];
  sections.forEach((section) => {
    const evidence = section.evidence;
    if (!evidence.length) return;
    const refs = evidence.slice(0, 3).map((e) => ({
      title: e.title,
      url: e.url,
      site: e.site
    }));
    const confidence =
      evidence.length >= 3 ? "高" : evidence.length >= 2 ? "中" : "低";
    const text = `${section.label}方面，多份检索材料显示：${truncate(
      evidence[0].summary,
      120
    )}`;
    conclusions.push({
      text,
      confidence,
      model_inference: false,
      source_count: evidence.length,
      sources: refs
    });
  });
  conclusions.push({
    text: "对于缺少直接来源或相互矛盾的部分，本报告将其标注为模型推断，并建议通过阅读原文、联系行业专家或定制数据源进一步核验。",
    confidence: "低",
    model_inference: true,
    source_count: 0,
    sources: []
  });
  return conclusions.slice(0, 8);
}

function buildOpenQuestions(evidenceByDimension, coverage) {
  const missing = DIMENSIONS.filter(
    (d) => (evidenceByDimension[d.key] || []).length < 2
  );
  return missing
    .map(
      (d) => `${d.label}方面的公开信息不够充分，需要补充一手数据或增加定向检索。`
    )
    .concat(
      coverage.level === "低"
        ? ["整体检索覆盖度较低，建议换个检索词、增加时间范围或使用行业数据库复核。"]
        : []
    );
}

function buildSummary(topic, sources, sections, coverage, cutoffDate) {
  const counts = sections.map((s) => s.source_count);
  const wellCovered = counts.filter((c) => c >= 2).length;
  return `本报告围绕“${topic}”完成 ${counts.length} 个研究方向的检索与整理，共收录 ${sources.length} 条可追溯来源，其中 ${wellCovered} 个方向有较多材料支撑。整体置信度为${coverage.level}。信息截止时间为 ${cutoffDate}，数据来自公开网络检索摘要。`;
}

function buildConfidenceExplanation(coverage, sourceCount, cutoffDate) {
  return `根据来源数量和方向覆盖情况，综合置信度为 ${coverage.level}（评分 ${coverage.score}）。共 ${sourceCount} 条独立来源。信息截止时间：${cutoffDate}。未拉取全文的页面仅依赖检索摘要；缺少来源支持的结论已标注为模型推断。`;
}

module.exports = { runResearch };

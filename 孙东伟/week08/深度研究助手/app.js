const topicInput = document.getElementById("topic-input");
const runButton = document.getElementById("run-button");
const progressText = document.getElementById("progress-text");
const systemStatus = document.getElementById("system-status");
const reportArea = document.getElementById("report-area");
const reportMeta = document.getElementById("report-meta");
const summaryBox = document.getElementById("summary-box");
const sectionsBox = document.getElementById("sections-box");
const conclusionsBox = document.getElementById("conclusions-box");
const questionsBox = document.getElementById("questions-box");
const confidenceBox = document.getElementById("confidence-box");
const sourcesBox = document.getElementById("sources-box");
const processBox = document.getElementById("process-box");
const emptyState = document.getElementById("empty-state");
const downloadJson = document.getElementById("download-json");
const downloadMarkdown = document.getElementById("download-markdown");

let currentReport = null;

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function cleanFileName(value) {
  return String(value || "报告").replace(/[\\/:*?"<>|\\s]+/g, "_").slice(0, 40);
}

function downloadText(filename, text, type = "text/plain") {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function renderMeta(report) {
  reportMeta.innerHTML = [
    `<span><strong>主题</strong> ${escapeHtml(report.topic)}</span>`,
    `<span><strong>生成时间</strong> ${escapeHtml(report.generatedAt)}</span>`,
    `<span><strong>信息截止</strong> ${escapeHtml(report.cutoffDate)}</span>`,
    `<span><strong>置信度</strong> ${escapeHtml(report.confidence.level)} (${escapeHtml(report.confidence.score)})</span>`
  ].join("");
}

function renderSections(report) {
  sectionsBox.innerHTML = report.sections
    .map(
      (section) => `
        <article class="section-card">
          <header>
            <h3>${escapeHtml(section.label)}</h3>
            <span class="count-badge">${section.source_count} 条来源</span>
          </header>
          <p>${escapeHtml(section.body)}</p>
          ${section.evidence.length ? `<ul class="evidence-list">${section.evidence.map((item) => `<li><a href="${escapeHtml(item.url)}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a><div class="evidence-meta">${escapeHtml(item.site || "未知来源")} · ${escapeHtml(item.matchedQuery || "")}</div><div>${escapeHtml(item.summary)}</div></li>`).join("")}</ul>` : ""}
        </article>
      `
    )
    .join("");
}

function renderConclusions(report) {
  conclusionsBox.innerHTML = `
    <h2>关键结论</h2>
    ${report.conclusions
      .map(
        (item) => `
          <div class="conclusion-item">
            <div>${escapeHtml(item.text)}<span class="confidence-tag${item.model_inference ? " model-tag" : ""}">${escapeHtml(item.confidence)}${item.model_inference ? " · 模型推断" : ""}</span></div>
            ${item.sources.length ? `<div class="evidence-meta">${item.sources.map((s) => `<a href="${escapeHtml(s.url)}" target="_blank" rel="noopener">${escapeHtml(s.site || s.title)}</a>`).join(" · ")}</div>` : ""}
          </div>
        `
      )
      .join("")}
  `;
}

function renderQuestions(report) {
  questionsBox.innerHTML = `
    <h2>遗留问题</h2>
    <ul class="question-list">${report.openQuestions.map((q) => `<li>${escapeHtml(q)}</li>`).join("")}</ul>
  `;
}

function renderConfidence(report) {
  confidenceBox.innerHTML = `
    <h2>置信度说明</h2>
    <p>${escapeHtml(report.confidence.explanation)}</p>
  `;
}

function renderSources(report) {
  sourcesBox.innerHTML = `
    <h2>来源列表</h2>
    <table class="source-table">
      <thead>
        <tr>
          <th>#</th>
          <th>标题 / 链接</th>
          <th>来源</th>
          <th>摘要</th>
        </tr>
      </thead>
      <tbody>
        ${report.sources
          .map(
            (s, index) => `
              <tr>
                <td>${index + 1}</td>
                <td><a href="${escapeHtml(s.url)}" target="_blank" rel="noopener">${escapeHtml(s.title || s.url)}</a></td>
                <td>${escapeHtml(s.site)}</td>
                <td>${escapeHtml(s.summary)}</td>
              </tr>
            `
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function renderProcess(report) {
  const process = report.process;
  processBox.innerHTML = `
    <h2>研究过程记录</h2>
    <p class="evidence-meta">迭代 ${process.iterations} 轮 · 检索关键词 ${process.totalKeywords} 个 · 收录页面 ${process.totalReads} 条</p>
    ${process.rounds
      .map(
        (round) => `
          <div class="round-item">
            <strong>第 ${round.round} 轮</strong> · ${round.keywords.length} 个关键词 · 命中 ${round.results_count} 条${round.failed_queries ? ` · ${round.failed_queries} 个查询失败` : ""}
            <ul class="keyword-list">${round.keywords.map((k) => `<li><span>${escapeHtml(k)}</span></li>`).join("")}</ul>
          </div>
        `
      )
      .join("")}
  `;
}

function renderReport(report) {
  currentReport = report;
  reportArea.hidden = false;
  emptyState.hidden = true;
  renderMeta(report);
  summaryBox.innerHTML = `<h2>摘要</h2><p>${escapeHtml(report.summary)}</p>`;
  renderSections(report);
  renderConclusions(report);
  renderQuestions(report);
  renderConfidence(report);
  renderSources(report);
  renderProcess(report);
}

function renderError(message) {
  currentReport = null;
  reportArea.hidden = false;
  emptyState.hidden = true;
  summaryBox.innerHTML = `<h2>研究失败</h2><p>${escapeHtml(message)}</p>`;
  reportMeta.innerHTML = "";
  sectionsBox.innerHTML = "";
  conclusionsBox.innerHTML = "";
  questionsBox.innerHTML = "";
  confidenceBox.innerHTML = "";
  sourcesBox.innerHTML = "";
  processBox.innerHTML = "";
}

async function startResearch() {
  const topic = topicInput.value.trim();
  if (!topic) {
    topicInput.focus();
    return;
  }
  runButton.disabled = true;
  systemStatus.textContent = "研究进行中";
  systemStatus.classList.add("running");
  progressText.textContent = "正在规划检索关键词并启动多轮调研...";

  try {
    const response = await fetch("/api/research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic })
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || payload.detail || "未知错误");
    }
    progressText.textContent = `完成，生成报告用时约若干轮。`;
    renderReport(payload);
  } catch (error) {
    progressText.textContent = "研究失败";
    renderError(error.message || String(error));
  } finally {
    systemStatus.textContent = "完成";
    systemStatus.classList.remove("running");
    runButton.disabled = false;
  }
}

function toMarkdown(report) {
  const lines = [];
  lines.push(`# 深度研究：${report.topic}`);
  lines.push("");
  lines.push(`- 生成时间：${report.generatedAt}`);
  lines.push(`- 信息截止：${report.cutoffDate}`);
  lines.push(`- 置信度：${report.confidence.level}（评分 ${report.confidence.score}）`);
  lines.push("");
  lines.push("## 摘要");
  lines.push(report.summary);
  lines.push("");
  report.sections.forEach((section) => {
    lines.push(`## ${section.label}`);
    lines.push(section.body);
    lines.push("");
    section.evidence.forEach((item) => {
      lines.push(`- [${item.title}](${item.url}) — ${item.site}｜${item.summary}`);
    });
    lines.push("");
  });
  lines.push("## 关键结论");
  report.conclusions.forEach((item, index) => {
    lines.push(`${index + 1}. ${item.text}（${item.confidence}${item.model_inference ? " · 模型推断" : ""}）${item.sources.length ? `来源：${item.sources.map((s) => `[${s.title}](${s.url})`).join("、")}` : ""}`);
  });
  lines.push("");
  lines.push("## 遗留问题");
  report.openQuestions.forEach((q) => lines.push(`- ${q}`));
  lines.push("");
  lines.push("## 置信度说明");
  lines.push(report.confidence.explanation);
  lines.push("");
  lines.push("## 来源列表");
  report.sources.forEach((source, index) => {
    lines.push(`${index + 1}. [${source.title}](${source.url}) — ${source.site}`);
  });
  lines.push("");
  lines.push("## 研究过程记录");
  lines.push(`迭代 ${report.process.iterations} 轮 · 检索关键词 ${report.process.totalKeywords} 个 · 收录页面 ${report.process.totalReads} 条`);
  report.process.rounds.forEach((round) => {
    lines.push(`第 ${round.round} 轮：${round.keywords.join("；")}，命中 ${round.results_count} 条`);
  });
  return lines.join("\n");
}

runButton.addEventListener("click", startResearch);

downloadJson.addEventListener("click", () => {
  if (currentReport) {
    downloadText(`${cleanFileName(currentReport.topic)}.json`, JSON.stringify(currentReport, null, 2), "application/json");
  }
});

downloadMarkdown.addEventListener("click", () => {
  if (currentReport) {
    downloadText(`${cleanFileName(currentReport.topic)}.md`, toMarkdown(currentReport), "text/markdown");
  }
});

topicInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
    startResearch();
  }
});

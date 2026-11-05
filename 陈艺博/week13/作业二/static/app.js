/* =====================================================================
   Chinook 数据问答 · 前端逻辑
   1. 调用 /api/health 展示服务状态；
   2. 用 fetch + ReadableStream 消费 SSE，实时展示 LangGraph 阶段；
   3. 把最终 ChatResponse 渲染成答案、结果表、SQL、依据与执行轨迹。
   ===================================================================== */

(function () {
  "use strict";

  /* --------------------------------------------------------------- DOM */

  const el = {
    chatScroll: document.getElementById("chatScroll"),
    messages: document.getElementById("messages"),
    welcome: document.getElementById("welcome"),
    input: document.getElementById("input"),
    sendBtn: document.getElementById("sendBtn"),
    resetBtn: document.getElementById("resetBtn"),
    modePill: document.getElementById("modePill"),
    modeText: document.getElementById("modeText"),
    dbName: document.getElementById("dbName"),
    modelName: document.getElementById("modelName"),
    serverState: document.getElementById("serverState"),
  };

  const state = {
    history: [],       // [{role, content}]，只保存问答正文
    busy: false,
    abort: null,
    timer: null,
    startedAt: 0,
    requestSeq: 0,
    scrollFrame: null,
  };

  const SQL_KEYWORDS =
    "SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|FULL|CROSS|ON|USING|" +
    "GROUP|BY|ORDER|HAVING|LIMIT|OFFSET|AS|AND|OR|NOT|IN|IS|NULL|" +
    "COUNT|SUM|AVG|MIN|MAX|ROUND|DISTINCT|WITH|UNION|ALL|CASE|WHEN|THEN|" +
    "ELSE|END|DESC|ASC|LIKE|GLOB|BETWEEN|COALESCE|IFNULL|CAST|" +
    "INTEGER|TEXT|REAL|NUMERIC|OVER|PARTITION|NULLS|FIRST|LAST|" +
    "EXISTS|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE";

  /* --------------------------------------------------------------- 工具 */

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => {
      switch (ch) {
        case "&": return "&amp;";
        case "<": return "&lt;";
        case ">": return "&gt;";
        case '"': return "&quot;";
        case "'": return "&#39;";
        default: return ch;
      }
    });
  }

  function truncate(text, limit) {
    const value = String(text == null ? "" : text);
    return value.length <= limit ? value : value.slice(0, limit) + "…";
  }

  function formatElapsed(ms) {
    const value = Number(ms);
    if (!Number.isFinite(value) || value < 0) return "";
    if (value < 1000) return Math.round(value) + " ms";
    const seconds = value / 1000;
    return (seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)) + " s";
  }

  function formatRich(text) {
    let html = escapeHtml(text);
    html = html.replace(/(^|\n)[ \t]*[-•][ \t]+/g, "$1• ");
    html = html.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    html = html.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\n/g, "<br>");
    return html;
  }

  function highlightSql(sql) {
    const pattern = new RegExp(
      "('(?:[^']|'')*')" +          // 字符串
      "|(--[^\\n]*)" +              // 行注释
      "|(\\b\\d+(?:\\.\\d+)?\\b)" + // 数字
      "|\\b(" + SQL_KEYWORDS + ")\\b",
      "gi"
    );
    const source = String(sql || "");
    let out = "";
    let last = 0;
    let match;

    while ((match = pattern.exec(source)) !== null) {
      out += escapeHtml(source.slice(last, match.index));
      if (match[1]) {
        out += '<span class="tok-str">' + escapeHtml(match[1]) + "</span>";
      } else if (match[2]) {
        out += '<span class="tok-com">' + escapeHtml(match[2]) + "</span>";
      } else if (match[3]) {
        out += '<span class="tok-num">' + escapeHtml(match[3]) + "</span>";
      } else {
        out += '<span class="tok-kw">' + escapeHtml(match[0]) + "</span>";
      }
      last = pattern.lastIndex;
    }
    out += escapeHtml(source.slice(last));
    return out;
  }

  function isNumeric(value) {
    const text = String(value == null ? "" : value).trim();
    return text.length > 0 && text.length < 24 && /^-?\d+(?:\.\d+)?$/.test(text);
  }

  const botIcon =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
    '<ellipse cx="12" cy="6" rx="5.5" ry="2.3"/>' +
    '<path d="M6.5 6v5.6c0 1.27 2.46 2.3 5.5 2.3s5.5-1.03 5.5-2.3V6"/>' +
    '<path d="M6.5 11.6V17c0 1.27 2.46 2.3 5.5 2.3 1 0 1.93-.1 2.74-.28"/>' +
    "</svg>";

  /* --------------------------------------------------------------- 滚动 */

  function nearBottom() {
    const node = el.chatScroll;
    return node.scrollHeight - node.scrollTop - node.clientHeight < 180;
  }

  function cancelScheduledScroll() {
    if (state.scrollFrame) {
      window.cancelAnimationFrame(state.scrollFrame);
      state.scrollFrame = null;
    }
  }

  function scrollToBottom(force) {
    if (!force && !nearBottom()) return;
    cancelScheduledScroll();
    state.scrollFrame = window.requestAnimationFrame(() => {
      state.scrollFrame = null;
      el.chatScroll.scrollTop = el.chatScroll.scrollHeight;
    });
  }

  function revealAssistant(asst) {
    if (!asst || !asst.article.isConnected) return;
    const scroller = el.chatScroll;
    const cardHeight = asst.card.getBoundingClientRect().height;

    // 取消上一阶段排队中的「滚到底」，否则会覆盖本次定位。
    cancelScheduledScroll();

    // 长答案从卡片顶部开始读；短答案直接滚到底，保持聊天感。
    if (cardHeight > scroller.clientHeight * 0.72) {
      const articleTop = asst.article.getBoundingClientRect().top;
      const scrollerTop = scroller.getBoundingClientRect().top;
      const target = scroller.scrollTop + articleTop - scrollerTop - 14;
      scroller.scrollTo({ top: Math.max(0, target), behavior: "smooth" });
    } else {
      scrollToBottom(true);
    }
  }

  /* --------------------------------------------------------------- 计时 */

  function startTimer(target) {
    stopTimer();
    state.startedAt = performance.now();
    if (target) target.textContent = "0.0s";
    state.timer = window.setInterval(() => {
      if (!target) return;
      const seconds = (performance.now() - state.startedAt) / 1000;
      target.textContent = seconds.toFixed(1) + "s";
    }, 100);
  }

  function stopTimer() {
    if (state.timer) {
      window.clearInterval(state.timer);
      state.timer = null;
    }
  }

  /* --------------------------------------------------------------- 消息 */

  function hideWelcome() {
    if (el.welcome && !el.welcome.hidden) {
      el.welcome.hidden = true;
    }
  }

  function createMessage(role) {
    const article = document.createElement("article");
    article.className = "msg msg-" + role;

    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.setAttribute("aria-hidden", "true");
    if (role === "assistant") {
      avatar.innerHTML = botIcon;
    } else {
      avatar.textContent = "你";
    }

    const body = document.createElement("div");
    body.className = "msg-body";

    article.append(avatar, body);
    el.messages.append(article);
    scrollToBottom(true);
    return { article, body };
  }

  function appendUser(text) {
    const { body } = createMessage("user");
    const bubble = document.createElement("div");
    bubble.className = "user-bubble";
    bubble.innerHTML = formatRich(text);
    body.append(bubble);
  }

  function appendAssistantLoading() {
    const { article, body } = createMessage("assistant");
    const card = document.createElement("div");
    card.className = "answer-card loading-card";
    card.innerHTML =
      '<div class="thinking-head">' +
      '  <span class="pulse-dots" aria-hidden="true"><i></i><i></i><i></i></span>' +
      '  <span class="thinking-title">正在分析问题</span>' +
      '  <span class="thinking-timer">0.0s</span>' +
      "</div>" +
      '<ul class="stage-list" aria-label="执行阶段">' +
      '  <li class="stage-placeholder">正在连接 Agent…</li>' +
      "</ul>";
    body.append(card);

    const timerEl = card.querySelector(".thinking-timer");
    startTimer(timerEl);

    return {
      article,
      card,
      stageList: card.querySelector(".stage-list"),
      finished: false,
    };
  }

  function addStage(asst, event) {
    if (!asst || asst.finished || !asst.article.isConnected) return;
    const list = asst.stageList;
    if (!list) return;

    const placeholder = list.querySelector(".stage-placeholder");
    if (placeholder) placeholder.remove();

    const status = event.status || "ok";
    const label = event.label || event.node || "执行";
    const detail = String(event.detail || "").trim();
    const isSql = /sql/i.test(String(event.node || "")) && detail;

    const item = document.createElement("li");
    item.className = "stage-item status-" + status;
    item.innerHTML =
      '<span class="stage-dot" aria-hidden="true"></span>' +
      '<span class="stage-main">' +
      '  <span class="stage-label">' + escapeHtml(label) + "</span>" +
      (detail
        ? '<span class="stage-detail' + (isSql ? " mono" : "") + '">' +
          escapeHtml(truncate(detail, 220)) +
          "</span>"
        : "") +
      "</span>" +
      '<span class="stage-ms">' +
      (event.elapsed_ms != null ? escapeHtml(formatElapsed(event.elapsed_ms)) : "") +
      "</span>";

    list.append(item);
    list.scrollTop = list.scrollHeight;

    const title = asst.card.querySelector(".thinking-title");
    if (title) title.textContent = "正在执行：" + label;
    scrollToBottom();
  }

  function finalizeAssistant(asst, response) {
    if (!asst || asst.finished) return;
    asst.finished = true;
    stopTimer();

    if (!asst.article.isConnected) return;

    const data = response && typeof response === "object" ? response : {};
    asst.card.classList.remove("loading-card");
    asst.card.classList.toggle("failed-card", data.ok === false);
    asst.card.innerHTML = renderResponse(data);

    state.history.push({
      role: "assistant",
      content: truncate(String(data.answer || "（无回答）"), 4000),
    });
    revealAssistant(asst);
  }

  function failAssistant(asst, message) {
    const elapsed = state.startedAt
      ? Math.round(performance.now() - state.startedAt)
      : 0;
    finalizeAssistant(asst, {
      ok: false,
      answer: message,
      error: message,
      events: [],
      elapsed_ms: elapsed,
    });
  }

  function stopAssistant(asst) {
    if (!asst || asst.finished) return;
    asst.finished = true;
    stopTimer();
    if (!asst.article.isConnected) return;

    const elapsed = state.startedAt
      ? Math.round(performance.now() - state.startedAt)
      : 0;
    const stages = asst.stageList ? asst.stageList.innerHTML : "";
    const hasStages = stages && !stages.includes("stage-placeholder");

    asst.card.classList.remove("loading-card");
    asst.card.innerHTML =
      '<div class="stopped-box">' +
      '  <span class="stopped-icon" aria-hidden="true">■</span>' +
      "  <div><b>已停止本次查询</b><p>可以换个问法，或重新发送。</p></div>" +
      '  <span class="elapsed">' + escapeHtml(formatElapsed(elapsed)) + "</span>" +
      "</div>" +
      (hasStages
        ? '<details class="timeline"><summary>已完成的步骤</summary>' +
          '<ol class="timeline-list">' + stages + "</ol></details>"
        : "");

    state.history.push({ role: "assistant", content: "（本次查询被用户停止）" });
    scrollToBottom();
  }

  /* --------------------------------------------------------------- 渲染 */

  function renderResponse(data) {
    const ok = data.ok !== false;
    const answer = String(data.answer || (ok ? "查询完成。" : "处理失败。"));
    const tables = Array.isArray(data.tables) ? data.tables : [];
    const evidence = Array.isArray(data.evidence) ? data.evidence : [];
    const caveats = Array.isArray(data.caveats) ? data.caveats : [];
    const events = Array.isArray(data.events) ? data.events : [];
    const columns = Array.isArray(data.columns) ? data.columns : [];
    const rows = Array.isArray(data.rows) ? data.rows : [];
    const repair = Number(data.repair_attempts) || 0;
    const rowCount = Number(data.row_count) || 0;

    const parts = [];

    parts.push(
      '<div class="answer-head">' +
      '  <span class="agent-badge">' + botIcon + "SQL Agent</span>" +
      '  <span class="status-chip ' + (ok ? "ok" : "error") + '">' +
      (ok ? "已完成" : "未完成") +
      "</span>" +
      (data.elapsed_ms != null
        ? '<span class="elapsed">' + escapeHtml(formatElapsed(data.elapsed_ms)) + "</span>"
        : "") +
      "</div>"
    );

    parts.push('<div class="answer-text">' + formatRich(answer) + "</div>");

    if (data.standalone_question) {
      parts.push(
        '<div class="rewrite-note" title="' +
        escapeHtml(data.followup_reason || "") + '">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<path d="M4 11a8 8 0 1 1 2.3 5.7"/><path d="M4 4v7h7"/></svg>' +
        "<span><b>结合上下文改写为：</b>" +
        escapeHtml(data.standalone_question) +
        "</span></div>"
      );
    }

    const chips = [];
    if (ok || tables.length) {
      if (tables.length) {
        chips.push(
          '<span class="chip"><b>tables</b>' +
          escapeHtml(tables.join(" · ")) +
          "</span>"
        );
      }
      chips.push(
        '<span class="chip"><b>rows</b>' +
        escapeHtml(String(rowCount)) +
        (data.truncated ? " +" : "") +
        "</span>"
      );
    }
    if (repair > 0) {
      chips.push('<span class="chip warn"><b>repair</b>自动修复 ' + repair + " 次</span>");
    }
    if (chips.length) {
      parts.push('<div class="meta-chips">' + chips.join("") + "</div>");
    }

    parts.push(renderTable(columns, rows, rowCount, Boolean(data.truncated)));
    parts.push(renderSql(data.sql));
    parts.push(renderInfoList("判断依据", evidence, "evidence"));
    parts.push(renderInfoList("注意事项", caveats, "caveat"));

    if (!ok && data.error) {
      parts.push(
        '<div class="error-box">' +
        '<span class="error-icon" aria-hidden="true">!</span>' +
        '<span class="error-label">技术细节</span>' +
        '<span class="error-text">' + escapeHtml(data.error) + "</span>" +
        "</div>"
      );
    }

    parts.push(renderTimeline(events, repair, !ok));

    return parts.filter(Boolean).join("");
  }

  function renderTable(columns, rows, rowCount, truncated) {
    if (!columns.length) return "";

    const head =
      '<div class="table-head">' +
      "<h3>查询结果</h3>" +
      '<span class="table-count">' + rows.length + " 行" +
      (rowCount && rowCount !== rows.length ? " / 共 " + rowCount + " 行" : "") +
      "</span>" +
      (truncated ? '<span class="trunc-badge">已截断</span>' : "") +
      "</div>";

    if (!rows.length) {
      return (
        '<div class="table-card">' + head +
        '<div class="table-empty">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M4 7h16v13H4z"/><path d="M4 11h16"/><path d="M9 7V4h6v3"/>' +
        "</svg>" +
        "<b>查询成功，但没有返回数据</b>" +
        "<span>可以换一个时间范围或筛选条件再问。</span>" +
        "</div></div>"
      );
    }

    const numericCols = columns.map((_, index) => {
      let hasValue = false;
      const allNumeric = rows.every((row) => {
        const value = Array.isArray(row) ? row[index] : undefined;
        const text = String(value == null ? "" : value).trim();
        if (!text) return true;
        hasValue = true;
        return isNumeric(text);
      });
      return hasValue && allNumeric;
    });

    const headCells = columns
      .map(
        (name, index) =>
          '<th class="' + (numericCols[index] ? "num" : "") + '">' +
          escapeHtml(name) +
          "</th>"
      )
      .join("");

    const bodyRows = rows
      .map((row) => {
        const cells = (Array.isArray(row) ? row : [row])
          .map((cell) => {
            const text = String(cell == null ? "" : cell);
            return (
              '<td class="' + (isNumeric(text) ? "num" : "") + '">' +
              escapeHtml(text) +
              "</td>"
            );
          })
          .join("");
        return "<tr>" + cells + "</tr>";
      })
      .join("");

    return (
      '<div class="table-card">' + head +
      '<div class="table-scroll"><table>' +
      "<thead><tr>" + headCells + "</tr></thead>" +
      "<tbody>" + bodyRows + "</tbody>" +
      "</table></div></div>"
    );
  }

  function renderSql(sql) {
    if (!sql) return "";
    return (
      '<div class="sql-card">' +
      '<div class="sql-head">' +
      '<span class="sql-dot" aria-hidden="true"></span>' +
      "<span>EXECUTED SQL</span>" +
      '<button type="button" class="copy-btn" data-copy-sql>复制</button>' +
      "</div>" +
      "<pre><code>" + highlightSql(sql) + "</code></pre>" +
      "</div>"
    );
  }

  function renderInfoList(title, items, kind) {
    if (!Array.isArray(items) || !items.length) return "";
    const lis = items
      .map((item) => "<li>" + formatRich(item) + "</li>")
      .join("");
    return (
      '<div class="info-block ' + kind + '">' +
      "<h3>" + escapeHtml(title) + "</h3>" +
      "<ul>" + lis + "</ul>" +
      "</div>"
    );
  }

  function renderTimeline(events, repair, failed) {
    if (!events.length) return "";
    // 单个错误事件已经在 error-box 里展示，不再重复一遍“处理失败”。
    if (events.length === 1 && repair === 0) return "";
    const items = events
      .map((event) => {
        const status = event.status || "ok";
        const label = event.label || event.node || "执行";
        const detail = String(event.detail || "").trim();
        const isSql = /sql/i.test(String(event.node || "")) && detail;
        return (
          '<li class="stage-item status-' + escapeHtml(status) + '">' +
          '<span class="stage-dot" aria-hidden="true"></span>' +
          '<span class="stage-main">' +
          '<span class="stage-label">' + escapeHtml(label) + "</span>" +
          (detail
            ? '<span class="stage-detail' + (isSql ? " mono" : "") + '">' +
              escapeHtml(truncate(detail, 260)) +
              "</span>"
            : "") +
          "</span>" +
          '<span class="stage-ms">' +
          (event.elapsed_ms != null ? escapeHtml(formatElapsed(event.elapsed_ms)) : "") +
          "</span></li>"
        );
      })
      .join("");

    const open = repair > 0 || failed ? " open" : "";
    const summary =
      "执行轨迹 · " + events.length + " 步" +
      (repair > 0 ? " · 自动修复 " + repair + " 次" : "");

    return (
      '<details class="timeline"' + open + ">" +
      "<summary>" + escapeHtml(summary) + "</summary>" +
      '<ol class="timeline-list">' + items + "</ol>" +
      "</details>"
    );
  }

  /* --------------------------------------------------------------- SSE */

  function handleFrame(raw, asst) {
    const lines = String(raw || "").split(/\r?\n/);
    let data = "";
    for (const line of lines) {
      if (line.startsWith("data:")) {
        const chunk = line.slice(5).replace(/^ /, "");
        data += (data ? "\n" : "") + chunk;
      }
    }
    if (!data || data === "[DONE]") return null;

    let payload;
    try {
      payload = JSON.parse(data);
    } catch (error) {
      console.warn("忽略无法解析的 SSE 数据", error);
      return null;
    }

    if (payload.type === "start") return "start";
    if (payload.type === "stage") {
      addStage(asst, payload.event || {});
      return "stage";
    }
    if (payload.type === "final") {
      finalizeAssistant(asst, payload.response || {});
      return "final";
    }
    return null;
  }

  async function readStream(response, asst) {
    if (!response.body) throw new Error("当前浏览器不支持流式响应");

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let sawFinal = false;

    while (true) {
      const result = await reader.read();
      if (result.done) break;
      buffer += decoder.decode(result.value, { stream: true });

      let splitAt;
      while ((splitAt = buffer.search(/\r?\n\r?\n/)) !== -1) {
        const rawFrame = buffer.slice(0, splitAt);
        const rest = buffer.slice(splitAt);
        const separator = rest.match(/^\r?\n\r?\n/);
        buffer = rest.slice(separator ? separator[0].length : 2);
        if (handleFrame(rawFrame, asst) === "final") sawFinal = true;
      }
    }

    buffer += decoder.decode();
    if (buffer.trim() && handleFrame(buffer, asst) === "final") sawFinal = true;

    if (!sawFinal && !asst.finished) {
      failAssistant(asst, "连接提前结束，没有收到最终结果。请重试一次。");
    }
  }

  /* --------------------------------------------------------------- 发送 */

  function setBusy(busy) {
    state.busy = busy;
    el.sendBtn.dataset.busy = busy ? "1" : "0";
    el.sendBtn.setAttribute("aria-label", busy ? "停止本次查询" : "发送问题");
    const label = el.sendBtn.querySelector(".send-label");
    if (label) label.textContent = busy ? "停止" : "发送";
  }

  function autoResize() {
    el.input.style.height = "auto";
    el.input.style.height = Math.min(el.input.scrollHeight, 164) + "px";
  }

  async function sendMessage(raw) {
    const text = String(raw == null ? "" : raw).trim();
    if (!text || state.busy) return;

    const history = state.history.slice(-12);
    state.history.push({ role: "user", content: text });

    el.input.value = "";
    autoResize();
    hideWelcome();
    appendUser(text);

    const asst = appendAssistantLoading();
    const seq = ++state.requestSeq;
    const controller = new AbortController();
    state.abort = controller;
    setBusy(true);

    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify({ message: text, history: history }),
        signal: controller.signal,
      });

      if (!response.ok) {
        let detail = "HTTP " + response.status;
        try {
          const data = await response.json();
          if (data && data.detail) {
            detail = typeof data.detail === "string"
              ? data.detail
              : JSON.stringify(data.detail);
          }
        } catch (ignored) {
          /* 非 JSON 错误响应，保留 HTTP 状态码 */
        }
        throw new Error(detail);
      }

      await readStream(response, asst);
    } catch (error) {
      if (error && error.name === "AbortError") {
        stopAssistant(asst);
      } else if (!asst.finished) {
        console.error(error);
        failAssistant(asst, "请求失败：" + (error && error.message ? error.message : error));
      }
    } finally {
      if (seq === state.requestSeq) {
        stopTimer();
        state.busy = false;
        state.abort = null;
        setBusy(false);
        el.input.focus();
      }
    }
  }

  /* --------------------------------------------------------------- 状态 */

  function applyHealth(health) {
    const demo = Boolean(health.demo_mode);
    let mode = "ok";
    let text = "模型就绪";

    if (demo) {
      mode = "demo";
      text = "离线演示";
    } else if (!health.llm_configured) {
      mode = "warn";
      text = "未配置模型";
    }

    el.modePill.dataset.mode = mode;
    el.modeText.textContent = text;
    el.modePill.title =
      (demo ? "离线演示 · 内置安全 SQL" : health.model || "") +
      (health.db && health.db.name ? " · " + health.db.name : "");

    el.dbName.textContent = health.db && health.db.name ? health.db.name : "chinook.db";
    el.modelName.textContent = demo ? "内置演示逻辑" : health.model || "—";

    const dbOk = health.db && health.db.exists;
    el.serverState.dataset.state = dbOk ? "ok" : "error";
    el.serverState.innerHTML = "<i></i>" + (dbOk ? "已连接" : "数据库缺失");
  }

  async function loadHealth() {
    try {
      const response = await fetch("/api/health", {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error("HTTP " + response.status);
      applyHealth(await response.json());
    } catch (error) {
      console.warn("健康检查失败", error);
      el.modePill.dataset.mode = "error";
      el.modeText.textContent = "服务未连接";
      el.modePill.title = String(error);
      el.serverState.dataset.state = "error";
      el.serverState.innerHTML = "<i></i>未连接";
    }
  }

  /* --------------------------------------------------------------- 复制 */

  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy-sql]");
    if (!button) return;
    event.preventDefault();

    const card = button.closest(".sql-card");
    const code = card ? card.querySelector("code") : null;
    if (!code) return;

    const original = button.textContent;
    try {
      await copyText(code.textContent || "");
      button.textContent = "已复制";
      button.classList.add("copied");
    } catch (error) {
      button.textContent = "复制失败";
    }
    window.setTimeout(() => {
      button.textContent = original;
      button.classList.remove("copied");
    }, 1600);
  });

  /* --------------------------------------------------------------- 重置 */

  function resetChat() {
    if (state.busy && state.abort) state.abort.abort();

    state.requestSeq += 1;
    state.busy = false;
    state.abort = null;
    stopTimer();
    setBusy(false);

    state.history = [];
    el.messages.innerHTML = "";
    el.welcome.hidden = false;
    el.input.value = "";
    autoResize();
    el.chatScroll.scrollTop = 0;
    el.input.focus();
  }

  /* --------------------------------------------------------------- 绑定 */

  el.sendBtn.addEventListener("click", () => {
    if (state.busy) {
      if (state.abort) state.abort.abort();
      return;
    }
    sendMessage(el.input.value);
  });

  el.input.addEventListener("input", autoResize);

  el.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (!state.busy) sendMessage(el.input.value);
    }
  });

  el.resetBtn.addEventListener("click", resetChat);

  document.querySelectorAll("[data-question]").forEach((button) => {
    button.addEventListener("click", () => {
      sendMessage(button.dataset.question || "");
    });
  });

  /* --------------------------------------------------------------- 启动 */

  autoResize();
  loadHealth();
  el.input.focus();
})();

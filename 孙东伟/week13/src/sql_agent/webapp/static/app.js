"use strict";

const chat = document.getElementById("chat");
const welcome = document.getElementById("welcome");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const statusEl = document.getElementById("status");
const statusText = document.getElementById("status-text");
const newChatBtn = document.getElementById("new-chat");

const STATUS = {
  ok: { label: "查询成功", cls: "ok" },
  empty: { label: "无匹配数据", cls: "empty" },
  clarified: { label: "需要澄清", cls: "warn" },
  unsupported: { label: "无法回答", cls: "warn" },
  failed: { label: "执行失败", cls: "error" },
};

let busy = false;

/* ------------------------------------------------------------------ 工具 */

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function scrollToBottom() {
  chat.scrollTop = chat.scrollHeight;
}

function setBusy(value) {
  busy = value;
  sendBtn.disabled = value;
  chat.setAttribute("aria-busy", value ? "true" : "false");
}

function formatElapsed(ms) {
  if (typeof ms !== "number" || Number.isNaN(ms)) return "";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(2)} s`;
}

async function copyText(text, button) {
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = "已复制";
  } catch {
    button.textContent = "复制失败";
  }
  window.setTimeout(() => {
    button.textContent = "复制";
  }, 1600);
}

/* ------------------------------------------------------------------ 消息 */

function hideWelcome() {
  if (welcome && !welcome.classList.contains("hidden")) {
    welcome.classList.add("hidden");
  }
}

function addUserMessage(text) {
  hideWelcome();
  const row = el("div", "msg user");
  row.append(el("div", "bubble", text));
  chat.append(row);
  scrollToBottom();
}

function addAssistantShell() {
  hideWelcome();
  const row = el("div", "msg assistant");
  const card = el("div", "card");
  const body = el("div", "card-body");
  card.append(body);
  row.append(card);
  chat.append(row);
  scrollToBottom();
  return { row, body };
}

function renderPending(body) {
  const typing = el("div", "typing");
  typing.append(el("span"), el("span"), el("span"));
  body.replaceChildren(typing);
}

function renderError(body, message) {
  body.replaceChildren();
  const head = el("div", "card-head");
  head.append(el("span", "pill error", "请求失败"));
  body.append(head);
  body.append(el("p", "answer", message));
  scrollToBottom();
}

/* ------------------------------------------------------------------ 结果 */

function renderHead(data) {
  const head = el("div", "card-head");
  const status = STATUS[data.status] || { label: data.status || "完成", cls: "" };
  head.append(el("span", `pill ${status.cls}`, status.label));

  const meta = el("div", "meta");
  if (Array.isArray(data.tables) && data.tables.length) {
    meta.append(el("span", "", `表 ${data.tables.join("、")}`));
  }
  meta.append(el("span", "", `${data.row_count || 0} 行`));
  if (data.repair_attempts) {
    meta.append(el("span", "", `修复 ${data.repair_attempts} 次`));
  }
  const elapsed = formatElapsed(data.elapsed_ms);
  if (elapsed) meta.append(el("span", "", elapsed));
  head.append(meta);
  return head;
}

function renderSql(data) {
  const section = el("div", "section");
  const head = el("div", "section-head");
  head.append(el("div", "section-title", "SQL"));
  const copy = el("button", "copy", "复制");
  copy.type = "button";
  copy.addEventListener("click", () => copyText(data.sql, copy));
  head.append(copy);
  section.append(head);
  section.append(el("pre", "sql", data.sql));
  return section;
}

function renderTable(data) {
  const section = el("div", "section");
  const head = el("div", "section-head");
  head.append(el("div", "section-title", "执行结果"));
  section.append(head);

  if (!Array.isArray(data.rows) || data.rows.length === 0) {
    section.append(el("div", "empty-rows", "SQL 执行成功，但没有返回数据行。"));
    return section;
  }

  const wrap = el("div", "table-wrap");
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const column of data.columns || []) {
    headRow.append(el("th", "", column));
  }
  thead.append(headRow);
  table.append(thead);

  const tbody = document.createElement("tbody");
  for (const row of data.rows) {
    const tr = document.createElement("tr");
    for (const cell of row) {
      tr.append(el("td", "", cell));
    }
    tbody.append(tr);
  }
  table.append(tbody);
  wrap.append(table);
  section.append(wrap);

  if (data.truncated) {
    section.append(
      el("p", "note", `结果已截断，仅展示前 ${data.rows.length} 行；完整数据请缩小查询范围。`)
    );
  }
  return section;
}

function renderList(title, items) {
  const section = el("div", "section");
  section.append(el("div", "section-title", title));
  const list = el("ul", "list");
  for (const item of items) list.append(el("li", "", item));
  section.append(list);
  return section;
}

function renderResult(body, data) {
  body.replaceChildren();
  body.append(renderHead(data));
  body.append(el("p", "answer", data.answer || "（未返回答案）"));

  if (data.sql) body.append(renderSql(data));
  if (Array.isArray(data.columns) && data.columns.length) {
    body.append(renderTable(data));
  }
  if (Array.isArray(data.evidence) && data.evidence.length) {
    body.append(renderList("证据", data.evidence));
  }
  if (Array.isArray(data.caveats) && data.caveats.length) {
    body.append(renderList("注意事项", data.caveats));
  }
  if (data.error) {
    const details = el("details", "error");
    details.append(el("summary", "", "错误详情"));
    details.append(el("pre", "", data.error));
    body.append(details);
  }
  scrollToBottom();
}

/* ------------------------------------------------------------------ 请求 */

async function sendQuestion(raw) {
  if (busy) return;
  const question = String(raw || "").trim();
  if (!question) return;

  addUserMessage(question);
  const shell = addAssistantShell();
  renderPending(shell.body);
  setBusy(true);

  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 120000);

  try {
    const response = await fetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
      signal: controller.signal,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || `请求失败（HTTP ${response.status}）`);
    }
    renderResult(shell.body, payload);
  } catch (error) {
    const message =
      error && error.name === "AbortError"
        ? "请求超时（120 秒），请稍后重试或换一个更简单的问题。"
        : error instanceof Error
          ? error.message
          : String(error);
    renderError(shell.body, message);
  } finally {
    window.clearTimeout(timer);
    setBusy(false);
    input.focus();
  }
}

/* ------------------------------------------------------------------ 事件 */

form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (busy) return;
  const value = input.value;
  input.value = "";
  input.style.height = "auto";
  sendQuestion(value);
});

input.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  if (busy) return;
  const value = input.value;
  input.value = "";
  input.style.height = "auto";
  sendQuestion(value);
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
});

for (const chip of document.querySelectorAll(".chip")) {
  chip.addEventListener("click", () => sendQuestion(chip.textContent || ""));
}

newChatBtn.addEventListener("click", () => {
  if (busy) return;
  for (const node of chat.querySelectorAll(".msg")) node.remove();
  welcome.classList.remove("hidden");
  input.value = "";
  input.style.height = "auto";
  input.focus();
});

/* ------------------------------------------------------------------ 健康检查 */

async function checkHealth() {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    const health = await response.json();
    if (health.has_api_key) {
      statusEl.classList.add("ok");
      statusText.textContent = `${health.tables} 张表 · ${health.model}`;
      statusEl.title = `数据库：${health.db}`;
    } else {
      statusEl.classList.add("warn");
      statusText.textContent = "缺少 API Key";
      statusEl.title = "设置 OPENAI_API_KEY 后重启服务即可开始查询";
    }
  } catch {
    statusEl.classList.add("error");
    statusText.textContent = "服务未连接";
    statusEl.title = "无法访问 /api/health";
  }
}

checkHealth();
input.focus();

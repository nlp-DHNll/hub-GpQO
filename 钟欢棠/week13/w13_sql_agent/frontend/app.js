"use strict";

const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("send");
const statusEl = document.getElementById("status");

let busy = false;

function setStatus(text, kind) {
  statusEl.textContent = text;
  statusEl.className = "status" + (kind ? " status-" + kind : "");
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function appendUserMessage(text) {
  const wrap = document.createElement("div");
  wrap.className = "msg user";
  wrap.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
  messagesEl.appendChild(wrap);
  scrollToBottom();
}

function appendAssistantShell() {
  const wrap = document.createElement("div");
  wrap.className = "msg assistant";
  wrap.innerHTML = `<div class="bubble"><span class="thinking">正在思考…</span></div>`;
  messagesEl.appendChild(wrap);
  scrollToBottom();
  return wrap.querySelector(".bubble");
}

function renderAssistant(bubble, data) {
  const tags = [];
  if (data.tables && data.tables.length) {
    data.tables.forEach((t) => tags.push(`<span class="tag">表: ${escapeHtml(t)}</span>`));
  }
  if (data.row_count) {
    tags.push(`<span class="tag">行数: ${data.row_count}</span>`);
  }
  if (data.error) {
    tags.push(`<span class="tag err">错误</span>`);
  }

  const timeline = (data.steps || [])
    .map((s) => `<li>${escapeHtml(s)}</li>`)
    .join("");

  const extra =
    `<details class="extra"><summary>查看执行过程（LangGraph 轨迹 / SQL）</summary>` +
    (timeline ? `<ul class="timeline">${timeline}</ul>` : "") +
    (data.sql ? `<div class="sql-block">${escapeHtml(data.sql)}</div>` : "") +
    (data.caveats && data.caveats.length
      ? `<div class="sql-block" style="color:#ffcf6b">注意：${escapeHtml(
          data.caveats.join("；")
        )}</div>`
      : "") +
    `</details>`;

  bubble.innerHTML =
    `${escapeHtml(data.answer || "（无结果）")}` +
    (tags.length ? `<div class="tags">${tags.join("")}</div>` : "") +
    extra;
  scrollToBottom();
}

function autoGrow() {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 140) + "px";
}

async function send() {
  const text = inputEl.value.trim();
  if (!text || busy) return;

  appendUserMessage(text);
  inputEl.value = "";
  autoGrow();

  busy = true;
  sendBtn.disabled = true;
  setStatus("处理中…", "busy");
  const bubble = appendAssistantShell();

  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history: [] }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${resp.status}`);
    }
    const data = await resp.json();
    renderAssistant(bubble, data);
    setStatus("就绪", "ok");
  } catch (e) {
    bubble.innerHTML = `<span class="thinking">请求失败：${escapeHtml(
      e.message
    )}</span>`;
    setStatus("出错", "err");
  } finally {
    busy = false;
    sendBtn.disabled = false;
  }
}

// 事件绑定
sendBtn.addEventListener("click", send);
inputEl.addEventListener("input", autoGrow);
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});

// 点击示例问题
messagesEl.addEventListener("click", (e) => {
  const li = e.target.closest(".suggestions li");
  if (li) {
    inputEl.value = li.textContent;
    send();
  }
});

// 启动健康检查
fetch("/api/health")
  .then((r) => r.json())
  .then(() => setStatus("就绪", "ok"))
  .catch(() => setStatus("后端未连接", "err"));

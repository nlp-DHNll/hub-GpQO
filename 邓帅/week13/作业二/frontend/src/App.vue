<script setup>
import { nextTick, onMounted, reactive, ref } from "vue";
import { marked } from "marked";
import { chatStream, fetchHistory, stageText } from "./api.js";

/**
 * 数据模型：
 * - threads：会话列表（localStorage 持久化 thread_id + 标题）
 * - messages：当前会话消息流。assistant 消息是「组装体」：
 *   steps[]（阶段进度，真实 SSE 流式到达）+ sql + answer（打字机渲染）
 *   + result（WorkflowOutput 元信息）+ clarification
 */

const STORAGE_KEY = "sql-agent-threads";

const threads = ref([]);
const activeThreadId = ref(null);
const messages = reactive([]);
const question = ref("");
const sending = ref(false);
const listRef = ref(null);

function loadThreads() {
  try {
    threads.value = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
  } catch {
    threads.value = [];
  }
}

function saveThreads() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(threads.value.slice(0, 50)));
}

function newThread() {
  activeThreadId.value = null;
  messages.length = 0;
}

async function switchThread(id) {
  activeThreadId.value = id;
  messages.length = 0;
  try {
    const turns = await fetchHistory(id);
    if (!turns.length) throw new Error("empty");
    for (const t of turns) {
      messages.push({ role: "user", text: t.question });
      messages.push({
        role: "assistant",
        steps: [],
        sql: t.sql || null,
        answer: t.answer || null,
        result: t.row_count !== undefined ? t : null,
        clarification: null,
      });
    }
    messages.push({
      role: "system",
      text: "已从 checkpoint 恢复该会话全部轮次，直接追问即可延续上下文。",
    });
  } catch {
    messages.push({
      role: "system",
      text: `已切换会话（thread: ${id.slice(0, 13)}…），但未找到历史轮次；直接追问仍会延续该会话上下文。`,
    });
  }
  scrollBottom();
}

function rememberThread(threadId, title) {
  activeThreadId.value = threadId;
  const existing = threads.value.find((t) => t.id === threadId);
  if (existing) {
    existing.updatedAt = Date.now();
  } else {
    threads.value.unshift({ id: threadId, title, updatedAt: Date.now() });
    saveThreads();
  }
}

function scrollBottom() {
  nextTick(() => {
    const el = listRef.value?.wrapRef;
    if (el) el.scrollTop = el.scrollHeight;
  });
}

/** result.answer 的打字机渲染：LLM 为结构化输出无 token 流，由前端按节奏放出 */
function typewrite(msg, fullText) {
  let i = 0;
  msg.answer = "";
  const timer = setInterval(() => {
    const step = Math.max(1, Math.round(fullText.length / 120));
    msg.answer = fullText.slice(0, (i += step));
    scrollBottom();
    if (i >= fullText.length) {
      msg.answer = fullText;
      clearInterval(timer);
    }
  }, 24);
}

async function send() {
  const text = question.value.trim();
  if (!text || sending.value) return;

  messages.push({ role: "user", text });
  question.value = "";
  sending.value = true;
  scrollBottom();

  const msg = reactive({
    role: "assistant",
    steps: [],
    sql: null,
    answer: null,
    result: null,
    clarification: null,
    error: null,
  });
  messages.push(msg);

  try {
    await chatStream(text, activeThreadId.value, ({ event, data }) => {
      if (event === "meta") {
        rememberThread(data.thread_id, text.slice(0, 18));
      } else if (event === "progress") {
        msg.steps.push(stageText(data.node, data.stage));
        scrollBottom();
      } else if (event === "sql") {
        msg.sql = data.sql;
        scrollBottom();
      } else if (event === "clarification") {
        msg.clarification = data.question;
        scrollBottom();
      } else if (event === "result") {
        msg.result = data;
        if (!msg.sql && data.sql) msg.sql = data.sql;
        if (data.answer) typewrite(msg, data.answer);
      } else if (event === "error") {
        msg.error = data.message;
      }
    });
  } catch (err) {
    msg.error = String(err);
  } finally {
    sending.value = false;
    scrollBottom();
  }
}

function onKeydown(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
}

function renderMarkdown(text) {
  return marked.parse(text || "", { breaks: true });
}

onMounted(() => {
  loadThreads();
  // 演示辅助：#q=<问题> 自动发送；#t=<thread_id> 自动恢复会话（截图/冒烟用）
  const threadMatch = location.hash.match(/[#&]t=([^&]+)/);
  const match = location.hash.match(/[#&]q=([^&]+)/);
  if (threadMatch) {
    switchThread(decodeURIComponent(threadMatch[1]));
  } else if (match) {
    question.value = decodeURIComponent(match[1]);
    send();
  }
});
</script>

<template>
  <el-container class="shell">
    <el-aside width="240px" class="aside">
      <div class="brand">
        <div class="brand-title">Chinook SQL Agent</div>
        <div class="brand-sub">LangGraph · 子图 + 持久化多轮</div>
      </div>
      <el-button type="primary" plain class="new-btn" @click="newThread">
        ＋ 新会话
      </el-button>
      <el-scrollbar class="thread-list">
        <div
          v-for="t in threads"
          :key="t.id"
          class="thread-item"
          :class="{ active: t.id === activeThreadId }"
          :title="t.title"
          @click="switchThread(t.id)"
        >
          <span class="thread-title">{{ t.title }}</span>
        </div>
      </el-scrollbar>
      <div class="aside-foot">thread_id 由后端 checkpoint 管理</div>
    </el-aside>

    <el-container class="main">
      <el-header class="header" height="52px">
        <span>对话查询 Chinook 数据库</span>
        <span class="header-hint">Enter 发送 · Shift+Enter 换行</span>
      </el-header>

      <el-main class="chat">
        <el-scrollbar ref="listRef" class="scroller">
          <div v-if="messages.length === 0" class="empty">
            <el-empty description="问点什么吧，例如：总共有多少张专辑？" />
          </div>

          <div v-for="(m, i) in messages" :key="i" class="row" :class="m.role">
            <!-- 用户气泡 -->
            <div v-if="m.role === 'user'" class="bubble user-bubble">{{ m.text }}</div>

            <!-- 系统提示 -->
            <div v-else-if="m.role === 'system'" class="system-tip">{{ m.text }}</div>

            <!-- 助手消息 -->
            <div v-else class="bubble assistant-bubble">
              <!-- 阶段进度（真实 SSE 流式） -->
              <div v-if="m.steps.length" class="steps">
                <div v-for="(s, j) in m.steps" :key="j" class="step">
                  <span class="dot" :class="{ ok: j < m.steps.length - 1 || m.result || m.clarification || m.error }"></span>
                  {{ s }}
                </div>
              </div>

              <!-- 澄清提问 -->
              <el-alert
                v-if="m.clarification"
                type="warning"
                :closable="false"
                show-icon
                title="需要补充信息"
                :description="m.clarification"
                class="clarify"
              />

              <!-- SQL 代码块 -->
              <div v-if="m.sql" class="sql-block">
                <div class="sql-head">SQL</div>
                <pre>{{ m.sql }}</pre>
              </div>

              <!-- 答案（打字机 / Markdown） -->
              <div
                v-if="m.answer !== null && m.answer !== ''"
                class="answer"
                v-html="renderMarkdown(m.answer)"
              ></div>
              <div v-else-if="sending && i === messages.length - 1" class="typing">
                <span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>
              </div>

              <!-- 结果元信息 -->
              <div v-if="m.result" class="meta">
                <el-tag size="small" type="info" v-if="m.result.tables?.length">
                  表：{{ m.result.tables.join("、") }}
                </el-tag>
                <el-tag size="small" type="info">行数：{{ m.result.row_count }}</el-tag>
                <el-tag v-if="m.result.repair_attempts" size="small" type="warning">
                  修复 {{ m.result.repair_attempts }} 次
                </el-tag>
              </div>
              <div v-for="(c, j) in m.result?.caveats || []" :key="'c' + j" class="caveat">⚠ {{ c }}</div>

              <el-alert
                v-if="m.error"
                type="error"
                :closable="false"
                show-icon
                title="出错了"
                :description="m.error"
              />
            </div>
          </div>
        </el-scrollbar>
      </el-main>

      <el-footer class="input-bar" height="auto">
        <div class="input-row">
          <el-input
            v-model="question"
            type="textarea"
            :rows="2"
            resize="none"
            placeholder="用自然语言查询，例如：销量最高的三张专辑是哪些？"
            :disabled="sending"
            @keydown="onKeydown"
          />
          <el-button type="primary" :loading="sending" @click="send">
            发送
          </el-button>
        </div>
      </el-footer>
    </el-container>
  </el-container>
</template>

<style>
html,
body,
#app {
  height: 100%;
  margin: 0;
}
#app {
  font-family: "PingFang SC", "Helvetica Neue", Arial, sans-serif;
}
</style>

<style scoped>
.shell {
  height: 100%;
}
.aside {
  border-right: 1px solid var(--el-border-color-light);
  display: flex;
  flex-direction: column;
  padding: 14px 12px;
  background: #fafbfc;
}
.brand {
  padding: 4px 6px 12px;
}
.brand-title {
  font-weight: 600;
  font-size: 15px;
}
.brand-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}
.new-btn {
  width: 100%;
  margin-bottom: 12px;
}
.thread-list {
  flex: 1;
}
.thread-item {
  padding: 9px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  color: var(--el-text-color-regular);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.thread-item:hover {
  background: var(--el-fill-color-light);
}
.thread-item.active {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}
.aside-foot {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  padding-top: 10px;
}
.main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--el-border-color-light);
  font-size: 14px;
  font-weight: 500;
}
.header-hint {
  font-size: 12px;
  font-weight: 400;
  color: var(--el-text-color-placeholder);
}
.chat {
  flex: 1;
  min-height: 0;
  padding: 8px 0;
}
.scroller {
  height: 100%;
}
.empty {
  padding-top: 12vh;
}
.row {
  display: flex;
  margin: 10px 18px;
}
.row.user {
  justify-content: flex-end;
}
.row.system {
  justify-content: center;
}
.system-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
  padding: 4px 12px;
  border-radius: 10px;
  white-space: pre-line;
}
.bubble {
  max-width: 76%;
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 14px;
  line-height: 1.65;
}
.user-bubble {
  background: var(--el-color-primary);
  color: #fff;
  white-space: pre-wrap;
}
.assistant-bubble {
  background: var(--el-fill-color-lighter);
  border: 1px solid var(--el-border-color-lighter);
  min-width: 220px;
}
.steps {
  margin-bottom: 8px;
}
.step {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 1px 0;
}
.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--el-color-primary);
  opacity: 0.45;
  flex: none;
}
.dot.ok {
  opacity: 1;
  background: var(--el-color-success);
}
.clarify {
  margin-bottom: 8px;
}
.sql-block {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  margin: 8px 0;
  overflow: hidden;
}
.sql-head {
  font-size: 11px;
  letter-spacing: 0.5px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
  padding: 3px 10px;
}
.sql-block pre {
  margin: 0;
  padding: 10px 12px;
  font-size: 12.5px;
  line-height: 1.5;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
.answer :deep(table) {
  border-collapse: collapse;
  margin: 6px 0;
  font-size: 12.5px;
}
.answer :deep(th),
.answer :deep(td) {
  border: 1px solid var(--el-border-color-lighter);
  padding: 3px 8px;
}
.typing {
  display: flex;
  gap: 4px;
  padding: 4px 0;
}
.typing-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--el-text-color-placeholder);
  animation: blink 1.2s infinite ease-in-out;
}
.typing-dot:nth-child(2) {
  animation-delay: 0.2s;
}
.typing-dot:nth-child(3) {
  animation-delay: 0.4s;
}
@keyframes blink {
  0%,
  80%,
  100% {
    opacity: 0.25;
  }
  40% {
    opacity: 1;
  }
}
.meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 8px;
}
.caveat {
  font-size: 12px;
  color: var(--el-color-warning);
  margin-top: 4px;
}
.input-bar {
  border-top: 1px solid var(--el-border-color-light);
  padding: 12px 18px 14px;
  background: #fff;
}
.input-row {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}
.input-row .el-button {
  height: 54px;
}
</style>

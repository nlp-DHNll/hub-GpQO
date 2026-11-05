/**
 * POST /api/chat 的 SSE 客户端。
 *
 * 浏览器 EventSource 只支持 GET，因此用 fetch + ReadableStream 手动解析
 * SSE 文本（按空行分块，event:/data: 字段），onEvent 回调逐事件上抛。
 */

const STAGE_LABELS = {
  table_selected: "已选表",
  clarify: "需要澄清",
  generated: "SQL 已生成",
  validated: "校验通过",
  invalid: "校验失败，进入修复",
  executed: "执行成功",
  rewritten: "SQL 已修复",
  repair_exhausted: "修复次数用尽",
  cannot_fix: "无法修复",
  done: "汇总完成",
};

const NODE_LABELS = {
  table_select: "选表",
  generate: "生成 SQL",
  repair: "校验/执行/修复",
  summarize: "汇总",
};

export function stageText(node, stage) {
  const nodeLabel = NODE_LABELS[node] || node;
  const stageLabel = STAGE_LABELS[stage] || stage || "";
  return `${nodeLabel}：${stageLabel}`;
}

/**
 * @param {string} question
 * @param {string|null} threadId
 * @param {(event: {event: string, data: any}) => void} onEvent
 * @param {AbortSignal} [signal]
 */
export async function chatStream(question, threadId, onEvent, signal) {
  const resp = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, thread_id: threadId }),
    signal,
  });
  if (!resp.ok || !resp.body) {
    throw new Error(`HTTP ${resp.status}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const handleBlock = (block) => {
    let event = "message";
    let data = "";
    for (const rawLine of block.split(/\r?\n/)) {
      if (rawLine.startsWith("event:")) event = rawLine.slice(6).trim();
      else if (rawLine.startsWith("data:")) data = rawLine.slice(5).trim();
    }
    if (!event) return;
    let parsed = data;
    try {
      parsed = data ? JSON.parse(data) : {};
    } catch {
      /* 保留原文 */
    }
    onEvent({ event, data: parsed });
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE 块分隔兼容 \n\n 与 \r\n\r\n（不同代理/客户端行尾不一致）
    let match;
    const sep = /\r?\n\r?\n/;
    while ((match = sep.exec(buffer))) {
      const block = buffer.slice(0, match.index);
      buffer = buffer.slice(match.index + match[0].length);
      if (block.trim()) handleBlock(block);
    }
  }
  if (buffer.trim()) handleBlock(buffer);
}

/** 从后端 checkpoint 还原某会话的全部轮次 */
export async function fetchHistory(threadId) {
  const resp = await fetch(`/api/history?thread_id=${encodeURIComponent(threadId)}`);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const data = await resp.json();
  return data.turns || [];
}

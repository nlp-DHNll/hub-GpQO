// SSE 消费封装:原生 EventSource 断线自动重连并携带 Last-Event-ID;
// 收到终结事件后主动关闭,避免 EventSource 对已关闭的流反复重连。
import type { ResearchEvent } from './types'

const TERMINAL_TYPES = new Set(['report_done', 'aborted', 'error'])

export interface SSEHandle {
  close: () => void
}

export function subscribeEvents(
  taskId: string,
  onEvent: (ev: ResearchEvent) => void,
  onTerminal: (ev: ResearchEvent) => void,
): SSEHandle {
  let closedByUs = false
  const es = new EventSource(`/api/research/${taskId}/events`)

  es.onmessage = (e: MessageEvent<string>) => {
    let ev: ResearchEvent
    try {
      ev = JSON.parse(e.data) as ResearchEvent
    } catch {
      return
    }
    onEvent(ev)
    if (TERMINAL_TYPES.has(ev.type)) {
      closedByUs = true
      es.close()
      onTerminal(ev)
    }
  }

  es.onerror = () => {
    // 原生机制:非主动关闭时自动重连(带 Last-Event-ID,服务端从断点重放)
    if (closedByUs) {
      es.close()
    }
  }

  return {
    close: () => {
      closedByUs = true
      es.close()
    },
  }
}

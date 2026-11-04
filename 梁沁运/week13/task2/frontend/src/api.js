const API_BASE = '/api'

/** 检查后端健康状态 */
export async function checkHealth() {
  try {
    const res = await fetch(`${API_BASE}/health`)
    if (!res.ok) return { status: 'offline', api_key_configured: false, tables: 0 }
    return { status: 'online', ...(await res.json()) }
  } catch {
    return { status: 'offline', api_key_configured: false, tables: 0 }
  }
}

/** 同步查询 */
export async function querySync(question) {
  const res = await fetch(`${API_BASE}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
    throw new Error(err.detail || `请求失败: ${res.status}`)
  }
  return res.json()
}

/** 流式查询 — 返回 ReadableStream 的 reader */
export function queryStream(question) {
  return fetch(`${API_BASE}/query/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
}

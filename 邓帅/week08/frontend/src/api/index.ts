// 后端 REST 接口封装
import type { ReportDetail, ReportSummary, TaskStatusResp } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(`请求失败 ${resp.status}:${text.slice(0, 200)}`)
  }
  return resp.json() as Promise<T>
}

export function startResearch(topic: string) {
  return request<{ task_id: string }>('/api/research', {
    method: 'POST',
    body: JSON.stringify({ topic }),
  })
}

export function fetchTaskStatus(taskId: string) {
  return request<TaskStatusResp>(`/api/research/${taskId}`)
}

export function cancelResearch(taskId: string) {
  return request<{ task_id: string; status: string }>(`/api/research/${taskId}`, {
    method: 'DELETE',
  })
}

export async function fetchReports(): Promise<ReportSummary[]> {
  const data = await request<{ items: ReportSummary[] }>('/api/reports')
  return data.items
}

export function fetchReport(taskId: string) {
  return request<ReportDetail>(`/api/reports/${taskId}`)
}

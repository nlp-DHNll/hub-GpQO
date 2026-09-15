// 与后端 API 响应 / SSE 事件结构一一对应

/** SSE 进度事件(data 为 JSON,含递增 id) */
export interface ResearchEvent {
  id: number
  type:
    | 'created'
    | 'plan'
    | 'round_start'
    | 'search'
    | 'read'
    | 'reflect'
    | 'synthesize_start'
    | 'report_done'
    | 'aborted'
    | 'error'
    | 'resumed'
  task_id?: string
  topic?: string
  round?: number
  queries?: string[]
  urls?: string[]
  ok?: number
  fallback?: number
  sufficient?: boolean
  gaps?: string
  sub_questions?: string[]
  message?: string
}

export type TaskStatus =
  | 'running'
  | 'completed'
  | 'incomplete'
  | 'aborted'
  | 'failed'

export interface TaskStatusResp {
  task_id: string
  topic: string
  status: TaskStatus
  events_count: number
}

export interface ProcessStats {
  searches: number
  pages_read: number
  rounds: number
}

export interface ReportSummary {
  task_id: string
  topic: string
  created_at: string
  status: TaskStatus
  stats: ProcessStats
}

export interface SourceMeta {
  title: string
  summary: string
  date_published?: string
  from_summary?: boolean
  cited?: number
}

export interface ProcessRound {
  round: number
  queries: string[]
  failed_queries?: string[]
  read_urls?: string[]
  findings_added?: number
  gaps?: string
}

export interface ResearchProcess {
  task_id: string
  topic: string
  created_at: string
  plan: string[]
  rounds: ProcessRound[]
  stats: ProcessStats
  sources: Record<string, SourceMeta>
  model: string
  status: TaskStatus
}

export interface ReportDetail {
  task_id: string
  report_md: string
  process: ResearchProcess
}

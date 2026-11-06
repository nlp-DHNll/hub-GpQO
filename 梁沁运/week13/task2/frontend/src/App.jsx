import { useState, useEffect, useRef, useCallback } from 'react'
import * as api from './api.js'

// ===== 阶段配置：中英文标签 + 图标 =====
const STAGE_META = {
  start: { label: '开始解析', icon: '🚀', color: 'pending' },
  table_select: { label: '选择数据表', icon: '🔍', color: 'active' },
  table_select_tools: { label: '获取表结构', icon: '📋', color: 'active' },
  validate_selection: { label: '校验表选择', icon: '✅', color: 'active' },
  schema_render: { label: '渲染 Schema', icon: '📄', color: 'active' },
  sql_generate: { label: '生成 SQL', icon: '🧠', color: 'active' },
  validate_sql: { label: '校验 SQL', icon: '🔒', color: 'active' },
  execute: { label: '执行查询', icon: '⚡', color: 'active' },
  sql_rewrite: { label: '修复 SQL', icon: '🔧', color: 'active' },
  summarize: { label: '汇总答案', icon: '📝', color: 'active' },
  summarize_fallback: { label: '降级汇总', icon: '📝', color: 'warning' },
  clarify_or_reject: { label: '需要澄清', icon: '❓', color: 'error' },
  failure_answer: { label: '查询失败', icon: '❌', color: 'error' },
  done: { label: '完成', icon: '🎉', color: 'done' },
  error: { label: '错误', icon: '💥', color: 'error' },
}

const EXAMPLE_QUESTIONS = [
  'albums 表里有多少张专辑？',
  '每位客户的总消费金额是多少？',
  '播放时长最长的 10 首曲目是哪些？',
  'Rock 类型的曲目有哪些？列出前 10 首。',
  '每个播放列表各有多少首曲目？',
  '2010 年之后入职的员工有哪些？',
]

// ===== Sidebar Component =====
function Sidebar({ health, onSelectExample }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h1>
          <span className="icon">🕵️</span>
          SQL Agent
        </h1>
        <p className="subtitle">基于 LangGraph 的自然语言查询</p>
      </div>

      <div className="sidebar-section">
        <h3>示例问题</h3>
        {EXAMPLE_QUESTIONS.map((q, i) => (
          <button key={i} className="example-btn" onClick={() => onSelectExample(q)}>
            {q}
          </button>
        ))}
      </div>

      <div className="sidebar-section">
        <h3>数据库表 ({health.tables || 11})</h3>
        <div className="table-list">
          {[
            'albums', 'artists', 'customers', 'employees',
            'genres', 'invoice_items', 'invoices', 'media_types',
            'playlist_track', 'playlists', 'tracks',
          ].map(t => (
            <span key={t} className="table-tag">{t}</span>
          ))}
        </div>
      </div>

      <div className="connection-status">
        <span className={`status-dot ${health.status === 'online' ? 'online' : health.status === 'checking' ? 'checking' : 'offline'}`} />
        <span>
          {health.status === 'online'
            ? `后端已连接 · ${health.api_key_configured ? 'API Key 已配置' : '未配置 API Key'}`
            : health.status === 'checking'
              ? '正在检查连接...'
              : '后端未连接'}
        </span>
      </div>
    </aside>
  )
}

// ===== Workflow Steps Component =====
function WorkflowSteps({ stages }) {
  if (!stages || stages.length === 0) return null

  // 只展示关键阶段
  const keyStages = stages.filter(s => {
    const name = s.stage || s.node
    return !['table_select_tools', 'schema_render', 'start'].includes(name)
  })

  if (keyStages.length === 0) return null

  return (
    <details className="workflow-steps" open>
      <summary>工作流执行步骤</summary>
      <div className="steps-list">
        {keyStages.map((s, i) => {
          const name = s.stage || s.node
          const meta = STAGE_META[name] || { label: name, icon: '→', color: 'pending' }
          const completed = i < keyStages.length - 1 || meta.color === 'done' || meta.color === 'error'
          const statusColor = completed ? 'done' : meta.color === 'error' ? 'error' : 'active'

          return (
            <div key={i} className="step-item">
              <span className={`step-indicator ${statusColor}`} />
              <div className="step-info">
                <span className="step-name">
                  {meta.icon} {meta.label}
                </span>
                {s.data?.selection && (
                  <div className="step-detail">
                    选中表: {s.data.selection.tables.join(', ') || '无'}
                    {s.data.selection.needs_clarification && ' (需要澄清)'}
                  </div>
                )}
                {s.data?.sql && (
                  <div className="step-sql">{s.data.sql}</div>
                )}
                {s.data?.validation && s.data.validation.ok === false && (
                  <div className="step-detail">
                    校验失败: [{s.data.validation.code}] {s.data.validation.message}
                  </div>
                )}
                {s.data?.validation && s.data.validation.ok === true && (
                  <div className="step-detail">校验通过 ✓</div>
                )}
                {s.data?.execution && (
                  <div className="step-detail">
                    返回 {s.data.execution.row_count} 行
                    {s.data.execution.truncated && ' (已截断)'}
                  </div>
                )}
                {s.data?.error && (
                  <div className="step-error">错误: {s.data.error}</div>
                )}
                {s.data?.repair_attempts != null && (
                  <div className="step-detail">
                    修复尝试: {s.data.repair_attempts}/3
                  </div>
                )}
                {s.data?.selection_retry_count != null && (
                  <div className="step-detail">
                    选表重试: {s.data.selection_retry_count}/1
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </details>
  )
}

// ===== Answer Message Component =====
function AnswerMessage({ answer }) {
  // 简单 markdown 渲染
  const renderMarkdown = (text) => {
    if (!text) return ''
    // 代码块
    let html = text
      .replace(/```sql\n([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
      .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      // 表格
      .replace(/^\|(.+)\|$/gm, (match) => {
        const cells = match.split('|').filter(c => c.trim()).map(c => c.trim())
        const isHeader = /^[-:\s]+$/.test(cells.join(''))
        if (isHeader) return ''
        const tag = cells[0]?.startsWith('---') ? '' : (cells.length > 0 ? `<tr>${cells.map((c, i) => {
          // Check if row above was a header separator
          return `<td>${c}</td>`
        }).join('')}</tr>` : '')
        return tag
      })
      // 标题
      .replace(/^### (.+)$/gm, '<h3>$1</h3>')
      .replace(/^## (.+)$/gm, '<h2>$1</h2>')
      // 粗体
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      // 换行
      .replace(/\n\n/g, '<br/><br/>')
      .replace(/\n/g, '<br/>')

    return html
  }

  return (
    <>
      <div
        className="answer-text"
        dangerouslySetInnerHTML={{ __html: renderMarkdown(answer.answer) }}
      />
      {answer.evidence && answer.evidence.length > 0 && (
        <details className="evidence-block">
          <summary>支撑证据</summary>
          <ul>
            {answer.evidence.map((e, i) => <li key={i}>{e}</li>)}
          </ul>
        </details>
      )}
      {answer.caveats && answer.caveats.length > 0 && (
        <details className="caveats-block">
          <summary>注意事项</summary>
          <ul>
            {answer.caveats.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
        </details>
      )}
    </>
  )
}

// ===== Main App =====
export default function App() {
  const [health, setHealth] = useState({ status: 'checking', api_key_configured: false, tables: 11 })
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  const abortRef = useRef(null)

  // 健康检查
  useEffect(() => {
    api.checkHealth().then(setHealth)
    const interval = setInterval(() => api.checkHealth().then(setHealth), 30000)
    return () => clearInterval(interval)
  }, [])

  // 滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // 提交查询
  const handleSubmit = useCallback(async (e) => {
    e?.preventDefault()
    const question = input.trim()
    if (!question || loading) return

    setInput('')
    setLoading(true)

    // 添加用户消息和占位的 agent 消息
    const userMsg = { role: 'user', content: question, id: Date.now() }
    const agentMsg = { role: 'agent', id: Date.now() + 1, stages: [], answer: null, loading: true }
    setMessages(prev => [...prev, userMsg, agentMsg])

    try {
      const response = await api.queryStream(question)

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }))
        throw new Error(err.detail || `请求失败: ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      abortRef.current = () => reader.cancel()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const jsonStr = line.slice(6).trim()
          if (!jsonStr) continue

          try {
            const event = JSON.parse(jsonStr)

            setMessages(prev => {
              const updated = [...prev]
              const lastIdx = updated.length - 1
              if (lastIdx < 0 || updated[lastIdx].role !== 'agent') return updated

              const agent = { ...updated[lastIdx] }

              if (event.type === 'stage' && event.data) {
                agent.stages = [...(agent.stages || []), {
                  node: event.data.node,
                  stage: event.stage,
                  data: event.data,
                }]
              }

              if (event.type === 'error') {
                agent.answer = { answer: `查询出错: ${event.data?.error || '未知错误'}`, evidence: [], caveats: [] }
                agent.loading = false
              }

              if (event.type === 'complete') {
                // find last answer from stages
                const allStages = agent.stages || []
                const lastAnswer = [...allStages].reverse().find(s => s.data?.answer)
                if (lastAnswer?.data?.answer) {
                  agent.answer = lastAnswer.data.answer
                } else if (!agent.answer) {
                  agent.answer = { answer: '查询完成但未获得答案。', evidence: [], caveats: [] }
                }
                agent.loading = false
              }

              updated[lastIdx] = agent
              return updated
            })
          } catch {
            // skip malformed JSON
          }
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') return
      setMessages(prev => {
        const updated = [...prev]
        const lastIdx = updated.length - 1
        if (lastIdx >= 0 && updated[lastIdx].role === 'agent') {
          updated[lastIdx] = {
            ...updated[lastIdx],
            answer: { answer: `查询出错: ${err.message}`, evidence: [], caveats: [] },
            loading: false,
          }
        }
        return updated
      })
    } finally {
      setLoading(false)
      abortRef.current = null
    }
  }, [input, loading])

  // 键盘快捷键
  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }, [handleSubmit])

  return (
    <div className="app">
      <Sidebar
        health={health}
        onSelectExample={(q) => {
          setInput(q)
          // 延迟自动提交
          setTimeout(() => {
            inputRef.current?.focus()
          }, 100)
        }}
      />

      <main className="main">
        <div className="chat-header">
          <h2>对话查询</h2>
          <span className="badge">
            {loading ? '查询中...' : '就绪'}
          </span>
        </div>

        <div className="messages">
          {messages.length === 0 && (
            <div className="messages-empty">
              <div className="welcome-icon">💬</div>
              <h2>用自然语言查询数据库</h2>
              <p>
                输入中文问题，SQL Agent 将自动选择数据表、生成并校验 SQL、
                执行查询，并返回易懂的中文答案。试试左侧的示例问题吧！
              </p>
            </div>
          )}

          {messages.map(msg => (
            <div key={msg.id} className={`message ${msg.role}`}>
              <div className="message-avatar">
                {msg.role === 'user' ? '👤' : '🤖'}
              </div>
              <div className="message-bubble">
                {msg.role === 'user' ? (
                  msg.content
                ) : msg.loading ? (
                  <div className="loading-dots">
                    <span /><span /><span />
                  </div>
                ) : (
                  <>
                    {msg.answer && <AnswerMessage answer={msg.answer} />}
                    {msg.stages && <WorkflowSteps stages={msg.stages} />}
                  </>
                )}
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        <div className="input-area">
          <form onSubmit={handleSubmit}>
            <div className="input-wrapper">
              <textarea
                ref={inputRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="输入你的查询问题，例如：每位客户的总消费金额是多少？"
                rows={1}
                disabled={loading}
              />
            </div>
            <button type="submit" className="send-btn" disabled={loading || !input.trim()}>
              {loading ? '⏳ 查询中' : '发送 →'}
            </button>
          </form>
        </div>
      </main>
    </div>
  )
}

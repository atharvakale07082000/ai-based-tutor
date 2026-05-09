import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import toast from 'react-hot-toast'
import { PageWrapper } from '@/components/layout/PageWrapper'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { api } from '@/lib/api'

// ─── Types ────────────────────────────────────────────────────────────────────

type AgentKey =
  | 'doubt_solver' | 'quiz_agent' | 'course_planner'
  | 'curriculum_agent' | 'progress_agent' | 'navigator' | 'general'
  | 'guardrail' | 'error'

interface SseEvent {
  type: 'routing' | 'token' | 'action' | 'delegation' | 'guardrail' | 'done' | 'error'
  agent?: AgentKey
  reason?: string
  delegated_from?: string | null
  content?: string
  kind?: string
  payload?: Record<string, unknown>
  from?: string
  to?: string
  message?: string
}

interface ActionCard {
  kind: string
  payload: Record<string, unknown>
}

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  agent?: AgentKey
  delegations?: Array<{ from: string; to: string; reason: string }>
  actions?: ActionCard[]
  isStreaming?: boolean
  guardrailBlocked?: boolean
}

// ─── Agent meta ───────────────────────────────────────────────────────────────

const AGENT_META: Record<string, { label: string; emoji: string; color: string }> = {
  doubt_solver:     { label: 'Doubt-Solver',      emoji: '💡', color: 'violet' },
  quiz_agent:       { label: 'Quiz Agent',         emoji: '📝', color: 'amber' },
  course_planner:   { label: 'Course Planner',     emoji: '🗺️', color: 'indigo' },
  curriculum_agent: { label: 'Curriculum Agent',   emoji: '📚', color: 'emerald' },
  progress_agent:   { label: 'Progress Tracker',   emoji: '📊', color: 'violet' },
  navigator:        { label: 'Navigator',          emoji: '🧭', color: 'surface' },
  general:          { label: 'Assistant',          emoji: '🤖', color: 'surface' },
  guardrail:        { label: 'Guardrail',          emoji: '🛡️', color: 'rose' },
  error:            { label: 'Error',              emoji: '⚠️', color: 'rose' },
}

const QUICK_ACTIONS = [
  { label: 'Explain Python decorators', icon: '💡' },
  { label: 'Quiz me on Machine Learning', icon: '📝' },
  { label: 'Create a roadmap for Data Science', icon: '🗺️' },
  { label: 'Show my progress', icon: '📊' },
  { label: 'Build my curriculum', icon: '📚' },
  { label: 'Take me to the dashboard', icon: '🧭' },
]

// ─── Markdown-ish renderer (bold + newlines only) ────────────────────────────

function SimpleMarkdown({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith('**') && p.endsWith('**') ? (
          <strong key={i}>{p.slice(2, -2)}</strong>
        ) : (
          <span key={i} style={{ whiteSpace: 'pre-wrap' }}>{p}</span>
        )
      )}
    </>
  )
}

// ─── Action card ──────────────────────────────────────────────────────────────

function ActionCardView({ action }: { action: ActionCard }) {
  const navigate = useNavigate()

  if (action.kind === 'quiz_created') {
    const p = action.payload
    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="mt-3 bg-amber/10 border border-amber/30 rounded-2xl p-4 flex items-center justify-between gap-4"
      >
        <div>
          <p className="text-xs text-paper/50 mb-0.5">Quiz ready</p>
          <p className="text-sm font-medium text-paper">{p.topic as string} · {p.question_count as number} questions · {p.bloom_level as string}</p>
        </div>
        <Button size="sm" onClick={() => navigate(p.url as string)}>Start Quiz →</Button>
      </motion.div>
    )
  }

  if (action.kind === 'plan_created') {
    const p = action.payload
    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="mt-3 bg-indigo/10 border border-indigo/30 rounded-2xl p-4 flex items-center justify-between gap-4"
      >
        <div>
          <p className="text-xs text-paper/50 mb-0.5">Course plan ready</p>
          <p className="text-sm font-medium text-paper">{p.title as string}</p>
          <p className="text-xs text-paper/40">{p.module_count as number} modules · {p.weeks as number} weeks</p>
        </div>
        <Button size="sm" onClick={() => navigate(p.url as string)}>View Plan →</Button>
      </motion.div>
    )
  }

  if (action.kind === 'navigate') {
    const p = action.payload
    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="mt-3 inline-flex"
      >
        <Button size="sm" variant="secondary" onClick={() => navigate(p.url as string)}>
          → {p.label as string}
        </Button>
      </motion.div>
    )
  }

  return null
}

// ─── Message bubble ───────────────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const meta = AGENT_META[msg.agent ?? 'general']

  if (msg.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[78%] bg-violet/20 border border-violet/30 rounded-2xl rounded-tr-sm px-4 py-3 text-sm text-paper">
          {msg.content}
        </div>
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col gap-2"
    >
      {/* Agent badge */}
      {msg.agent && (
        <div className="flex items-center gap-2 ml-1">
          <span className="text-sm">{meta.emoji}</span>
          <span className="text-xs text-paper/40 font-medium">{meta.label}</span>
          {msg.delegations?.map((d, i) => (
            <span key={i} className="text-xs text-paper/30">← delegated from {AGENT_META[d.from]?.label ?? d.from}</span>
          ))}
        </div>
      )}

      {/* Guardrail */}
      {msg.guardrailBlocked ? (
        <div className="bg-rose/10 border border-rose/30 rounded-2xl px-4 py-3 text-sm text-rose/80 flex items-center gap-2">
          <span>🛡️</span>
          {msg.content}
        </div>
      ) : (
        <div className="max-w-[85%] bg-surface-2/80 border border-surface-3/50 rounded-2xl rounded-tl-sm px-4 py-3 text-sm text-paper/90 leading-relaxed">
          {msg.content ? <SimpleMarkdown text={msg.content} /> : null}
          {msg.isStreaming && (
            <span className="inline-flex gap-0.5 ml-1">
              {[0, 1, 2].map((i) => (
                <span key={i} className="w-1 h-1 rounded-full bg-paper/40"
                  style={{ animation: `blink 1.2s ease-in-out ${i * 0.2}s infinite` }} />
              ))}
            </span>
          )}
        </div>
      )}

      {/* Action cards */}
      {msg.actions?.map((a, i) => <ActionCardView key={i} action={a} />)}
    </motion.div>
  )
}

// ─── Routing indicator ────────────────────────────────────────────────────────

function RoutingBadge({ agent, reason, delegatedFrom }: { agent: string; reason: string; delegatedFrom?: string | null }) {
  const meta = AGENT_META[agent] ?? AGENT_META.general
  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0 }}
      className="flex items-center gap-2 text-xs text-paper/40 py-1"
    >
      <span>{meta.emoji}</span>
      <span className="text-paper/60 font-medium">{meta.label}</span>
      {delegatedFrom && <span className="text-paper/30">← from {AGENT_META[delegatedFrom]?.label}</span>}
      <span className="text-paper/30">·</span>
      <span className="text-paper/30 truncate max-w-xs">{reason}</span>
      <span className="flex gap-0.5 ml-auto">
        {[0, 1, 2].map((i) => (
          <span key={i} className="w-1 h-1 rounded-full bg-violet/60"
            style={{ animation: `blink 1.2s ease-in-out ${i * 0.2}s infinite` }} />
        ))}
      </span>
    </motion.div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function AssistantPage() {
  const navigate = useNavigate()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [routingInfo, setRoutingInfo] = useState<{ agent: string; reason: string; delegatedFrom?: string | null } | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, routingInfo])

  const buildHistory = useCallback(() =>
    messages.map((m) => ({ role: m.role, content: m.content })),
    [messages]
  )

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || isStreaming) return
    setInput('')
    setIsStreaming(true)
    setRoutingInfo(null)

    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: text,
    }
    setMessages((prev) => [...prev, userMsg])

    const asstId = `a-${Date.now()}`
    const asstMsg: ChatMessage = {
      id: asstId,
      role: 'assistant',
      content: '',
      isStreaming: true,
      actions: [],
      delegations: [],
    }
    setMessages((prev) => [...prev, asstMsg])

    try {
      const response = await fetch('/api/v1/assistant/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('ai_tutor_token')}`,
          Accept: 'text/event-stream',
        },
        body: JSON.stringify({ message: text, history: buildHistory() }),
      })

      if (!response.ok || !response.body) {
        throw new Error(`HTTP ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value, { stream: true })
        const lines = chunk.split('\n')

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const payload = line.slice(6).trim()
          if (!payload) continue

          try {
            const event: SseEvent = JSON.parse(payload)

            if (event.type === 'routing') {
              setRoutingInfo({ agent: event.agent!, reason: event.reason!, delegatedFrom: event.delegated_from })
              setMessages((prev) => prev.map((m) =>
                m.id === asstId ? { ...m, agent: event.agent as AgentKey } : m
              ))
            }

            if (event.type === 'token') {
              setMessages((prev) => prev.map((m) =>
                m.id === asstId ? { ...m, content: m.content + (event.content ?? '') } : m
              ))
            }

            if (event.type === 'action') {
              const actionCard: ActionCard = { kind: event.kind!, payload: event.payload! }
              setMessages((prev) => prev.map((m) =>
                m.id === asstId ? { ...m, actions: [...(m.actions ?? []), actionCard] } : m
              ))
              // Auto-navigate for navigate actions
              if (event.kind === 'navigate' && event.payload?.url) {
                setTimeout(() => navigate(event.payload!.url as string), 800)
              }
            }

            if (event.type === 'delegation') {
              const delegation = { from: event.from!, to: event.to!, reason: event.reason! }
              setMessages((prev) => prev.map((m) =>
                m.id === asstId ? { ...m, delegations: [...(m.delegations ?? []), delegation] } : m
              ))
              setRoutingInfo({ agent: event.to!, reason: event.reason!, delegatedFrom: event.from })
            }

            if (event.type === 'guardrail') {
              setMessages((prev) => prev.map((m) =>
                m.id === asstId ? {
                  ...m,
                  content: event.message ?? 'Request blocked.',
                  guardrailBlocked: true,
                  agent: 'guardrail',
                } : m
              ))
            }

            if (event.type === 'error') {
              toast.error(event.message ?? 'Something went wrong')
            }

            if (event.type === 'done') {
              setMessages((prev) => prev.map((m) =>
                m.id === asstId ? { ...m, isStreaming: false } : m
              ))
              setRoutingInfo(null)
            }
          } catch {
            // skip malformed events
          }
        }
      }
    } catch (e) {
      toast.error('Connection error')
      setMessages((prev) => prev.map((m) =>
        m.id === asstId ? { ...m, content: 'Something went wrong. Please try again.', isStreaming: false } : m
      ))
    } finally {
      setIsStreaming(false)
      setRoutingInfo(null)
      inputRef.current?.focus()
    }
  }, [isStreaming, buildHistory, navigate])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage(input)
    }
  }

  const isEmpty = messages.length === 0

  return (
    <PageWrapper>
      <div className="flex flex-col h-[calc(100vh-56px-52px)]">
        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-surface-2/50 shrink-0">
          <div className="max-w-3xl mx-auto flex items-center justify-between">
            <div>
              <h1 className="font-display text-xl text-paper">AI Assistant</h1>
              <p className="text-xs text-paper/40 mt-0.5">
                {Object.keys(AGENT_META).length - 2} specialist agents · strict guardrails · auto-delegation
              </p>
            </div>
            <div className="hidden md:flex flex-wrap gap-1.5">
              {Object.entries(AGENT_META).filter(([k]) => !['guardrail','error'].includes(k)).map(([k, v]) => (
                <span key={k} className="text-xs px-2 py-0.5 rounded-full bg-surface-2 border border-surface-3 text-paper/40">
                  {v.emoji} {v.label}
                </span>
              ))}
            </div>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-6">
          <div className="max-w-3xl mx-auto space-y-6">
            {/* Empty state */}
            {isEmpty && (
              <motion.div
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                className="text-center py-12"
              >
                <div className="text-5xl mb-4">🤖</div>
                <h2 className="font-display text-xl text-paper mb-2">What can I help you with?</h2>
                <p className="text-sm text-paper/50 mb-8 max-w-sm mx-auto">
                  I can answer questions, start quizzes, build course plans, show your progress, and navigate the platform — all from here.
                </p>
                <div className="flex flex-wrap gap-2 justify-center">
                  {QUICK_ACTIONS.map((a) => (
                    <button
                      key={a.label}
                      onClick={() => sendMessage(a.label)}
                      className="flex items-center gap-2 px-3 py-2 rounded-xl bg-surface-2 border border-surface-3 text-sm text-paper/60 hover:text-paper hover:border-violet/40 transition-all"
                    >
                      <span>{a.icon}</span>{a.label}
                    </button>
                  ))}
                </div>
              </motion.div>
            )}

            {/* Chat messages */}
            <AnimatePresence initial={false}>
              {messages.map((msg) => (
                <MessageBubble key={msg.id} msg={msg} />
              ))}
            </AnimatePresence>

            {/* Live routing indicator */}
            <AnimatePresence>
              {routingInfo && (
                <RoutingBadge
                  agent={routingInfo.agent}
                  reason={routingInfo.reason}
                  delegatedFrom={routingInfo.delegatedFrom}
                />
              )}
            </AnimatePresence>

            <div ref={bottomRef} />
          </div>
        </div>

        {/* Input */}
        <div className="px-6 py-4 border-t border-surface-2/50 shrink-0 bg-ink/80 backdrop-blur">
          <div className="max-w-3xl mx-auto flex gap-3">
            <input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask anything — doubts, quizzes, plans, progress…"
              disabled={isStreaming}
              className="flex-1 bg-surface-2 border border-surface-3 rounded-xl px-4 py-3 text-sm text-paper placeholder-paper/30 focus:outline-none focus:ring-2 focus:ring-violet/50 disabled:opacity-50"
            />
            <Button
              onClick={() => sendMessage(input)}
              disabled={isStreaming || !input.trim()}
              isLoading={isStreaming}
            >
              Send
            </Button>
          </div>
          <p className="text-center text-[10px] text-paper/20 mt-2 max-w-3xl mx-auto">
            Requests are routed through strict guardrails · up to 2-level agent delegation
          </p>
        </div>
      </div>
    </PageWrapper>
  )
}

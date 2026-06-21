import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { assistantV2API } from '@/lib/api'
import { useLearnerStore } from '@/stores/learnerStore'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import { Avatar } from '@/components/ui/Avatar'
import { MarkdownMessage } from '@/components/ui/MarkdownMessage'
import { StreamTrace, type AgentStep } from '@/components/agents/StreamTrace'

interface ActionCard {
  kind: string
  payload: Record<string, unknown>
}

interface V2Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  routing?: { agent: string; reason: string }
  steps: AgentStep[]
  actions: ActionCard[]
}

function ActionCardView({ action, onNavigate }: { action: ActionCard; onNavigate: (url: string) => void }) {
  const { kind, payload } = action
  if (kind === 'quiz_created') {
    return (
      <div style={{ marginTop: 10, padding: '12px 14px', background: 'var(--paper-2)', border: '1px solid var(--line-2)', borderRadius: 'var(--r-2)', maxWidth: 340 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
          <Icon name="zap" size={13} style={{ color: 'var(--accent)' }} />
          <span className="t-sm fg-0" style={{ fontWeight: 500 }}>Quiz ready — {String(payload.topic)}</span>
        </div>
        <div className="t-xs fg-2" style={{ marginBottom: 10 }}>
          {String(payload.question_count)} questions · {String(payload.bloom_level)} level
        </div>
        <Button size="sm" variant="primary" onClick={() => onNavigate(String(payload.url))}>
          Take Quiz
        </Button>
      </div>
    )
  }
  if (kind === 'plan_created') {
    return (
      <div style={{ marginTop: 10, padding: '12px 14px', background: 'var(--paper-2)', border: '1px solid var(--line-2)', borderRadius: 'var(--r-2)', maxWidth: 340 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
          <Icon name="book" size={13} style={{ color: 'var(--accent)' }} />
          <span className="t-sm fg-0" style={{ fontWeight: 500 }}>{String(payload.title)}</span>
        </div>
        <div className="t-xs fg-2" style={{ marginBottom: 10 }}>
          {String(payload.module_count)} modules · {String(payload.weeks)} weeks
        </div>
        <Button size="sm" variant="primary" onClick={() => onNavigate(String(payload.url))}>
          View Course
        </Button>
      </div>
    )
  }
  if (kind === 'progress_updated') {
    return (
      <div style={{ marginTop: 10, padding: '12px 14px', background: 'var(--paper-2)', border: '1px solid var(--line-2)', borderRadius: 'var(--r-2)', maxWidth: 340 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
          <Icon name="progress" size={13} style={{ color: 'var(--accent)' }} />
          <span className="t-sm fg-0" style={{ fontWeight: 500 }}>Progress updated</span>
        </div>
        {payload.xp_earned !== undefined && (
          <div className="t-xs fg-2">+{String(payload.xp_earned)} XP earned</div>
        )}
      </div>
    )
  }
  if (kind === 'navigate') {
    return (
      <div style={{ marginTop: 8 }}>
        <Button size="sm" variant="outline" icon="arrow" onClick={() => onNavigate(String(payload.url))}>
          Go to {String(payload.label)}
        </Button>
      </div>
    )
  }
  return null
}

export default function AtelierV2Page() {
  const navigate = useNavigate()
  const { name } = useLearnerStore()
  const [messages, setMessages] = useState<V2Message[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = useCallback(async () => {
    const text = input.trim()
    if (!text || streaming) return
    if (text.length > 2000) { toast.error("Let's keep it under 2,000 characters — try breaking it into a shorter question."); return }
    setInput('')

    const userMsg: V2Message = { id: crypto.randomUUID(), role: 'user', content: text, steps: [], actions: [] }
    setMessages((m) => [...m, userMsg])
    setStreaming(true)

    const assistantId = crypto.randomUUID()
    setMessages((m) => [
      ...m,
      { id: assistantId, role: 'assistant', content: '', streaming: true, steps: [], actions: [] },
    ])

    // Build history from last 6 completed messages
    const history = messages
      .filter((m) => !m.streaming && m.content)
      .slice(-6)
      .map((m) => ({ role: m.role, content: m.content }))

    try {
      await assistantV2API.streamChat(
        text,
        (event) => {
          setMessages((msgs) =>
            msgs.map((msg) => {
              if (msg.id !== assistantId) return msg

              switch (event.type) {
                case 'routing':
                  return { ...msg, routing: { agent: event.agent, reason: event.reason } }

                case 'thought': {
                  const steps = [...msg.steps]
                  const idx = steps.findIndex((s) => s.step === event.step)
                  if (idx >= 0) {
                    steps[idx] = { ...steps[idx], thought: event.content }
                  } else {
                    steps.push({ step: event.step, thought: event.content })
                  }
                  return { ...msg, steps }
                }

                case 'tool_call': {
                  const steps = [...msg.steps]
                  const idx = steps.findIndex((s) => s.step === event.step)
                  const toolCall = { name: event.name, args: event.args }
                  if (idx >= 0) {
                    steps[idx] = { ...steps[idx], toolCall }
                  } else {
                    steps.push({ step: event.step, toolCall })
                  }
                  return { ...msg, steps }
                }

                case 'tool_result': {
                  const steps = [...msg.steps]
                  const idx = steps.findIndex((s) => s.step === event.step)
                  const toolResult = { result: event.result, latency_ms: event.latency_ms }
                  if (idx >= 0) {
                    steps[idx] = { ...steps[idx], toolResult }
                  } else {
                    steps.push({ step: event.step, toolResult })
                  }
                  return { ...msg, steps }
                }

                case 'token':
                  return { ...msg, content: msg.content + event.content }

                case 'action':
                  return { ...msg, actions: [...msg.actions, { kind: event.kind, payload: event.payload }] }

                case 'done':
                  return { ...msg, streaming: false }

                default:
                  return msg
              }
            })
          )

          // Handle error event outside the map
          if (event.type === 'error') {
            toast.error(`Agent error: ${event.message}`)
          }
        },
        history,
      )
      // Ensure streaming is marked false even if 'done' event was missed
      setMessages((m) =>
        m.map((msg) => (msg.id === assistantId ? { ...msg, streaming: false } : msg))
      )
    } catch (err) {
      toast.error('Something went wrong — try again')
      setMessages((m) => m.filter((msg) => msg.id !== assistantId))
    } finally {
      setStreaming(false)
    }
  }, [input, streaming, messages])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="grid h-full grid-cols-1 overflow-hidden lg:grid-cols-[220px_1fr]">
      {/* Left rail */}
      <div className="hidden lg:block" style={{ borderRight: '1px solid var(--line-1)', background: 'var(--paper-1)', overflow: 'auto', padding: 14 }}>
        <div className="caps" style={{ color: 'var(--ink-3)', marginBottom: 8 }}>Try asking</div>
        {[
          'Help me understand transformers',
          'Build me a machine learning course',
          "I'm confused about backpropagation",
          'What are my weakest topics?',
          'Where should I focus next?',
        ].map((t) => (
          <button
            key={t}
            className="t-sm fg-1"
            style={{
              padding: '5px 8px',
              borderRadius: 4,
              cursor: 'pointer',
              width: '100%',
              textAlign: 'left',
              background: 'transparent',
              border: 0,
              fontFamily: 'inherit',
              lineHeight: 1.5,
            }}
            onClick={() => setInput(t)}
            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--paper-2)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
          >
            {t}
          </button>
        ))}

        <div className="caps" style={{ color: 'var(--ink-3)', margin: '20px 0 8px' }}>About Atelier</div>
        <div className="t-xs fg-3" style={{ lineHeight: 1.6, padding: '0 4px' }}>
          Atelier exposes full reasoning traces — routing decisions, tool calls, and latencies — as your answer streams in.
        </div>
      </div>

      {/* Main thread */}
      <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Header */}
        <div style={{ padding: '12px 24px', borderBottom: '1px solid var(--line-1)', display: 'flex', alignItems: 'center', gap: 10 }}>
          <Icon name="sparkle" size={14} style={{ color: 'var(--accent)' }} />
          <span className="t-md fg-0" style={{ fontWeight: 500 }}>AI Atelier</span>
          <Badge tone="warn" size="xs">Beta</Badge>
          <Badge tone="pos" size="xs" dot>tool traces on</Badge>
          <span style={{ flex: 1 }} />
          <Button size="sm" variant="ghost" icon="plus" onClick={() => setMessages([])}>
            New thread
          </Button>
        </div>

        {/* Messages */}
        <div
          style={{ flex: 1, overflowY: 'auto', padding: '24px 32px', maxWidth: 860, width: '100%', margin: '0 auto' }}
        >
          {messages.length === 0 && (
            <div style={{ textAlign: 'center', paddingTop: 80 }}>
              <div
                style={{
                  width: 40,
                  height: 40,
                  borderRadius: 'var(--r-pill)',
                  background: 'var(--ink-0)',
                  color: 'var(--paper-0)',
                  display: 'grid',
                  placeItems: 'center',
                  fontFamily: 'var(--font-serif)',
                  fontSize: 20,
                  fontStyle: 'italic',
                  margin: '0 auto 16px',
                }}
              >
                æ
              </div>
              <div className="serif" style={{ fontSize: 24, color: 'var(--ink-0)' }}>
                What would you like to learn?
              </div>
              <div className="t-md fg-3" style={{ marginTop: 8 }}>
                Ask me anything — you'll see every step of my reasoning as I work through it.
              </div>
            </div>
          )}

          {messages.map((msg) => (
            <div key={msg.id} style={{ marginBottom: 28, display: 'flex', gap: 12 }}>
              {msg.role === 'user' ? (
                <Avatar name={name || 'You'} size={26} />
              ) : (
                <div
                  style={{
                    width: 26,
                    height: 26,
                    borderRadius: 'var(--r-pill)',
                    background: 'var(--ink-0)',
                    color: 'var(--paper-0)',
                    display: 'grid',
                    placeItems: 'center',
                    fontFamily: 'var(--font-serif)',
                    fontSize: 13,
                    fontStyle: 'italic',
                    flexShrink: 0,
                  }}
                >
                  æ
                </div>
              )}

              <div style={{ flex: 1, minWidth: 0 }}>
                {/* Name row */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                  <span className="t-sm fg-0" style={{ fontWeight: 500 }}>
                    {msg.role === 'user' ? name || 'You' : 'Atelier'}
                  </span>
                  {msg.streaming && <Badge tone="pos" size="xs" dot>Writing…</Badge>}
                </div>

                {/* User message */}
                {msg.role === 'user' ? (
                  <div className="t-md fg-1" style={{ lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>
                    {msg.content}
                  </div>
                ) : (
                  <>
                    {/* Agent trace */}
                    {(msg.routing || msg.steps.length > 0) && (
                      <StreamTrace
                        routing={msg.routing}
                        steps={msg.steps}
                        streaming={!!msg.streaming}
                      />
                    )}

                    {/* Answer content */}
                    <MarkdownMessage content={msg.content} streaming={msg.streaming} />

                    {/* Action cards */}
                    {msg.actions.map((action, i) => (
                      <ActionCardView key={i} action={action} onNavigate={(url) => navigate(url)} />
                    ))}

                    {/* Feedback row */}
                    {!msg.streaming && msg.content && (
                      <div style={{ display: 'flex', gap: 4, marginTop: 12 }}>
                        <Button size="xs" variant="outline" icon="check">Helpful</Button>
                        <Button
                          size="xs"
                          variant="ghost"
                          onClick={() => {
                            navigator.clipboard.writeText(msg.content).then(() => toast.success('Copied'))
                          }}
                        >
                          Copy
                        </Button>
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          ))}

          <div ref={bottomRef} />
        </div>

        {/* Composer */}
        <div style={{ padding: 16, borderTop: '1px solid var(--line-1)', background: 'var(--paper-0)', flexShrink: 0 }}>
          <div style={{ maxWidth: 860, margin: '0 auto' }}>
            <div
              style={{
                background: 'var(--paper-1)',
                border: '1px solid var(--line-2)',
                borderRadius: 'var(--r-3)',
                padding: 8,
              }}
            >
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="What would you like to learn today?"
                rows={3}
                maxLength={2000}
                style={{
                  width: '100%',
                  background: 'transparent',
                  border: 0,
                  outline: 'none',
                  resize: 'none',
                  fontSize: 14,
                  color: 'var(--ink-0)',
                  fontFamily: 'inherit',
                  lineHeight: 1.5,
                }}
              />
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
                <span style={{ flex: 1 }} />
                {input.length > 1600 && (
                  <span className="t-xs" style={{ color: input.length > 1900 ? 'var(--neg)' : 'var(--ink-3)' }}>
                    {input.length}/2000
                  </span>
                )}
                <span className="hidden sm:inline t-xs fg-3">
                  <kbd>⌘</kbd><kbd>↵</kbd> to send
                </span>
                <Button size="sm" variant="primary" icon="send" onClick={sendMessage} loading={streaming}>
                  Send
                </Button>
              </div>
            </div>
            <div className="t-xs fg-3" style={{ textAlign: 'center', marginTop: 6 }}>
              You can always ask me to explain my reasoning in plain language.
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

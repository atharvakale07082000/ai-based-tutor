import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import toast from 'react-hot-toast'
import { chatAPI } from '@/lib/api'
import { useLearnerStore } from '@/stores/learnerStore'
import {
  useChatStore,
  type ChatMessage as V2Message,
  type ChatAction as ActionCard,
} from '@/stores/chatStore'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import { Avatar } from '@/components/ui/Avatar'
import { MarkdownMessage } from '@/components/ui/MarkdownMessage'
import { ReasoningStream } from '@/components/agents/ReasoningStream'
import { useSpeechInput } from '@/hooks/useSpeechInput'

function relativeTime(ts: number): string {
  const diff = Date.now() - ts
  const min = Math.floor(diff / 60000)
  if (min < 1) return 'just now'
  if (min < 60) return `${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}h ago`
  const day = Math.floor(hr / 24)
  return day === 1 ? 'yesterday' : `${day}d ago`
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
  const location = useLocation()
  const prefill = (location.state as { prefill?: string } | null)?.prefill ?? ''
  const { name } = useLearnerStore()
  const [messages, setMessages] = useState<V2Message[]>([])
  const [input, setInput] = useState(prefill)
  const [streaming, setStreaming] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const dirtyRef = useRef(false)
  const initRef = useRef(false)

  // Chat history (client-side, persisted). See stores/chatStore.
  const threads = useChatStore((s) => s.threads)
  const activeId = useChatStore((s) => s.activeId)

  const { isListening, isSupported: isSpeechSupported, toggle: toggleVoice } = useSpeechInput({
    onInterim: (text) => setInput(text),
    onFinal: (text) => { setInput(text); toast.success('Heard you!', { icon: '🎤', duration: 2000 }) },
  })

  useEffect(() => {
    if (prefill) inputRef.current?.focus()
  }, []) // intentionally only on mount

  // On mount: load the last active chat, or start a fresh one.
  useEffect(() => {
    if (initRef.current) return
    initRef.current = true
    const st = useChatStore.getState()
    const existing = st.activeId ? st.threads.find((t) => t.id === st.activeId) : null
    if (existing) {
      setMessages(existing.messages)
    } else if (st.threads.length > 0) {
      st.setActive(st.threads[0].id)
      setMessages(st.threads[0].messages)
    } else {
      st.newThread()
    }
  }, [])

  // Persist the active chat once an exchange finishes (never mid-stream).
  useEffect(() => {
    if (streaming || !dirtyRef.current || messages.length === 0) return
    useChatStore.getState().saveActive(messages, 'done')
    dirtyRef.current = false
  }, [messages, streaming])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const startNewChat = () => {
    setHistoryOpen(false)
    if (streaming || messages.length === 0) return // already on a fresh chat (or busy)
    useChatStore.getState().newThread()
    setMessages([])
  }

  const selectThread = (id: string) => {
    setHistoryOpen(false)
    if (streaming || id === activeId) return
    const st = useChatStore.getState()
    const t = st.threads.find((thread) => thread.id === id)
    if (!t) return
    st.setActive(id)
    dirtyRef.current = false
    setMessages(t.messages)
  }

  const removeThread = (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (streaming && id === activeId) return // don't delete a chat that's mid-answer
    const before = useChatStore.getState()
    const wasActive = before.activeId === id
    before.deleteThread(id)
    if (!wasActive) return
    const st = useChatStore.getState()
    const next = st.activeId ? st.threads.find((t) => t.id === st.activeId) : null
    if (next) {
      setMessages(next.messages)
    } else {
      st.newThread()
      setMessages([])
    }
    dirtyRef.current = false
  }

  const sendMessage = useCallback(async () => {
    const text = input.trim()
    if (!text || streaming) return
    if (text.length > 2000) { toast.error("Let's keep it under 2,000 characters — try breaking it into a shorter question."); return }
    setInput('')
    dirtyRef.current = true // this exchange should be persisted to history when it finishes

    const userMsg: V2Message = { id: crypto.randomUUID(), role: 'user', content: text, reasoning: '', actions: [] }
    setMessages((m) => [...m, userMsg])
    setStreaming(true)

    const assistantId = crypto.randomUUID()
    setMessages((m) => [
      ...m,
      { id: assistantId, role: 'assistant', content: '', streaming: true, reasoning: '', actions: [] },
    ])

    // Build history from last 6 completed messages (full content — the backend has no length cap).
    const history = messages
      .filter((m) => !m.streaming && m.content)
      .slice(-6)
      .map((m) => ({ role: m.role, content: m.content }))

    try {
      await chatAPI.streamChat(
        text,
        (event) => {
          setMessages((msgs) =>
            msgs.map((msg) => {
              if (msg.id !== assistantId) return msg

              switch (event.type) {
                case 'reasoning':
                  return { ...msg, reasoning: msg.reasoning + event.content }

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
        undefined,
        // Stable thread id → server-side persistent memory for this chat.
        useChatStore.getState().activeId ?? undefined,
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
      {/* Chat history drawer (burger menu) */}
      {historyOpen && (
        <>
          <div
            onClick={() => setHistoryOpen(false)}
            style={{ position: 'fixed', inset: 0, background: 'rgba(20,17,13,0.35)', zIndex: 60 }}
          />
          <aside
            className="fade-in"
            style={{
              position: 'fixed', top: 0, left: 0, bottom: 0, width: 300, maxWidth: '85vw',
              background: 'var(--paper-0)', borderRight: '1px solid var(--line-1)',
              boxShadow: 'var(--shadow-4)', zIndex: 61, display: 'flex', flexDirection: 'column',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '14px 16px', borderBottom: '1px solid var(--line-1)' }}>
              <Icon name="chat" size={14} style={{ color: 'var(--accent)' }} />
              <span className="t-md fg-0" style={{ fontWeight: 600, flex: 1 }}>Chats</span>
              <button onClick={() => setHistoryOpen(false)} aria-label="Close" style={{ display: 'inline-flex', padding: 4, cursor: 'pointer', background: 'transparent', border: 0 }}>
                <Icon name="x" size={14} style={{ color: 'var(--ink-2)' }} />
              </button>
            </div>
            <div style={{ padding: 10 }}>
              <Button size="sm" variant="outline" icon="plus" onClick={startNewChat} style={{ width: '100%' }}>
                New chat
              </Button>
            </div>
            <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px 12px' }}>
              {threads.length === 0 && (
                <div className="t-xs fg-3" style={{ padding: 12, textAlign: 'center' }}>No chats yet.</div>
              )}
              {threads.map((t) => {
                const isActive = t.id === activeId
                const isRunning = streaming && isActive
                return (
                  <button
                    key={t.id}
                    onClick={() => selectThread(t.id)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left',
                      padding: '9px 10px', marginBottom: 2, borderRadius: 'var(--r-2)', cursor: 'pointer',
                      background: isActive ? 'var(--paper-2)' : 'transparent',
                      border: isActive ? '1px solid var(--line-1)' : '1px solid transparent',
                    }}
                    onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = 'var(--paper-1)' }}
                    onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = 'transparent' }}
                  >
                    <span
                      className={isRunning ? 'pulse-dot' : ''}
                      style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0, background: isRunning ? 'var(--accent)' : 'var(--pos)' }}
                    />
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <span className="t-sm fg-0" style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: isActive ? 500 : 400 }}>
                        {t.title}
                      </span>
                      <span className="t-xs fg-3" style={{ display: 'block' }}>
                        {isRunning ? 'running…' : relativeTime(t.updatedAt)}
                      </span>
                    </span>
                    <span
                      role="button"
                      aria-label="Delete chat"
                      title="Delete"
                      onClick={(e) => removeThread(t.id, e)}
                      style={{ display: 'inline-flex', padding: 4, borderRadius: 4, flexShrink: 0, opacity: 0.6 }}
                      onMouseEnter={(e) => (e.currentTarget.style.opacity = '1')}
                      onMouseLeave={(e) => (e.currentTarget.style.opacity = '0.6')}
                    >
                      <Icon name="trash" size={12} style={{ color: 'var(--ink-3)' }} />
                    </span>
                  </button>
                )
              })}
            </div>
          </aside>
        </>
      )}

      {/* Left rail */}
      <div className="hidden lg:block" style={{ borderRight: '1px solid var(--line-1)', background: 'var(--paper-1)', overflow: 'auto', padding: 14 }}>
        <div className="eyebrow" style={{ marginBottom: 8 }}>// try asking</div>
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

        <div className="eyebrow" style={{ margin: '20px 0 8px' }}>// about atelier</div>
        <div className="t-xs fg-3" style={{ lineHeight: 1.6, padding: '0 4px' }}>
          Atelier shows its reasoning — how it's thinking through your question — as the answer streams in.
        </div>
      </div>

      {/* Main thread */}
      <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Header */}
        <div style={{ padding: '12px 24px', borderBottom: '1px solid var(--line-1)', display: 'flex', alignItems: 'center', gap: 10 }}>
          <button
            onClick={() => setHistoryOpen(true)}
            aria-label="Chat history"
            title="Chat history"
            style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              width: 30, height: 30, borderRadius: 'var(--r-2)',
              background: 'transparent', border: '1px solid var(--line-1)', cursor: 'pointer',
            }}
          >
            <Icon name="menu" size={15} style={{ color: 'var(--ink-1)' }} />
          </button>
          <Icon name="sparkle" size={14} style={{ color: 'var(--accent)' }} />
          <span className="t-md fg-0" style={{ fontWeight: 500 }}>AI Atelier</span>
          <Badge tone="warn" size="xs">Beta</Badge>
          <Badge tone="pos" size="xs" dot>shows its reasoning</Badge>
          <span style={{ flex: 1 }} />
          <Button size="sm" variant="ghost" icon="plus" onClick={startNewChat}>
            New chat
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
                  fontFamily: 'var(--font-display)',
                  fontSize: 18,
                  fontWeight: 700,
                  letterSpacing: '-0.04em',
                  margin: '0 auto 16px',
                }}
              >
                æ
              </div>
              <div className="eyebrow" style={{ marginBottom: 8 }}>// six agents, one thread</div>
              <div className="display" style={{ fontSize: 26, fontWeight: 600, color: 'var(--ink-0)', letterSpacing: '-0.03em' }}>
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
                    fontFamily: 'var(--font-display)',
                    fontSize: 12,
                    fontWeight: 700,
                    letterSpacing: '-0.04em',
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
                    {/* Live reasoning — how the agent is thinking through it */}
                    <ReasoningStream
                      segments={msg.reasoning ? [{ text: msg.reasoning }] : []}
                      active={!!msg.streaming && !msg.content}
                    />

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
                {isSpeechSupported && (
                  <Button
                    size="xs"
                    variant={isListening ? 'secondary' : 'ghost'}
                    icon="mic"
                    onClick={toggleVoice}
                    style={isListening ? { color: 'var(--neg)', animation: 'pulse 1s ease-in-out infinite' } : undefined}
                  >
                    {isListening ? 'Listening…' : 'Voice'}
                  </Button>
                )}
                <span style={{ flex: 1 }} />
                {input.length > 1600 && (
                  <span className="t-xs" style={{ color: input.length > 1900 ? 'var(--neg)' : 'var(--ink-3)' }}>
                    {input.length}/2000
                  </span>
                )}
                <span className="hidden sm:inline t-xs fg-3">
                  <kbd>⌘</kbd><kbd>↵</kbd> to send
                </span>
                <Button size="sm" variant="signal" icon="send" onClick={sendMessage} loading={streaming}>
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

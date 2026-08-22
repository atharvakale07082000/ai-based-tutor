import { useState, useRef, useEffect, useCallback, type CSSProperties } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import toast from 'react-hot-toast'
import { chatAPI, isAbortError } from '@/lib/api'
import { useLearnerStore } from '@/stores/learnerStore'
import {
  useChatStore,
  DEFAULT_TITLE,
  type ChatMessage as V2Message,
  type ChatAction as ActionCard,
  type ChatRevision,
  type ChatThread,
} from '@/stores/chatStore'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import { Avatar } from '@/components/ui/Avatar'
import { MarkdownMessage } from '@/components/ui/MarkdownMessage'
import { ReasoningStream } from '@/components/agents/ReasoningStream'
import { useSpeechInput } from '@/hooks/useSpeechInput'

const MAX_CHARS = 2000
const TOO_LONG = "Let's keep it under 2,000 characters — try breaking it into a shorter question."
const STREAM_FAILED = "That answer didn't come through."

/**
 * Regenerate / edit-and-resend only rewrite what the learner *sees*. The thread's
 * server-side memory is keyed by its id (sent as `X-Session-Id`) and the backend
 * reads that memory instead of the history we post, so the superseded turn is still
 * in the model's context. Say so rather than implying it was erased.
 */
const REVISION_NOTE: Record<ChatRevision, string> = {
  edited: 'Edited and resent — Atelier still has your original wording in this chat’s memory.',
  regenerated: 'Regenerated — Atelier still has its earlier answer in this chat’s memory.',
}

// ≥44px touch target for the icon-only chat controls in the history drawer.
const iconButtonStyle: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  width: 44,
  height: 44,
  flexShrink: 0,
  padding: 0,
  background: 'transparent',
  border: 0,
  borderRadius: 'var(--r-2)',
  cursor: 'pointer',
  opacity: 0.65,
  transition: 'opacity var(--dur-fast)',
}

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

function RevisionNote({ kind }: { kind?: ChatRevision }) {
  if (!kind) return null
  return (
    <div className="t-xs fg-3" style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6 }}>
      <Icon name="info" size={11} style={{ color: 'var(--ink-3)', flexShrink: 0 }} />
      <span>{REVISION_NOTE[kind]}</span>
    </div>
  )
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
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editDraft, setEditDraft] = useState('')
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const dirtyRef = useRef(false)
  const initRef = useRef(false)
  // Mirrors of state that callbacks read without re-binding on every render.
  const messagesRef = useRef<V2Message[]>([])
  const streamingRef = useRef(false)
  const abortRef = useRef<AbortController | null>(null)
  const renameCancelledRef = useRef(false)

  // Chat history (client-side, persisted). See stores/chatStore.
  const threads = useChatStore((s) => s.threads)
  const activeId = useChatStore((s) => s.activeId)

  const { isListening, isSupported: isSpeechSupported, toggle: toggleVoice } = useSpeechInput({
    onInterim: (text) => setInput(text),
    onFinal: (text) => { setInput(text); toast.success('Heard you!', { icon: '🎤', duration: 2000 }) },
  })

  useEffect(() => {
    if (prefill) inputRef.current?.focus()
  }, [prefill])

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

  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  // Persist the active chat once an exchange finishes (never mid-stream).
  useEffect(() => {
    if (streaming || !dirtyRef.current || messages.length === 0) return
    useChatStore.getState().saveActive(messages, 'done')
    dirtyRef.current = false
  }, [messages, streaming])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Unmounting mid-answer (navigation) is a stop, not a loss: cancel the request and
  // salvage whatever streamed, since the persist effect above can no longer run.
  useEffect(() => {
    return () => {
      abortRef.current?.abort()
      if (!streamingRef.current) return
      streamingRef.current = false
      const salvaged = messagesRef.current.flatMap<V2Message>((m) => {
        if (!m.streaming) return [m]
        return m.content || m.reasoning ? [{ ...m, streaming: false, stopped: true }] : []
      })
      if (dirtyRef.current && salvaged.length > 0) {
        useChatStore.getState().saveActive(salvaged, 'done')
        dirtyRef.current = false
      }
    }
  }, [])

  /**
   * Run one turn: `base` is the full message list ending in the user turn to answer.
   * Everything after it is dropped, which is how retry / regenerate / edit rewind.
   */
  const runTurn = useCallback(async (text: string, base: V2Message[], revision?: ChatRevision) => {
    const assistantId = crypto.randomUUID()
    dirtyRef.current = true // this exchange should be persisted to history when it finishes
    setMessages([
      ...base,
      {
        id: assistantId,
        role: 'assistant',
        content: '',
        streaming: true,
        reasoning: '',
        actions: [],
        ...(revision === 'regenerated' ? { revised: revision } : {}),
      },
    ])
    setStreaming(true)
    streamingRef.current = true

    const controller = new AbortController()
    abortRef.current = controller

    // Last 6 completed turns. The backend ignores this whenever X-Session-Id is set
    // (it reads the thread's own persistent memory instead) — we still send it so the
    // call stays correct if the session header is ever dropped.
    const history = base
      .filter((m) => !m.streaming && m.content)
      .slice(-6)
      .map((m) => ({ role: m.role, content: m.content }))

    // Held in an object: a plain `let` assigned inside the event callback would be
    // narrowed back to its initial value by control-flow analysis at the read site.
    const failure: { message: string | null } = { message: null }

    try {
      await chatAPI.streamChat(
        text,
        (event) => {
          if (event.type === 'error') {
            failure.message = event.message || STREAM_FAILED
            return
          }
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
        },
        history,
        undefined,
        // Stable thread id → server-side persistent memory for this chat.
        useChatStore.getState().activeId ?? undefined,
        { signal: controller.signal },
      )
    } catch (err) {
      // An aborted stream resolves quietly, so anything landing here is a real failure.
      if (!isAbortError(err)) failure.message = STREAM_FAILED
    } finally {
      const aborted = controller.signal.aborted
      abortRef.current = null
      streamingRef.current = false
      setMessages((msgs) =>
        msgs.flatMap<V2Message>((msg) => {
          if (msg.id !== assistantId) return [msg]
          const stopped = aborted && !!msg.streaming
          // Stopped before a single token arrived — drop the empty bubble.
          if (stopped && !msg.content && !msg.reasoning) return []
          return [{
            ...msg,
            streaming: false,
            ...(stopped ? { stopped: true } : {}),
            ...(failure.message ? { error: failure.message } : {}),
          }]
        })
      )
      setStreaming(false)
    }
  }, [])

  const sendMessage = useCallback(() => {
    const text = input.trim()
    if (!text || streamingRef.current) return
    if (text.length > MAX_CHARS) { toast.error(TOO_LONG); return }
    setInput('')
    const userMsg: V2Message = { id: crypto.randomUUID(), role: 'user', content: text, reasoning: '', actions: [] }
    void runTurn(text, [...messagesRef.current, userMsg])
  }, [input, runTurn])

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  /** Re-answer the user turn preceding `assistantId`, discarding everything after it. */
  const rerun = useCallback((assistantId: string, revision?: ChatRevision) => {
    if (streamingRef.current) return
    const msgs = messagesRef.current
    const idx = msgs.findIndex((m) => m.id === assistantId)
    if (idx < 0) return
    let userIdx = -1
    for (let i = idx - 1; i >= 0; i -= 1) {
      if (msgs[i].role === 'user') { userIdx = i; break }
    }
    if (userIdx < 0) return
    void runTurn(msgs[userIdx].content, msgs.slice(0, userIdx + 1), revision)
  }, [runTurn])

  const beginEdit = (msg: V2Message) => {
    if (streamingRef.current) return
    setEditingId(msg.id)
    setEditDraft(msg.content)
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditDraft('')
  }

  const submitEdit = useCallback(() => {
    const text = editDraft.trim()
    if (!text || !editingId || streamingRef.current) return
    if (text.length > MAX_CHARS) { toast.error(TOO_LONG); return }
    const msgs = messagesRef.current
    const idx = msgs.findIndex((m) => m.id === editingId)
    setEditingId(null)
    setEditDraft('')
    if (idx < 0) return
    const edited: V2Message = {
      ...msgs[idx],
      id: crypto.randomUUID(),
      content: text,
      revised: 'edited',
      stopped: false,
      error: undefined,
    }
    void runTurn(text, [...msgs.slice(0, idx), edited])
  }, [editDraft, editingId, runTurn])

  const startNewChat = () => {
    setHistoryOpen(false)
    cancelEdit()
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
    cancelEdit()
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
    cancelEdit()
    if (next) {
      setMessages(next.messages)
    } else {
      st.newThread()
      setMessages([])
    }
    dirtyRef.current = false
  }

  const beginRename = (t: ChatThread, e?: React.MouseEvent) => {
    e?.stopPropagation()
    renameCancelledRef.current = false
    setRenamingId(t.id)
    setRenameDraft(t.title === DEFAULT_TITLE ? '' : t.title)
  }

  const finishRename = (commit: boolean) => {
    if (commit && renamingId) useChatStore.getState().renameThread(renamingId, renameDraft)
    setRenamingId(null)
    setRenameDraft('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault()
      sendMessage()
      return
    }
    if (e.key === 'Escape' && streaming) {
      e.preventDefault()
      stopStreaming()
    }
  }

  // Retry/Regenerate belong to the turn at the end of the thread.
  let lastAssistantId: string | null = null
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].role === 'assistant') { lastAssistantId = messages[i].id; break }
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
                const isRenaming = renamingId === t.id
                return (
                  <div
                    key={t.id}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 2, width: '100%',
                      marginBottom: 2, borderRadius: 'var(--r-2)',
                      background: isActive ? 'var(--paper-2)' : 'transparent',
                      border: isActive ? '1px solid var(--line-1)' : '1px solid transparent',
                    }}
                    onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = 'var(--paper-1)' }}
                    onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = 'transparent' }}
                  >
                    {isRenaming ? (
                      <input
                        autoFocus
                        value={renameDraft}
                        aria-label="Chat name"
                        placeholder={DEFAULT_TITLE}
                        maxLength={44}
                        onChange={(e) => setRenameDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') { e.preventDefault(); e.currentTarget.blur() }
                          if (e.key === 'Escape') { e.preventDefault(); renameCancelledRef.current = true; e.currentTarget.blur() }
                        }}
                        onBlur={() => {
                          const cancelled = renameCancelledRef.current
                          renameCancelledRef.current = false
                          finishRename(!cancelled)
                        }}
                        className="t-sm fg-0"
                        style={{
                          flex: 1, minWidth: 0, minHeight: 44, margin: 2, padding: '0 10px',
                          background: 'var(--paper-0)', border: '1px solid var(--accent)',
                          borderRadius: 'var(--r-2)', outline: 'none', fontFamily: 'inherit',
                          color: 'var(--ink-0)',
                        }}
                      />
                    ) : (
                      <>
                        <button
                          onClick={() => selectThread(t.id)}
                          onDoubleClick={(e) => beginRename(t, e)}
                          title={t.title}
                          style={{
                            display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0,
                            minHeight: 44, padding: '6px 8px', textAlign: 'left', cursor: 'pointer',
                            background: 'transparent', border: 0, borderRadius: 'var(--r-2)',
                            fontFamily: 'inherit',
                          }}
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
                        </button>
                        <button
                          onClick={(e) => beginRename(t, e)}
                          aria-label={`Rename chat: ${t.title}`}
                          title="Rename"
                          style={iconButtonStyle}
                          onMouseEnter={(e) => (e.currentTarget.style.opacity = '1')}
                          onMouseLeave={(e) => (e.currentTarget.style.opacity = '0.65')}
                          onFocus={(e) => (e.currentTarget.style.opacity = '1')}
                          onBlur={(e) => (e.currentTarget.style.opacity = '0.65')}
                        >
                          <Icon name="edit" size={12} style={{ color: 'var(--ink-3)' }} />
                        </button>
                        <button
                          onClick={(e) => removeThread(t.id, e)}
                          aria-label={`Delete chat: ${t.title}`}
                          title="Delete"
                          disabled={isRunning}
                          style={{ ...iconButtonStyle, cursor: isRunning ? 'not-allowed' : 'pointer', opacity: isRunning ? 0.3 : 0.65 }}
                          onMouseEnter={(e) => { if (!isRunning) e.currentTarget.style.opacity = '1' }}
                          onMouseLeave={(e) => { if (!isRunning) e.currentTarget.style.opacity = '0.65' }}
                          onFocus={(e) => { if (!isRunning) e.currentTarget.style.opacity = '1' }}
                          onBlur={(e) => { if (!isRunning) e.currentTarget.style.opacity = '0.65' }}
                        >
                          <Icon name="trash" size={12} style={{ color: 'var(--ink-3)' }} />
                        </button>
                      </>
                    )}
                  </div>
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
          Six specialists share one thread, so you can move from a question to a quiz to a plan
          without repeating yourself. When Atelier works something out before answering, it shows
          you that thinking too.
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
          {/* No "shows its reasoning" badge: the model emits the <reasoning> note on some turns
              and not others, so an always-on claim promised a guarantee we cannot keep. The
              panel below appears when there is reasoning and stays silent when there isn't. */}
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
                Ask me anything — I can explain a concept, build you a plan, or quiz you on it.
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
                  {msg.stopped && !msg.streaming && <Badge tone="warn" size="xs">Stopped</Badge>}
                  {msg.error && !msg.streaming && <Badge tone="neg" size="xs">Failed</Badge>}
                </div>

                {/* User message */}
                {msg.role === 'user' ? (
                  editingId === msg.id ? (
                    <div style={{ background: 'var(--paper-1)', border: '1px solid var(--line-2)', borderRadius: 'var(--r-2)', padding: 8 }}>
                      <textarea
                        autoFocus
                        value={editDraft}
                        aria-label="Edit your message"
                        rows={3}
                        maxLength={MAX_CHARS}
                        onChange={(e) => setEditDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Escape') { e.preventDefault(); cancelEdit() }
                          if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); submitEdit() }
                        }}
                        style={{
                          width: '100%', background: 'transparent', border: 0, outline: 'none',
                          resize: 'none', fontSize: 14, color: 'var(--ink-0)', fontFamily: 'inherit',
                          lineHeight: 1.5,
                        }}
                      />
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4, flexWrap: 'wrap' }}>
                        <span className="t-xs fg-3" style={{ flex: 1, minWidth: 140 }}>
                          Resending replaces every turn after this one.
                        </span>
                        <Button size="sm" variant="ghost" onClick={cancelEdit}>Cancel</Button>
                        <Button
                          size="sm"
                          variant="signal"
                          icon="send"
                          onClick={submitEdit}
                          disabled={!editDraft.trim() || streaming}
                        >
                          Resend
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="t-md fg-1" style={{ lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>
                        {msg.content}
                      </div>
                      <RevisionNote kind={msg.revised} />
                      <div style={{ display: 'flex', gap: 4, marginTop: 8 }}>
                        <Button
                          size="xs"
                          variant="ghost"
                          icon="edit"
                          disabled={streaming}
                          title="Edit this message and resend it"
                          onClick={() => beginEdit(msg)}
                        >
                          Edit
                        </Button>
                      </div>
                    </>
                  )
                ) : (
                  <>
                    {/* Live reasoning — how the agent is thinking through it */}
                    <ReasoningStream
                      segments={msg.reasoning ? [{ text: msg.reasoning }] : []}
                      active={!!msg.streaming && !msg.content}
                    />

                    {/* Answer content */}
                    <MarkdownMessage content={msg.content} streaming={msg.streaming} />

                    <RevisionNote kind={msg.revised} />

                    {/* Stopped mid-answer — say so, so a partial answer isn't read as complete */}
                    {msg.stopped && !msg.streaming && !msg.error && (
                      <div className="t-xs fg-3" style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8 }}>
                        <Icon name="pause" size={11} style={{ color: 'var(--ink-3)', flexShrink: 0 }} />
                        <span>You stopped this answer, so it breaks off early.</span>
                      </div>
                    )}

                    {/* Action cards */}
                    {msg.actions.map((action, i) => (
                      <ActionCardView key={i} action={action} onNavigate={(url) => navigate(url)} />
                    ))}

                    {/* Failed turn — one click puts it back on the wire */}
                    {msg.error && !msg.streaming && (
                      <div
                        style={{
                          marginTop: 10, padding: '10px 12px', background: 'var(--neg-soft)',
                          border: '1px solid var(--line-2)', borderRadius: 'var(--r-2)',
                          display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
                        }}
                      >
                        <Icon name="alert" size={13} style={{ color: 'var(--neg)', flexShrink: 0 }} />
                        <span className="t-sm" style={{ color: 'var(--neg)', flex: 1, minWidth: 140 }}>
                          {msg.error}
                        </span>
                        <Button
                          size="sm"
                          variant="outline"
                          icon="refresh"
                          disabled={streaming}
                          onClick={() => rerun(msg.id)}
                        >
                          Retry
                        </Button>
                      </div>
                    )}

                    {/* Message actions. No "Helpful" button until there is somewhere to send
                        the rating — it had no handler, so it collected nothing while looking
                        like it did. */}
                    {!msg.streaming && msg.content && !msg.error && (
                      <div style={{ display: 'flex', gap: 4, marginTop: 12, flexWrap: 'wrap' }}>
                        <Button
                          size="xs"
                          variant="ghost"
                          onClick={() => {
                            navigator.clipboard.writeText(msg.content).then(() => toast.success('Copied'))
                          }}
                        >
                          Copy
                        </Button>
                        {msg.id === lastAssistantId && (
                          <Button
                            size="xs"
                            variant="ghost"
                            icon="refresh"
                            disabled={streaming}
                            title="Answer this question again"
                            onClick={() => rerun(msg.id, 'regenerated')}
                          >
                            Regenerate
                          </Button>
                        )}
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
                maxLength={MAX_CHARS}
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
                  {streaming ? <><kbd>esc</kbd> to stop</> : <><kbd>⌘</kbd><kbd>↵</kbd> to send</>}
                </span>
                {streaming ? (
                  <Button
                    size="sm"
                    variant="outline"
                    icon="x"
                    onClick={stopStreaming}
                    aria-label="Stop generating"
                    title="Stop generating — the partial answer is kept"
                  >
                    Stop
                  </Button>
                ) : (
                  <Button size="sm" variant="signal" icon="send" onClick={sendMessage} aria-label="Send message">
                    Send
                  </Button>
                )}
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

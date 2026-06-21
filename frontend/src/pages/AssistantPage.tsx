import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import toast from 'react-hot-toast'
import { assistantAPI } from '@/lib/api'
import { useLearnerStore } from '@/stores/learnerStore'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import { Avatar } from '@/components/ui/Avatar'
import { AgentPill } from '@/components/ui/AgentPill'
import { MarkdownMessage } from '@/components/ui/MarkdownMessage'
import { useAgentStore } from '@/stores/agentStore'
import { useSpeechInput } from '@/hooks/useSpeechInput'

interface ActionCard {
  kind: string
  payload: Record<string, unknown>
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  actions?: ActionCard[]
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
  if (kind === 'navigate') {
    return (
      <div style={{ marginTop: 8 }}>
        <Button size="sm" variant="outline" icon="arrow-right" onClick={() => onNavigate(String(payload.url))}>
          Go to {String(payload.label)}
        </Button>
      </div>
    )
  }
  return null
}

export default function AssistantPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const prefill = (location.state as { prefill?: string } | null)?.prefill ?? ''
  const { name } = useLearnerStore()
  const agents = useAgentStore((s) => s.agents)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState(prefill)
  const [streaming, setStreaming] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const { isListening, isSupported: isSpeechSupported, toggle: toggleVoice } = useSpeechInput({
    onInterim: (text) => setInput(text),
    onFinal: (text) => { setInput(text); toast.success('Heard you!', { icon: '🎤', duration: 2000 }) },
  })

  // Focus input and auto-send when pre-filled from a trend chip
  useEffect(() => {
    if (prefill) {
      inputRef.current?.focus()
    }
  }, []) // intentionally only on mount

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  const sendMessage = useCallback(async () => {
    const text = input.trim()
    if (!text || streaming) return
    if (text.length > 2000) { toast.error("Let's keep it under 2,000 characters — try breaking it into a shorter question."); return }
    setInput('')
    const userMsg: Message = { id: crypto.randomUUID(), role: 'user', content: text }
    setMessages((m) => [...m, userMsg])
    setStreaming(true)

    const assistantId = crypto.randomUUID()
    setMessages((m) => [...m, { id: assistantId, role: 'assistant', content: '', streaming: true, actions: [] }])

    try {
      let full = ''
      // Build history from prior completed messages for multi-turn context
      const history = messages
        .filter((m) => !m.streaming && m.content)
        .map((m) => ({ role: m.role, content: m.content }))

      await assistantAPI.streamChat(
        text,
        (chunk: string) => {
          full += chunk
          setMessages((m) => m.map((msg) => msg.id === assistantId ? { ...msg, content: full } : msg))
        },
        (kind: string, payload: Record<string, unknown>) => {
          setMessages((m) => m.map((msg) =>
            msg.id === assistantId
              ? { ...msg, actions: [...(msg.actions ?? []), { kind, payload }] }
              : msg
          ))
          // Auto-navigate for navigate actions
          if (kind === 'navigate' && payload.url) {
            setTimeout(() => navigate(String(payload.url)), 800)
          }
        },
        history,
      )
      setMessages((m) => m.map((msg) => msg.id === assistantId ? { ...msg, streaming: false } : msg))
    } catch {
      toast.error('Assistant error — try again')
      setMessages((m) => m.filter((msg) => msg.id !== assistantId))
    } finally {
      setStreaming(false)
    }
  }, [input, streaming, navigate])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); sendMessage() }
  }

  const agentList = [
    { kind: 'curr'  as const, label: 'Curriculum', status: agents.curriculum?.status },
    { kind: 'quiz'  as const, label: 'Quiz Creator',       status: agents.quiz?.status },
    { kind: 'prog'  as const, label: 'Progress',           status: agents.progress?.status },
    { kind: 'doubt' as const, label: 'Learning Assistant', status: agents.doubt?.status },
  ]

  return (
    <div className="grid h-full grid-cols-1 overflow-hidden lg:grid-cols-[240px_1fr]">
      {/* Left rail */}
      <div className="hidden lg:block" style={{ borderRight: '1px solid var(--line-1)', background: 'var(--paper-1)', overflow: 'auto', padding: 14 }}>
        <div className="caps" style={{ color: 'var(--ink-3)', marginBottom: 8 }}>Active agents</div>
        {agentList.map((a) => (
          <div key={a.kind} style={{ padding: 10, borderRadius: 'var(--r-2)', background: 'var(--paper-0)', border: '1px solid var(--line-1)', marginBottom: 6 }}>
            <AgentPill kind={a.kind} state={a.status === 'active' ? 'active' : 'idle'} />
            <div className="t-xs fg-3" style={{ marginTop: 4 }}>
              {a.status === 'active' ? 'Working…' : a.status === 'processing' ? 'Thinking…' : 'Ready'}
            </div>
          </div>
        ))}

        <div className="caps" style={{ color: 'var(--ink-3)', margin: '16px 0 8px' }}>Try asking</div>
        {[
          'Help me understand PCA',
          'Build me a Python learning plan',
          'Can you break down gradient descent?',
          'How am I doing so far?',
          'What should I learn next?',
        ].map((t) => (
          <button
            key={t}
            className="t-sm fg-1"
            style={{ padding: '5px 8px', borderRadius: 4, cursor: 'pointer', width: '100%', textAlign: 'left', background: 'transparent', border: 0, fontFamily: 'inherit' }}
            onClick={() => setInput(t)}
            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--paper-2)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
          >{t}</button>
        ))}
      </div>

      {/* Main thread */}
      <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div style={{ padding: '12px 24px', borderBottom: '1px solid var(--line-1)', display: 'flex', alignItems: 'center', gap: 10 }}>
          <Icon name="sparkle" size={14} style={{ color: 'var(--accent)' }} />
          <span className="t-md fg-0" style={{ fontWeight: 500 }}>Atelier — multi-agent assistant</span>
          <Badge tone="pos" size="xs" dot>4 agents online</Badge>
          <span style={{ flex: 1 }} />
          <Button size="sm" variant="ghost" icon="plus" onClick={() => setMessages([])}>New thread</Button>
        </div>

        {/* Messages */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '24px 32px', maxWidth: 820, width: '100%', margin: '0 auto' }}>
          {messages.length === 0 && (
            <div style={{ textAlign: 'center', paddingTop: 80 }}>
              <div style={{ width: 40, height: 40, borderRadius: 'var(--r-pill)', background: 'var(--ink-0)', color: 'var(--paper-0)', display: 'grid', placeItems: 'center', fontFamily: 'var(--font-serif)', fontSize: 20, fontStyle: 'italic', margin: '0 auto 16px' }}>æ</div>
              <div className="serif" style={{ fontSize: 24, color: 'var(--ink-0)' }}>What would you like to learn?</div>
              <div className="t-md fg-3" style={{ marginTop: 8 }}>Plan a course, take a quiz, or dive into any concept — I'm here for all of it.</div>
            </div>
          )}

          {messages.map((msg) => (
            <div key={msg.id} style={{ marginBottom: 24, display: 'flex', gap: 12 }}>
              {msg.role === 'user' ? (
                <Avatar name={name || 'You'} size={26} />
              ) : (
                <div style={{ width: 26, height: 26, borderRadius: 'var(--r-pill)', background: 'var(--ink-0)', color: 'var(--paper-0)', display: 'grid', placeItems: 'center', fontFamily: 'var(--font-serif)', fontSize: 13, fontStyle: 'italic', flexShrink: 0 }}>æ</div>
              )}
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                  <span className="t-sm fg-0" style={{ fontWeight: 500 }}>{msg.role === 'user' ? (name || 'You') : 'Atelier'}</span>
                  {msg.streaming && <Badge tone="pos" size="xs" dot>Writing…</Badge>}
                </div>
                {msg.role === 'user' ? (
                  <div className="t-md fg-1" style={{ lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>
                    {msg.content}
                  </div>
                ) : (
                  <MarkdownMessage content={msg.content} streaming={msg.streaming} />
                )}
                {/* Action cards rendered below assistant content */}
                {msg.role === 'assistant' && (msg.actions ?? []).map((action, i) => (
                  <ActionCardView key={i} action={action} onNavigate={(url) => navigate(url)} />
                ))}
                {!msg.streaming && msg.role === 'assistant' && msg.content && (
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
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Composer */}
        <div style={{ padding: 16, borderTop: '1px solid var(--line-1)', background: 'var(--paper-0)', flexShrink: 0 }}>
          <div style={{ maxWidth: 820, margin: '0 auto' }}>
            <div style={{ background: 'var(--paper-1)', border: '1px solid var(--line-2)', borderRadius: 'var(--r-3)', padding: 8 }}>
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask me anything — I'll figure out the best way to help."
                rows={3}
                maxLength={2000}
                style={{ width: '100%', background: 'transparent', border: 0, outline: 'none', resize: 'none', fontSize: 14, color: 'var(--ink-0)', fontFamily: 'inherit', lineHeight: 1.5 }}
              />
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
                <Button size="xs" variant="ghost" icon="upload">Attach</Button>
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
                <span className="hidden sm:inline t-xs fg-3"><kbd>⌘</kbd><kbd>↵</kbd> to send</span>
                <Button size="sm" variant="primary" icon="send" onClick={sendMessage} loading={streaming}>Send</Button>
              </div>
            </div>
            <div className="t-xs fg-3" style={{ textAlign: 'center', marginTop: 6 }}>Always verify important facts with authoritative sources before acting on them.</div>
          </div>
        </div>
      </div>
    </div>
  )
}

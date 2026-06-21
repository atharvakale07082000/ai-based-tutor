import { useState, useEffect, useRef, useCallback } from 'react'
import { useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { doubtsAPI } from '@/lib/api'
import { runSentiment } from '@/lib/hf'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Icon } from '@/components/ui/Icon'
import { Avatar } from '@/components/ui/Avatar'
import { ChatBubbleSkeleton } from '@/components/ui/Skeleton'
import { MarkdownMessage } from '@/components/ui/MarkdownMessage'
import { useLearnerStore } from '@/stores/learnerStore'
import { useSpeechInput } from '@/hooks/useSpeechInput'
import toast from 'react-hot-toast'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

export default function DoubtChatPage() {
  const location = useLocation()
  const state = location.state as { prefill?: string; topic?: string } | null
  const { name } = useLearnerStore()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState(state?.prefill ?? '')
  const [topicContext, setTopicContext] = useState(state?.topic ?? '')
  const [isStreaming, setIsStreaming] = useState(false)
  const [sessionTimer, setSessionTimer] = useState(0)

  const { isListening: isRecording, isSupported: isSpeechSupported, toggle: toggleVoice } = useSpeechInput({
    onInterim: (text) => setInput(text),
    onFinal: (text) => { setInput(text); toast.success('Got it — send whenever you\'re ready!', { icon: '🎤', duration: 2500 }) },
  })
  const [sessionId] = useState(() => crypto.randomUUID())
  const [showHistory, setShowHistory] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const addDoubtSession = useLearnerStore((s) => s.addDoubtSession)

  const { data: sessions } = useQuery({
    queryKey: ['doubts', 'sessions'],
    queryFn: () => doubtsAPI.getSessions().then((r) => r.data),
    staleTime: 1000 * 30,       // session list: 30 s
    gcTime: 1000 * 60 * 5,
  })

  useEffect(() => {
    const interval = setInterval(() => setSessionTimer((t) => t + 1), 1000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60).toString().padStart(2, '0')
    const sec = (s % 60).toString().padStart(2, '0')
    return `${m}:${sec}`
  }

  const sendMessage = useCallback(async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || isStreaming) return
    if (trimmed.length < 3) { toast.error('Give me a bit more to work with — try writing a complete question.'); return }
    if (trimmed.length > 1500) { toast.error("That's a detailed one! Try breaking it into a shorter question."); return }
    setInput('')
    const userMsg: Message = { id: crypto.randomUUID(), role: 'user', content: text, timestamp: new Date() }
    setMessages((prev) => [...prev, userMsg])

    const assistantId = crypto.randomUUID()
    setMessages((prev) => [...prev, { id: assistantId, role: 'assistant', content: '', timestamp: new Date() }])
    setIsStreaming(true)

    try {
      const response = await fetch(doubtsAPI.streamUrl(), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('ai_tutor_token') ?? ''}`,
        },
        body: JSON.stringify({
          question: text,
          topic_context: topicContext,
          session_id: sessionId,
          history: messages.slice(-6).map((m) => ({ role: m.role, content: m.content })),
        }),
      })

      if (!response.ok || !response.body) throw new Error('Stream failed')

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let full = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value, { stream: true })
        const lines = chunk.split('\n').filter((l) => l.startsWith('data: '))
        for (const line of lines) {
          const json = line.slice(6).trim()
          if (json === '[DONE]') break
          try {
            const { token } = JSON.parse(json)
            full += token
            setMessages((prev) => prev.map((m) => m.id === assistantId ? { ...m, content: full } : m))
          } catch { /* skip */ }
        }
      }

      if (messages.length >= 3) {
        const allText = messages.map((m) => m.content).join(' ')
        try {
          const sentiment = await runSentiment(allText)
          const mood = sentiment[0]?.label ?? 'NEUTRAL'
          addDoubtSession({ id: sessionId, topic_context: topicContext, sentiment_mood: mood, started_at: new Date().toISOString(), message_count: messages.length })
        } catch { /* non-critical */ }
      }
    } catch {
      toast.error('I hit a snag — send your question again and I\'ll come right back.')
      setMessages((prev) => prev.filter((m) => m.id !== assistantId))
    } finally {
      setIsStreaming(false)
    }
  }, [isStreaming, messages, topicContext, sessionId, addDoubtSession])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(input) }
  }


  const ALLOWED_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/webp'])
  const handleImageUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (!ALLOWED_IMAGE_TYPES.has(file.type)) {
      toast.error('Unsupported image type. Use JPEG, PNG, GIF, or WebP.')
      e.target.value = ''
      return
    }
    if (file.size > 5 * 1024 * 1024) {
      toast.error('Image must be under 5 MB.')
      e.target.value = ''
      return
    }
    try {
      const { data } = await doubtsAPI.caption(file)
      setInput((prev) => `[Image: ${data.caption}]\n${prev}`)
      toast.success('Image captioned')
    } catch { toast.error('Could not caption image') }
  }

  const MOOD_EMOJI: Record<string, string> = { POSITIVE: '😊', NEGATIVE: '😟', NEUTRAL: '😐' }

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      {/* History drawer */}
      {showHistory && (
        <>
          <div className="fixed inset-0 z-30 bg-black/40 sm:hidden" onClick={() => setShowHistory(false)} aria-hidden="true" />
          <div
            className="fixed inset-y-0 left-0 z-40 w-[80vw] max-w-[280px] sm:static sm:z-auto sm:w-[260px] sm:max-w-none"
            style={{ borderRight: '1px solid var(--line-1)', background: 'var(--paper-1)', display: 'flex', flexDirection: 'column', flexShrink: 0, overflow: 'hidden' }}
          >
            <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--line-1)' }}>
              <span className="caps fg-2">Session history</span>
            </div>
            <div style={{ flex: 1, overflowY: 'auto', padding: 8 }}>
              {(sessions ?? []).map((s) => (
                <div key={s.id} className="row-i" style={{ padding: '8px 10px 8px 14px', borderRadius: 'var(--r-2)', cursor: 'pointer', marginBottom: 4 }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--paper-2)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span className="t-xs fg-2" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>{s.topic_context ?? 'General'}</span>
                    <span style={{ marginLeft: 6 }}>{MOOD_EMOJI[s.sentiment_mood?.toUpperCase() ?? ''] ?? '💬'}</span>
                    <Icon name="chevR" size={12} className="row-chevron" style={{ color: 'var(--ink-3)', marginLeft: 4 }} />
                  </div>
                  <div className="t-xs fg-3" style={{ marginTop: 2 }}>{new Date(s.started_at).toLocaleDateString()}</div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {/* Main chat */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
        {/* Top bar */}
        <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--line-1)', display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
          <button
            onClick={() => setShowHistory((v) => !v)}
            aria-label="Toggle session history"
            className="min-h-11 min-w-11 sm:min-h-0 sm:min-w-0"
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 28, height: 28, borderRadius: 'var(--r-1)', background: 'none', border: 0, cursor: 'pointer' }}
            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--paper-2)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'none')}
          >
            <Icon name="home" size={14} style={{ color: 'var(--ink-3)' }} />
          </button>
          {topicContext ? (
            <Badge tone="outline" size="xs">{topicContext}</Badge>
          ) : (
            <input
              value={topicContext}
              onChange={(e) => setTopicContext(e.target.value)}
              placeholder="Topic context (optional)"
              style={{ background: 'transparent', border: 0, outline: 'none', fontSize: 13, color: 'var(--ink-2)', fontFamily: 'inherit', flex: 1 }}
            />
          )}
          <span style={{ flex: 1 }} />
          <Badge tone="neutral" size="xs">Learning Assistant</Badge>
          <span className="t-xs fg-3 mono">{formatTime(sessionTimer)}</span>
        </div>

        {/* Messages */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
          {messages.length === 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', textAlign: 'center', paddingTop: 60 }}>
              <div style={{ width: 44, height: 44, borderRadius: 'var(--r-2)', background: 'var(--paper-2)', display: 'grid', placeItems: 'center', marginBottom: 16 }}>
                <Icon name="sparkle" size={20} style={{ color: 'var(--accent)' }} />
              </div>
              <div className="serif" style={{ fontSize: 22, marginBottom: 8 }}>What would you like to understand?</div>
              <div className="t-md fg-3">No question is too basic or too advanced — I'll meet you exactly where you are.</div>
            </div>
          )}

          <div style={{ maxWidth: 720, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 20 }}>
            {messages.map((msg) => (
              <div key={msg.id} style={{ display: 'flex', gap: 10, justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
                {msg.role === 'assistant' && (
                  <div style={{ width: 26, height: 26, borderRadius: 'var(--r-pill)', background: 'var(--ink-0)', color: 'var(--paper-0)', display: 'grid', placeItems: 'center', fontFamily: 'var(--font-serif)', fontSize: 13, fontStyle: 'italic', flexShrink: 0 }}>æ</div>
                )}
                <div
                  style={{
                    maxWidth: '75%',
                    background: msg.role === 'user' ? 'var(--ink-0)' : 'var(--paper-2)',
                    color: msg.role === 'user' ? 'var(--paper-0)' : 'var(--ink-0)',
                    borderRadius: msg.role === 'user' ? 'var(--r-2) var(--r-2) 2px var(--r-2)' : 'var(--r-2) var(--r-2) var(--r-2) 2px',
                    padding: '10px 14px',
                  }}
                >
                  {msg.role === 'user' ? (
                    <span style={{ fontSize: 14, lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>{msg.content}</span>
                  ) : (
                    <MarkdownMessage
                      content={msg.content}
                      streaming={isStreaming && messages.indexOf(msg) === messages.length - 1}
                    />
                  )}
                </div>
                {msg.role === 'user' && <Avatar name={name || 'You'} size={26} />}
              </div>
            ))}
            {isStreaming && messages[messages.length - 1]?.content === '' && <ChatBubbleSkeleton />}
            <div ref={bottomRef} />
          </div>
        </div>

        {/* Input */}
        <div style={{ padding: '12px 16px', borderTop: '1px solid var(--line-1)', background: 'var(--paper-0)', flexShrink: 0 }}>
          <div style={{ maxWidth: 720, margin: '0 auto' }}>
            <div style={{ background: 'var(--paper-1)', border: '1px solid var(--line-2)', borderRadius: 'var(--r-3)', padding: '8px 10px' }}>
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="What's on your mind? (Enter to send)"
                rows={2}
                maxLength={1500}
                style={{ width: '100%', background: 'transparent', border: 0, outline: 'none', resize: 'none', fontSize: 14, color: 'var(--ink-0)', fontFamily: 'inherit', lineHeight: 1.5 }}
              />
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 4 }}>
                {isSpeechSupported && (
                  <button
                    onClick={toggleVoice}
                    aria-label={isRecording ? 'Stop listening' : 'Start voice input'}
                    title={isRecording ? 'Stop (click to finish)' : 'Speak your question'}
                    className="min-h-11 min-w-11 sm:min-h-0 sm:min-w-0 inline-flex items-center justify-center"
                    style={{
                      padding: '4px 8px', borderRadius: 'var(--r-1)', border: 0, gap: 5, display: 'flex', alignItems: 'center',
                      background: isRecording ? 'color-mix(in srgb, var(--neg) 12%, var(--paper-1))' : 'transparent',
                      color: isRecording ? 'var(--neg)' : 'var(--ink-3)',
                      cursor: 'pointer', transition: 'all 0.15s ease',
                    }}
                  >
                    <Icon name="mic" size={13} style={isRecording ? { animation: 'pulse 1s ease-in-out infinite' } : undefined} />
                    {isRecording && <span style={{ fontSize: 11, fontWeight: 500 }}>Listening…</span>}
                  </button>
                )}
                <label aria-label="Upload an image" className="min-h-11 min-w-11 sm:min-h-0 sm:min-w-0 inline-flex items-center justify-center" style={{ padding: '4px 6px', borderRadius: 'var(--r-1)', cursor: 'pointer', color: 'var(--ink-3)' }}>
                  <Icon name="upload" size={13} />
                  <input type="file" accept="image/*" style={{ display: 'none' }} onChange={handleImageUpload} />
                </label>
                <span style={{ flex: 1 }} />
                {input.length > 1200 && (
                  <span className="t-xs" style={{ color: input.length > 1400 ? 'var(--neg)' : 'var(--ink-3)' }}>
                    {input.length}/1500
                  </span>
                )}
                <span className="hidden sm:inline t-xs fg-3"><kbd>↵</kbd> send</span>
                <Button size="sm" variant="primary" icon="send" onClick={() => sendMessage(input)} loading={isStreaming}>Send</Button>
              </div>
            </div>
            <div className="t-xs fg-3" style={{ textAlign: 'center', marginTop: 4 }}>Every question you ask gets you one step closer to mastery.</div>
          </div>
        </div>
      </div>
    </div>
  )
}

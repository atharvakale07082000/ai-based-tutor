import { useState, useEffect, useRef, useCallback } from 'react'
import { useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import { doubtsAPI } from '@/lib/api'
import { runSpeechToText, runSentiment } from '@/lib/hf'
import { PageWrapper } from '@/components/layout/PageWrapper'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { ChatBubbleSkeleton } from '@/components/ui/Skeleton'
import { useLearnerStore } from '@/stores/learnerStore'
import toast from 'react-hot-toast'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

let mediaRecorder: MediaRecorder | null = null
let recordedChunks: BlobPart[] = []

export default function DoubtChatPage() {
  const location = useLocation()
  const state = location.state as { prefill?: string; topic?: string } | null
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState(state?.prefill ?? '')
  const [topicContext, setTopicContext] = useState(state?.topic ?? '')
  const [isStreaming, setIsStreaming] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const [sessionTimer, setSessionTimer] = useState(0)
  const [sessionId] = useState(() => crypto.randomUUID())
  const [showHistory, setShowHistory] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const addDoubtSession = useLearnerStore((s) => s.addDoubtSession)

  const { data: sessions } = useQuery({
    queryKey: ['doubts', 'sessions'],
    queryFn: () => doubtsAPI.getSessions().then((r) => r.data),
  })

  // Session timer
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
    if (!text.trim() || isStreaming) return
    setInput('')

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      timestamp: new Date(),
    }
    setMessages((prev) => [...prev, userMsg])

    const assistantId = crypto.randomUUID()
    const assistantMsg: Message = {
      id: assistantId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
    }
    setMessages((prev) => [...prev, assistantMsg])
    setIsStreaming(true)

    try {
      const response = await fetch(doubtsAPI.streamUrl(), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('access_token') ?? ''}`,
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
            setMessages((prev) =>
              prev.map((m) => (m.id === assistantId ? { ...m, content: full } : m))
            )
          } catch { /* skip */ }
        }
      }

      // Run sentiment at session end
      if (messages.length >= 3) {
        const allText = messages.map((m) => m.content).join(' ')
        try {
          const sentiment = await runSentiment(allText)
          const mood = sentiment[0]?.label ?? 'NEUTRAL'
          addDoubtSession({
            id: sessionId,
            topic_context: topicContext,
            sentiment_mood: mood,
            started_at: new Date().toISOString(),
            message_count: messages.length,
          })
        } catch { /* non-critical */ }
      }
    } catch (err) {
      toast.error('Doubt-Solver is unavailable. Please try again.')
      setMessages((prev) => prev.filter((m) => m.id !== assistantId))
    } finally {
      setIsStreaming(false)
    }
  }, [isStreaming, messages, topicContext, sessionId, addDoubtSession])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage(input)
    }
  }

  const handleVoice = async () => {
    if (isRecording) {
      mediaRecorder?.stop()
      setIsRecording(false)
      return
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      recordedChunks = []
      mediaRecorder = new MediaRecorder(stream)
      mediaRecorder.ondataavailable = (e) => recordedChunks.push(e.data)
      mediaRecorder.onstop = async () => {
        const blob = new Blob(recordedChunks, { type: 'audio/webm' })
        stream.getTracks().forEach((t) => t.stop())
        try {
          const transcript = await runSpeechToText(blob)
          setInput(transcript)
          toast.success('Transcription complete')
        } catch {
          // fallback to backend transcription
          try {
            const { data } = await doubtsAPI.transcribe(blob)
            setInput(data.transcript)
          } catch {
            toast.error('Transcription failed')
          }
        }
      }
      mediaRecorder.start()
      setIsRecording(true)
    } catch {
      toast.error('Microphone permission denied')
    }
  }

  const handleImageUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const { data } = await doubtsAPI.caption(file)
      setInput((prev) => `[Image: ${data.caption}]\n${prev}`)
      toast.success('Image captioned')
    } catch {
      toast.error('Could not caption image')
    }
  }

  const MOOD_EMOJI: Record<string, string> = { POSITIVE: '😊', NEGATIVE: '😟', NEUTRAL: '😐' }

  return (
    <PageWrapper showAgentBar={false} fullscreen>
      <div className="flex h-full">
        {/* History drawer */}
        <AnimatePresence>
          {showHistory && (
            <motion.div
              initial={{ x: -320, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: -320, opacity: 0 }}
              transition={{ type: 'spring', stiffness: 100, damping: 20 }}
              className="w-72 border-r border-surface-2/50 glass flex flex-col overflow-hidden shrink-0"
            >
              <div className="p-4 border-b border-surface-2/50">
                <h3 className="text-sm font-medium text-paper">Session History</h3>
              </div>
              <div className="flex-1 overflow-y-auto p-3 space-y-2">
                {(sessions ?? []).map((s) => (
                  <div key={s.id} className="p-3 rounded-xl bg-surface-2 hover:bg-surface-3 cursor-pointer transition-colors">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-paper/60 truncate">{s.topic_context ?? 'General'}</span>
                      <span>{MOOD_EMOJI[s.sentiment_mood?.toUpperCase() ?? ''] ?? '💬'}</span>
                    </div>
                    <p className="text-[10px] text-paper/30 mt-1">
                      {new Date(s.started_at).toLocaleDateString()}
                    </p>
                  </div>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Main chat area */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Top bar */}
          <div className="glass border-b border-surface-2/50 px-4 py-3 flex items-center gap-3">
            <button
              onClick={() => setShowHistory((v) => !v)}
              className="p-2 rounded-lg hover:bg-surface-2 transition-colors"
              aria-label="Toggle session history"
            >
              <svg className="w-4 h-4 text-paper/60" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>

            {topicContext && (
              <Badge variant="violet" className="text-xs">📚 {topicContext}</Badge>
            )}
            <input
              value={topicContext}
              onChange={(e) => setTopicContext(e.target.value)}
              placeholder="Topic context (optional)"
              className="flex-1 bg-transparent text-sm text-paper/60 placeholder-paper/30 focus:outline-none"
            />
            <Badge variant="surface" className="text-[10px] shrink-0">AI Tutor</Badge>
            <span className="text-xs text-paper/30 font-mono shrink-0">{formatTime(sessionTimer)}</span>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4" aria-live="polite" aria-label="Chat messages">
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full text-center py-12">
                <div className="w-16 h-16 rounded-2xl bg-violet/20 flex items-center justify-center text-3xl mb-4">💡</div>
                <h3 className="font-display text-xl text-paper mb-2">Ask your Doubt-Solver</h3>
                <p className="text-sm text-paper/50 max-w-sm">
                  Ask any question about your current topic — get instant, context-aware answers.
                </p>
              </div>
            )}

            {messages.map((msg) => (
              <motion.div
                key={msg.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                {msg.role === 'assistant' && (
                  <div className="w-7 h-7 rounded-full bg-gradient-to-br from-violet to-indigo shrink-0 flex items-center justify-center text-xs mr-2 mt-1">
                    AI
                  </div>
                )}
                <div
                  className={`max-w-[75%] rounded-2xl px-4 py-3 text-sm ${
                    msg.role === 'user'
                      ? 'bg-indigo text-white rounded-tr-sm'
                      : 'bg-surface-2 text-paper border-l-2 border-violet rounded-tl-sm'
                  }`}
                >
                  {msg.content || (
                    isStreaming && msg.role === 'assistant' ? (
                      <span className="typewriter-cursor text-paper/50">Thinking</span>
                    ) : null
                  )}
                  {isStreaming && msg.role === 'assistant' && msg.content && (
                    <span className="typewriter-cursor" />
                  )}
                </div>
              </motion.div>
            ))}

            {isStreaming && messages[messages.length - 1]?.content === '' && (
              <ChatBubbleSkeleton />
            )}
            <div ref={bottomRef} />
          </div>

          {/* Chat input */}
          <div className="glass border-t border-surface-2/50 p-4">
            <div className="flex items-end gap-2 bg-surface-2 border border-surface-3 rounded-2xl px-4 py-3 focus-within:ring-2 focus-within:ring-violet/50 focus-within:border-violet transition">
              {/* Voice button */}
              <button
                onClick={handleVoice}
                aria-label={isRecording ? 'Stop recording' : 'Start voice input'}
                className={`shrink-0 p-1.5 rounded-lg transition-colors ${isRecording ? 'text-rose bg-rose/10 animate-pulse' : 'text-paper/40 hover:text-paper hover:bg-surface-3'}`}
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                </svg>
              </button>

              {/* Image upload */}
              <label aria-label="Upload image for caption" className="shrink-0 p-1.5 rounded-lg text-paper/40 hover:text-paper hover:bg-surface-3 cursor-pointer transition-colors">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                </svg>
                <input type="file" accept="image/*" className="hidden" onChange={handleImageUpload} />
              </label>

              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask anything about your topic… (Enter to send, Shift+Enter for new line)"
                rows={1}
                className="flex-1 bg-transparent text-sm text-paper placeholder-paper/30 focus:outline-none resize-none max-h-32 overflow-y-auto"
                style={{ minHeight: '24px' }}
              />

              <Button
                size="sm"
                onClick={() => sendMessage(input)}
                disabled={!input.trim() || isStreaming}
                isLoading={isStreaming}
                aria-label="Send message"
                className="shrink-0"
              >
                →
              </Button>
            </div>
            <p className="text-[10px] text-paper/20 text-center mt-2">
              AI-powered answers · Voice input · Image understanding
            </p>
          </div>
        </div>
      </div>
    </PageWrapper>
  )
}

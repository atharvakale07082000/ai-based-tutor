import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { quizAPI } from '@/lib/api'
import { runTextGeneration, runSentiment } from '@/lib/hf'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Icon } from '@/components/ui/Icon'
import { useLearnerStore } from '@/stores/learnerStore'
import { useAgentStore } from '@/stores/agentStore'
import toast from 'react-hot-toast'

const QUESTION_TIME = 60

function TimerBar({ timeLeft, total }: { timeLeft: number; total: number }) {
  const pct = (timeLeft / total) * 100
  const color = timeLeft > 20 ? 'var(--pos)' : timeLeft > 10 ? 'var(--warn)' : 'var(--neg)'
  return (
    <div style={{ height: 3, background: 'var(--paper-3)', borderRadius: 'var(--r-pill)', overflow: 'hidden' }}>
      <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 'var(--r-pill)', transition: 'width 1s linear, background 0.3s' }} />
    </div>
  )
}

export default function QuizPage() {
  const { quizId } = useParams<{ quizId: string }>()
  const navigate = useNavigate()
  const [currentIdx, setCurrentIdx] = useState(0)
  const [answers, setAnswers] = useState<number[]>([])
  const [selectedOption, setSelectedOption] = useState<number | null>(null)
  const [revealed, setRevealed] = useState(false)
  const [timeLeft, setTimeLeft] = useState(QUESTION_TIME)
  const [explanation, setExplanation] = useState('')
  const [explanationLoading, setExplanationLoading] = useState(false)
  const [quizDone, setQuizDone] = useState(false)
  const [result, setResult] = useState<{ score: number; weak_topics: string[] } | null>(null)
  const [reflection, setReflection] = useState('')
  const [reflectionMood, setReflectionMood] = useState<string | null>(null)
  const updateProficiency = useLearnerStore((s) => s.updateProficiency)
  const addQuizSession = useLearnerStore((s) => s.addQuizSession)
  const updateAgentStatus = useAgentStore((s) => s.updateAgentStatus)
  const queryClient = useQueryClient()

  const { data: quiz, isLoading } = useQuery({
    queryKey: ['quiz', quizId],
    queryFn: () => quizAPI.get(quizId!).then((r) => r.data),
    enabled: !!quizId && quizId !== 'new',
  })

  const currentQuestion = quiz?.questions[currentIdx]

  useEffect(() => {
    if (quizDone || revealed) return
    const interval = setInterval(() => {
      setTimeLeft((t) => {
        if (t <= 1) { clearInterval(interval); if (selectedOption === null) handleReveal(-1); return 0 }
        return t - 1
      })
    }, 1000)
    return () => clearInterval(interval)
  }, [currentIdx, quizDone, revealed])

  useEffect(() => {
    setTimeLeft(QUESTION_TIME)
    setSelectedOption(null)
    setRevealed(false)
    setExplanation('')
  }, [currentIdx])

  const handleReveal = useCallback((option: number) => {
    if (revealed) return
    setSelectedOption(option)
    setRevealed(true)
    setAnswers((prev) => [...prev, option])
  }, [revealed])

  const handleNext = useCallback(() => {
    if (quiz && currentIdx < quiz.questions.length - 1) {
      setCurrentIdx((i) => i + 1)
    } else {
      handleFinish()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quiz, currentIdx])

  // Keyboard shortcuts: 1-4 to answer, Enter / Cmd+Enter to advance
  useEffect(() => {
    if (quizDone) return
    const handler = (e: KeyboardEvent) => {
      if (revealed) {
        if (e.key === 'Enter') { e.preventDefault(); handleNext() }
        return
      }
      const num = Number(e.key)
      if (num >= 1 && num <= 4 && currentQuestion && num <= currentQuestion.options.length) {
        e.preventDefault()
        handleReveal(num - 1)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [revealed, currentQuestion, handleReveal, handleNext, quizDone])

  const handleFinish = async () => {
    if (!quiz) return
    updateAgentStatus('progress', { status: 'processing' })
    try {
      const { data } = await quizAPI.submit(quiz.quiz_id, answers, reflection)
      setResult(data)
      setQuizDone(true)
      updateProficiency(quiz.topic, data.elo_update.new_elo)
      addQuizSession({ id: quiz.quiz_id, topic: quiz.topic, score: data.score, bloom_level: quiz.bloom_level, completed_at: new Date().toISOString() })
      // Sync XP from the updated learner profile and invalidate progress cache
      queryClient.invalidateQueries({ queryKey: ['progress'] })
    } catch { toast.error('Could not submit quiz results') }
    finally { updateAgentStatus('progress', { status: 'active' }) }
  }

  const handleGetExplanation = async () => {
    if (!currentQuestion) return
    setExplanationLoading(true)
    try {
      const prompt = `Explain why the correct answer to this question is "${currentQuestion.options[currentQuestion.correct_index]}". Question: ${currentQuestion.question}`
      const text = await runTextGeneration('QUIZ_GENERATOR', prompt, { max_new_tokens: 150 })
      setExplanation(text)
    } catch { toast.error('Could not generate explanation') }
    finally { setExplanationLoading(false) }
  }

  const handleReflectionSubmit = async () => {
    if (!reflection.trim()) return
    try {
      const sentiment = await runSentiment(reflection)
      setReflectionMood(sentiment[0]?.label ?? 'NEUTRAL')
      toast.success('Mood saved')
    } catch { /* non-critical */ }
  }

  if (isLoading) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--paper-0)' }}>
        <div style={{ textAlign: 'center' }}>
          <Icon name="refresh" size={24} style={{ animation: 'spin 1s linear infinite', color: 'var(--ink-2)' }} />
          <div className="t-sm fg-3" style={{ marginTop: 10 }}>Loading quiz…</div>
        </div>
      </div>
    )
  }

  if (!quiz) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12 }}>
        <Icon name="book" size={32} style={{ color: 'var(--ink-3)' }} />
        <div className="t-md fg-2">Quiz not found</div>
        <Button variant="secondary" onClick={() => navigate('/dashboard')}>Back to Dashboard</Button>
      </div>
    )
  }

  // Results screen
  if (quizDone && result) {
    const scorePercent = Math.round(result.score * 100)
    const r = 54
    const circ = 2 * Math.PI * r
    const scoreColor = scorePercent >= 80 ? 'var(--pos)' : scorePercent >= 60 ? 'var(--warn)' : 'var(--neg)'

    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, background: 'var(--paper-0)' }}>
        <div style={{ background: 'var(--paper-1)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: 32, maxWidth: 440, width: '100%' }}>
          <h2 className="serif" style={{ fontSize: 28, fontWeight: 400, textAlign: 'center', marginBottom: 24 }}>Quiz Complete</h2>

          {/* Score ring */}
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 24 }}>
            <div style={{ position: 'relative', width: 144, height: 144 }}>
              <svg width="144" height="144" style={{ transform: 'rotate(-90deg)' }} viewBox="0 0 130 130">
                <circle cx="65" cy="65" r={r} fill="none" stroke="var(--paper-3)" strokeWidth="10" />
                <circle
                  cx="65" cy="65" r={r} fill="none"
                  stroke={scoreColor} strokeWidth="10" strokeLinecap="round"
                  strokeDasharray={circ}
                  strokeDashoffset={circ - circ * result.score}
                  style={{ transition: 'stroke-dashoffset 1.2s ease' }}
                />
              </svg>
              <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
                <span className="serif" style={{ fontSize: 30, fontWeight: 400 }}>{scorePercent}%</span>
                <span className="t-xs fg-3">Score</span>
              </div>
            </div>
          </div>

          {result.weak_topics.length > 0 && (
            <div style={{ marginBottom: 20 }}>
              <div className="caps fg-2" style={{ marginBottom: 6 }}>Topics to revisit</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {result.weak_topics.map((t) => <Badge key={t} tone="neg" size="xs" dot>{t}</Badge>)}
              </div>
            </div>
          )}

          {/* Reflection */}
          <div style={{ marginBottom: 20 }}>
            <div className="caps fg-2" style={{ marginBottom: 6 }}>How did it feel?</div>
            <textarea
              value={reflection}
              onChange={(e) => setReflection(e.target.value)}
              placeholder="Describe how the quiz felt…"
              style={{ width: '100%', background: 'var(--paper-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-2)', padding: '8px 12px', fontSize: 13, color: 'var(--ink-0)', fontFamily: 'inherit', outline: 'none', resize: 'none', height: 72, boxSizing: 'border-box' }}
            />
            {reflectionMood && (
              <Badge tone={reflectionMood === 'POSITIVE' ? 'pos' : 'neg'} size="xs" style={{ marginTop: 4 }}>
                Mood: {reflectionMood.toLowerCase()}
              </Badge>
            )}
            <Button size="xs" variant="ghost" style={{ marginTop: 4 }} onClick={handleReflectionSubmit}>Save mood</Button>
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <Button variant="primary" full onClick={() => navigate('/doubts', { state: { topic: quiz.topic } })}>Ask Doubt-Solver</Button>
            <Button variant="secondary" full onClick={() => navigate('/progress')}>View Progress</Button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '24px 16px', background: 'var(--paper-0)' }}>
      {/* Header */}
      <div style={{ width: '100%', maxWidth: 560, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <div style={{ display: 'flex', gap: 6 }}>
            <Badge tone="outline" size="xs">{quiz.topic}</Badge>
            <Badge tone="neutral" size="xs">{quiz.bloom_level}</Badge>
          </div>
          <span className="t-sm fg-3">{currentIdx + 1} / {quiz.questions.length}</span>
        </div>
        <TimerBar timeLeft={timeLeft} total={QUESTION_TIME} />
        <div className="t-xs fg-3 mono" style={{ textAlign: 'right', marginTop: 2 }}>{timeLeft}s</div>
      </div>

      {/* Question card */}
      {currentQuestion && (
        <div style={{ width: '100%', maxWidth: 560, background: 'var(--paper-1)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: 28 }}>
          <div className="caps fg-3" style={{ marginBottom: 12 }}>Question {currentIdx + 1}</div>
          <h2 className="serif" style={{ fontSize: 22, fontWeight: 400, marginBottom: 20, lineHeight: 1.45 }}>{currentQuestion.question}</h2>

          {/* Options */}
          <div role="radiogroup" aria-label="Answer options" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {currentQuestion.options.map((option, idx) => {
              let bg = 'var(--paper-2)'
              let border = 'var(--line-1)'
              let color = 'var(--ink-1)'
              if (revealed) {
                if (idx === currentQuestion.correct_index) { bg = 'color-mix(in srgb, var(--pos) 15%, var(--paper-1))'; border = 'var(--pos)'; color = 'var(--pos)' }
                else if (idx === selectedOption) { bg = 'color-mix(in srgb, var(--neg) 15%, var(--paper-1))'; border = 'var(--neg)'; color = 'var(--neg)' }
                else { color = 'var(--ink-3)' }
              } else if (selectedOption === idx) {
                bg = 'var(--paper-3)'; border = 'var(--ink-1)'
              }

              return (
                <button
                  key={idx}
                  onClick={() => handleReveal(idx)}
                  disabled={revealed}
                  role="radio"
                  aria-checked={selectedOption === idx}
                  style={{
                    width: '100%', textAlign: 'left', padding: '10px 14px', minHeight: 44,
                    display: 'flex', alignItems: 'center',
                    background: bg, border: `1px solid ${border}`, color,
                    borderRadius: 'var(--r-2)', fontSize: 13, fontFamily: 'inherit',
                    cursor: revealed ? 'default' : 'pointer', transition: 'all var(--dur-fast)',
                  }}
                >
                  <span style={{ opacity: 0.4, marginRight: 10 }}>{String.fromCharCode(65 + idx)}.</span>
                  <span style={{ flex: 1 }}>{option}</span>
                  {!revealed && (
                    <kbd className="hidden sm:inline" style={{ marginLeft: 8 }}>{idx + 1}</kbd>
                  )}
                </button>
              )
            })}
          </div>

          {/* Post-reveal */}
          {revealed && (
            <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
              {currentQuestion.explanation && (
                <div style={{ background: 'var(--paper-2)', borderRadius: 'var(--r-2)', padding: '10px 14px' }}>
                  <div className="t-xs fg-3" style={{ marginBottom: 4 }}>Explanation</div>
                  <div className="t-sm fg-1" style={{ lineHeight: 1.55 }}>{currentQuestion.explanation}</div>
                </div>
              )}

              {!explanation && (
                <Button size="sm" variant="ghost" icon="sparkle" onClick={handleGetExplanation} loading={explanationLoading}>
                  Generate deeper explanation
                </Button>
              )}

              {explanation && (
                <div style={{ background: 'color-mix(in srgb, var(--accent) 8%, var(--paper-1))', border: '1px solid color-mix(in srgb, var(--accent) 20%, transparent)', borderRadius: 'var(--r-2)', padding: '10px 14px' }}>
                  <div className="t-xs" style={{ color: 'var(--accent)', marginBottom: 4 }}>AI explanation</div>
                  <div className="t-sm fg-1" style={{ lineHeight: 1.55 }}>{explanation}</div>
                </div>
              )}

              <Button variant="primary" full iconRight="arrow" onClick={handleNext}>
                {currentIdx < quiz.questions.length - 1 ? 'Next Question' : 'See Results'}
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

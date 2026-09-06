import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { quizAPI, hfAPI, streamSSE } from '@/lib/api'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Icon } from '@/components/ui/Icon'
import { ReasoningStream } from '@/components/agents/ReasoningStream'
import { useAgentTimeline } from '@/hooks/useAgentTimeline'
import { useLearnerStore } from '@/stores/learnerStore'
import { useAgentStore } from '@/stores/agentStore'
import toast from 'react-hot-toast'

const QUESTION_TIME = 60

// Wire sentinel for a question the learner never answered. The submit payload has always been a
// dense array with one entry per question, so a deferred question still occupies its slot.
const UNANSWERED = -1

/** In-app answer log. `null` = still outstanding; it only becomes UNANSWERED on the wire. */
type AnswerLog = (number | null)[]

type QuestionState = 'answered' | 'deferred' | 'unseen'

/**
 * Next question still waiting on an answer, searching forward from `from` and then wrapping.
 * `from` itself is never returned, so this doubles as "where does Skip send me?".
 * Returns null when nothing is left — i.e. the quiz is ready to submit.
 */
function nextOutstanding(answers: AnswerLog, from: number): number | null {
  for (let i = from + 1; i < answers.length; i++) if (answers[i] === null) return i
  for (let i = 0; i < from; i++) if (answers[i] === null) return i
  return null
}

function TimerBar({ timeLeft, total }: { timeLeft: number; total: number }) {
  const pct = (timeLeft / total) * 100
  const color = timeLeft > 20 ? 'var(--pos)' : timeLeft > 10 ? 'var(--warn)' : 'var(--neg)'
  return (
    <div style={{ height: 3, background: 'var(--paper-3)', borderRadius: 'var(--r-pill)', overflow: 'hidden' }}>
      <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 'var(--r-pill)', transition: 'width 1s linear, background 0.3s' }} />
    </div>
  )
}

/** Flat stand-in for the timer bar so untimed questions don't shift the layout. */
function StaticRail() {
  return <div style={{ height: 3, background: 'var(--paper-3)', borderRadius: 'var(--r-pill)' }} />
}

/**
 * Compact pager: one cell per question, showing answered / set aside / not reached, and where the
 * learner is. Cells for set-aside questions are the jump targets; the rest stay visible (and are
 * still announced) but are out of the tab order via aria-disabled + tabIndex -1.
 */
function QuestionStrip({
  states,
  currentIdx,
  onJump,
}: {
  states: QuestionState[]
  currentIdx: number
  onJump: (idx: number) => void
}) {
  return (
    <div role="group" aria-label="Question navigator" style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
      {states.map((state, idx) => {
        const isCurrent = idx === currentIdx
        const canJump = state === 'deferred' && !isCurrent

        // Non-colour cues too: dashed = still owed, solid = settled.
        let bg = 'transparent'
        let border = '1px dashed var(--line-1)'
        let color = 'var(--ink-3)'
        if (state === 'answered') {
          bg = 'var(--paper-3)'; border = '1px solid var(--line-1)'; color = 'var(--ink-1)'
        } else if (state === 'deferred') {
          bg = 'var(--warn-soft)'; border = '1px dashed var(--warn)'; color = 'var(--warn)'
        }
        if (isCurrent) {
          bg = 'color-mix(in srgb, var(--accent) 10%, var(--paper-1))'
          border = '1px solid var(--accent)'
          color = 'var(--accent)'
        }

        const stateWord =
          state === 'answered' ? 'answered' : state === 'deferred' ? 'set aside, still needs an answer' : 'not reached yet'
        const label = `Question ${idx + 1}: ${isCurrent ? 'current question, ' : ''}${stateWord}${canJump ? '. Jump to it' : ''}`

        return (
          <button
            key={idx}
            type="button"
            onClick={() => { if (canJump) onJump(idx) }}
            aria-label={label}
            title={label}
            aria-disabled={canJump ? undefined : true}
            aria-current={isCurrent ? 'step' : undefined}
            tabIndex={canJump ? 0 : -1}
            style={{
              flex: '1 1 44px', minWidth: 44, maxWidth: 60, height: 44, padding: 0,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: bg, border, color, borderRadius: 'var(--r-2)',
              fontFamily: 'inherit', fontSize: 12, fontWeight: isCurrent ? 600 : 400,
              cursor: canJump ? 'pointer' : 'default',
              opacity: state === 'unseen' && !isCurrent ? 0.5 : 1,
              transition: 'all var(--dur-fast)',
            }}
          >
            <span className="tnum">{idx + 1}</span>
          </button>
        )
      })}
    </div>
  )
}

export default function QuizPage() {
  const { quizId } = useParams<{ quizId: string }>()
  const navigate = useNavigate()
  const [currentIdx, setCurrentIdx] = useState(0)
  // Authoritative answer log in a ref — handleFinish reads this, not a `answers` state closure, which
  // can be stale on the last question (handleNext is memoized on currentIdx and captures an old
  // handleFinish before the final answer state flushes → last answer dropped → submit 400).
  // `answers` mirrors it purely for rendering; every write goes through recordAnswer.
  const answersRef = useRef<AnswerLog>([])
  const [answers, setAnswers] = useState<AnswerLog>([])
  const [selectedOption, setSelectedOption] = useState<number | null>(null)
  const [revealed, setRevealed] = useState(false)
  const [timeLeft, setTimeLeft] = useState(QUESTION_TIME)
  // High-water mark of questions reached. Everything at or below it has been seen, so it is also
  // how we tell a first visit (timed) from a return visit (untimed).
  const [maxSeen, setMaxSeen] = useState(0)
  const [timerOn, setTimerOn] = useState(true)
  const [reviewMode, setReviewMode] = useState(false)
  const [confirmFinish, setConfirmFinish] = useState(false)
  const [explanation, setExplanation] = useState('')
  const [explanationLoading, setExplanationLoading] = useState(false)
  const [quizDone, setQuizDone] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const { steps: reviewSteps, applyStep: applyReviewStep, reset: resetReview } = useAgentTimeline()
  const [result, setResult] = useState<{ score: number; weak_topics: string[]; elo_update?: { topic: string; new_elo: number } } | null>(null)
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
    staleTime: Infinity,        // quiz questions are immutable once created
    gcTime: 1000 * 60 * 30,
  })

  const currentQuestion = quiz?.questions[currentIdx]
  const questionCount = quiz?.questions.length ?? 0

  // Size the answer log to the quiz once it lands (and reset if the learner opens another quiz).
  useEffect(() => {
    const blank: AnswerLog = Array.from({ length: questionCount }, () => null)
    answersRef.current = blank
    setAnswers(blank)
    setCurrentIdx(0)
    setMaxSeen(0)
    setTimerOn(true)
    setReviewMode(false)
    setConfirmFinish(false)
  }, [quizId, questionCount])

  const states = useMemo<QuestionState[]>(
    () => Array.from({ length: questionCount }, (_, i) =>
      typeof answers[i] === 'number' ? 'answered' : i <= maxSeen ? 'deferred' : 'unseen'
    ),
    [answers, questionCount, maxSeen]
  )

  const answeredCount = useMemo(() => answers.reduce<number>((n, a) => (a === null ? n : n + 1), 0), [answers])
  const outstandingCount = questionCount - answeredCount
  const setAsideCount = useMemo(
    () => states.reduce<number>((n, s, i) => (s === 'deferred' && i !== currentIdx ? n + 1 : n), 0),
    [states, currentIdx]
  )
  // Where "Skip" / "Next" goes. null means the quiz is fully answered.
  const nextTarget = useMemo(() => nextOutstanding(answers, currentIdx), [answers, currentIdx])

  const expired = timerOn && !revealed && timeLeft === 0
  const canSkip = !revealed && nextTarget !== null

  useEffect(() => {
    if (quizDone || revealed || !timerOn) return
    const interval = setInterval(() => {
      setTimeLeft((t) => {
        if (t <= 1) { clearInterval(interval); return 0 }
        return t - 1
      })
    }, 1000)
    return () => clearInterval(interval)
  }, [currentIdx, quizDone, revealed, timerOn])

  useEffect(() => {
    setTimeLeft(QUESTION_TIME)
    setSelectedOption(null)
    setRevealed(false)
    setExplanation('')
    setConfirmFinish(false)
  }, [currentIdx])

  /**
   * Single entry point for moving between questions. A question is timed only on its very first
   * visit (index beyond the high-water mark); coming back to one you set aside is always untimed.
   */
  const goTo = useCallback((idx: number) => {
    setTimerOn(idx > maxSeen)
    setMaxSeen((m) => Math.max(m, idx))
    setCurrentIdx(idx)
  }, [maxSeen])

  const handleReveal = useCallback((option: number) => {
    if (revealed) return
    setSelectedOption(option)
    setRevealed(true)
    const next = [...answersRef.current]
    next[currentIdx] = option
    answersRef.current = next
    setAnswers(next)
  }, [revealed, currentIdx])

  const handleFinish = useCallback(async () => {
    if (!quiz) return
    updateAgentStatus('progress', { status: 'processing' })
    setSubmitting(true)
    resetReview()
    type QuizScored = { score: number; weak_topics: string[]; elo_update: { topic: string; new_elo: number } }
    let scored: QuizScored | null = null
    // Same contract as before: one entry per question, unanswered ones carry the sentinel.
    const payload = answersRef.current.map((a) => (a === null ? UNANSWERED : a))
    try {
      await streamSSE(`/quiz/${quiz.quiz_id}/submit/stream`, { answers: payload, reflection }, (event) => {
        if (event.type === 'step') {
          applyReviewStep(event as unknown as { id: string; label: string; status: 'active' | 'done' | 'error' })
        } else if (event.type === 'action' && event.kind === 'quiz_scored') {
          scored = event.payload as QuizScored
        } else if (event.type === 'error') {
          toast.error(String(event.message ?? 'Could not submit your answers — they are still here, try again'))
        }
      })
      const s = scored as QuizScored | null  // assigned inside the SSE callback; cast so TS keeps the union
      if (s) {
        setResult(s)
        setQuizDone(true)
        updateProficiency(quiz.topic, s.elo_update.new_elo)
        addQuizSession({ id: quiz.quiz_id, topic: quiz.topic, score: s.score, bloom_level: quiz.bloom_level, completed_at: new Date().toISOString() })
        // Sync XP from the updated learner profile and invalidate progress cache
        queryClient.invalidateQueries({ queryKey: ['progress'] })
      } else {
        toast.error('Could not submit your answers — they are still here, try again')
      }
    } catch { toast.error('Could not submit your answers — they are still here, try again') }
    finally {
      setSubmitting(false)
      updateAgentStatus('progress', { status: 'active' })
    }
  }, [quiz, reflection, applyReviewStep, resetReview, updateAgentStatus, updateProficiency, addQuizSession, queryClient])

  const handleNext = useCallback(() => {
    const target = nextOutstanding(answersRef.current, currentIdx)
    if (target === null) { void handleFinish(); return }
    if (target < currentIdx) setReviewMode(true)   // wrapped past the end — into the revisit round
    goTo(target)
  }, [currentIdx, goTo, handleFinish])

  /** Set the current question aside (deferred + implicitly flagged) and move on. */
  const handleSkip = useCallback(() => {
    if (revealed) return
    const target = nextOutstanding(answersRef.current, currentIdx)
    if (target === null) return   // nothing to defer to; this is the last one owed
    if (target < currentIdx) setReviewMode(true)
    goTo(target)
  }, [revealed, currentIdx, goTo])

  const handleJump = useCallback((idx: number) => {
    if (idx === currentIdx) return
    goTo(idx)
  }, [currentIdx, goTo])

  // Keyboard shortcuts: 1-4 to answer, S to set aside, Enter / Cmd+Enter to advance
  useEffect(() => {
    if (quizDone) return
    const handler = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return
      if (revealed) {
        if (e.key === 'Enter') { e.preventDefault(); handleNext() }
        return
      }
      if ((e.key === 's' || e.key === 'S') && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault()
        handleSkip()
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
  }, [revealed, currentQuestion, handleReveal, handleNext, handleSkip, quizDone])

  const handleGetExplanation = async () => {
    if (!currentQuestion || !quiz) return
    setExplanationLoading(true)
    try {
      const { data } = await quizAPI.explain(quiz.quiz_id, currentIdx)
      setExplanation(data.explanation)
    } catch { toast.error('Could not write an explanation — try again') }
    finally { setExplanationLoading(false) }
  }

  const handleReflectionSubmit = async () => {
    if (!reflection.trim()) return
    try {
      const { data } = await hfAPI.sentiment(reflection)
      setReflectionMood(data.label ?? 'NEUTRAL')
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

  // Reviewing screen — live step timeline while the quiz is being scored
  if (submitting && !result) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, background: 'var(--paper-0)' }}>
        <div className="fade-in" style={{ background: 'var(--paper-1)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: 32, maxWidth: 420, width: '100%' }}>
          <h2 className="display" style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.03em', textAlign: 'center', marginBottom: 20 }}>Reviewing your quiz</h2>
          <ReasoningStream segments={reviewSteps.map((s) => ({ id: s.id, text: s.label, status: s.status }))} />
        </div>
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
          <div className="eyebrow" style={{ textAlign: 'center', marginBottom: 6 }}>// results in</div>
          <h2 className="display" style={{ fontSize: 30, fontWeight: 600, letterSpacing: '-0.03em', textAlign: 'center', marginBottom: 24 }}>Quiz complete</h2>

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
                <span className="display tnum" style={{ fontSize: 32, fontWeight: 600 }}>{scorePercent}%</span>
                <span className="readout-label">Score</span>
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
            <Button variant="primary" full onClick={() => navigate('/doubts', { state: { topic: quiz.topic } })}>Ask AI Tutor</Button>
            <Button variant="secondary" full onClick={() => navigate('/progress')}>View progress</Button>
          </div>
        </div>
      </div>
    )
  }

  const timerReadout = revealed
    ? 'answered'
    : !timerOn
      ? 'untimed revisit'
      : timeLeft > 0
        ? `${timeLeft}s`
        : "time's up"

  const nextLabel = nextTarget === null
    ? 'See Results'
    : nextTarget < currentIdx
      ? 'Back to a set-aside question'
      : 'Next Question'

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '24px 16px', background: 'var(--paper-0)' }}>
      {/* Header */}
      <div style={{ width: '100%', maxWidth: 560, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 8 }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <Badge tone="outline" size="xs">{quiz.topic}</Badge>
            <Badge tone="neutral" size="xs">{quiz.bloom_level}</Badge>
          </div>
          <span className="t-sm fg-3 tnum">{currentIdx + 1} / {questionCount}</span>
        </div>

        {timerOn && !revealed ? <TimerBar timeLeft={timeLeft} total={QUESTION_TIME} /> : <StaticRail />}

        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, marginTop: 3 }}>
          <span className="t-xs fg-3 tnum">
            {answeredCount} answered
            {setAsideCount > 0 && <span style={{ color: 'var(--warn)' }}> · {setAsideCount} set aside</span>}
          </span>
          <span className="t-xs fg-3 mono">{timerReadout}</span>
        </div>

        <QuestionStrip states={states} currentIdx={currentIdx} onJump={handleJump} />
      </div>

      {/* Revisit round — the learner reached the end with questions still owed */}
      {reviewMode && outstandingCount > 0 && (
        <div
          role="status"
          style={{
            width: '100%', maxWidth: 560, marginBottom: 12,
            background: 'var(--warn-soft)', border: '1px solid color-mix(in srgb, var(--warn) 32%, transparent)',
            borderRadius: 'var(--r-2)', padding: '10px 14px',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Icon name="bookmark" size={14} style={{ color: 'var(--warn)' }} />
            <span className="t-sm fg-1">
              End of the quiz — {outstandingCount === 1 ? '1 question' : `${outstandingCount} questions`} still to answer. No timer on these.
            </span>
          </div>
          {confirmFinish ? (
            <div style={{ display: 'flex', gap: 6 }}>
              <Button size="sm" variant="danger" style={{ minHeight: 44 }} onClick={() => { void handleFinish() }}>
                Submit with {outstandingCount} unanswered
              </Button>
              <Button size="sm" variant="ghost" style={{ minHeight: 44 }} onClick={() => setConfirmFinish(false)}>Cancel</Button>
            </div>
          ) : (
            <Button size="sm" variant="ghost" style={{ minHeight: 44 }} onClick={() => setConfirmFinish(true)}>
              Finish without them
            </Button>
          )}
        </div>
      )}

      {/* Question card */}
      {currentQuestion && (
        <div style={{ width: '100%', maxWidth: 560, background: 'var(--paper-1)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: 28 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 12 }}>
            <div className="caps fg-3">Question {currentIdx + 1}</div>
            {!timerOn && !revealed && <Badge tone="warn" size="xs" icon="bookmark">Set aside · no timer</Badge>}
          </div>
          <h2 className="display" style={{ fontSize: 22, fontWeight: 500, letterSpacing: '-0.02em', marginBottom: 20, lineHeight: 1.4 }}>{currentQuestion.question}</h2>

          {expired && (
            <div
              role="status"
              style={{ marginBottom: 16, background: 'var(--warn-soft)', border: '1px solid color-mix(in srgb, var(--warn) 30%, transparent)', borderRadius: 'var(--r-2)', padding: '8px 12px' }}
            >
              <span className="t-xs fg-1">The clock ran out — it has stopped, and nothing is lost. Answer now, or set this one aside.</span>
            </div>
          )}

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

          {/* Skip — defers the question and flags it for the revisit round */}
          {!revealed && (
            <div style={{ marginTop: 14, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
              <span className="t-xs fg-3" style={{ flex: '1 1 180px', lineHeight: 1.5 }}>
                {canSkip
                  ? 'Stuck? Set it aside — you will come back to it before the quiz is scored.'
                  : 'This is the last question you still owe an answer to.'}
              </span>
              <Button
                size="lg"
                variant="ghost"
                icon="bookmark"
                style={{ minHeight: 44 }}
                disabled={!canSkip}
                onClick={handleSkip}
                aria-label={`Skip question ${currentIdx + 1} for now and come back to it later`}
              >
                Skip for now
                <kbd className="hidden sm:inline" style={{ marginLeft: 4 }}>S</kbd>
              </Button>
            </div>
          )}

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

              <Button variant="primary" full iconRight="arrow" style={{ minHeight: 44 }} onClick={handleNext}>
                {nextLabel}
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Icon } from '@/components/ui/Icon'
import { coursesAPI, type Interview } from '@/lib/api'

type Phase = 'loading' | 'intro' | 'question' | 'recording' | 'evaluating' | 'feedback' | 'scoring' | 'complete'

interface AnswerResult {
  question_id: number
  score: number
  feedback: string
  answer_text: string
  key_points_covered: string[]
}

interface FinalResult {
  final_score: number
  passed: boolean
  scoring_matrix: Array<{
    question_id: number
    score: number
    justification: string
    concepts_covered: string[]
    concepts_missed: string[]
  }>
  summary: string
  total_questions: number
}

// ── Voice waveform ────────────────────────────────────────────────────────────

// [maxHeightPx, durationS, delayS]
const WAVE_BARS: [number, string, string][] = [
  [14, '0.70s', '0.00s'], [22, '0.90s', '0.05s'], [34, '0.60s', '0.11s'],
  [46, '1.00s', '0.00s'], [58, '0.80s', '0.07s'], [48, '1.10s', '0.13s'],
  [64, '0.70s', '0.04s'], [40, '0.85s', '0.09s'], [72, '0.75s', '0.01s'],
  [54, '0.90s', '0.07s'], [60, '1.00s', '0.03s'], [42, '0.80s', '0.10s'],
  [36, '0.90s', '0.06s'], [52, '0.70s', '0.12s'], [30, '1.10s', '0.02s'],
  [46, '0.75s', '0.08s'], [66, '0.65s', '0.05s'], [38, '0.95s', '0.11s'],
  [56, '0.80s', '0.07s'], [32, '1.00s', '0.04s'], [50, '0.72s', '0.09s'],
  [68, '0.88s', '0.02s'], [44, '0.92s', '0.06s'], [24, '0.78s', '0.12s'],
]

function VoiceWave({ active }: { active: boolean }) {
  return (
    <div
      aria-hidden
      style={{
        display: 'flex',
        alignItems: 'flex-end',
        justifyContent: 'center',
        gap: 3,
        height: 72,
        padding: '0 4px',
      }}
    >
      {WAVE_BARS.map(([maxH, dur, delay], i) => (
        <div
          key={i}
          style={{
            width: 3,
            height: maxH,
            borderRadius: '2px 2px 1px 1px',
            background: active ? 'var(--accent)' : 'var(--line-2)',
            transformOrigin: 'center bottom',
            transform: active ? undefined : 'scaleY(0.1)',
            transition: active
              ? 'background 0.4s ease'
              : 'transform 0.5s var(--ease-out), background 0.4s ease',
            animation: active
              ? `voiceBar ${dur} ease-in-out ${delay} infinite alternate`
              : 'none',
          }}
        />
      ))}
    </div>
  )
}

// ── Real-time mic audio canvas ────────────────────────────────────────────────

function MicCanvas({ stream, active }: { stream: MediaStream | null; active: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef    = useRef<number>(0)
  const ctxRef    = useRef<AudioContext | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    cancelAnimationFrame(rafRef.current)
    if (ctxRef.current) { ctxRef.current.close().catch(() => {}); ctxRef.current = null }

    const ctx2d = canvas.getContext('2d')!
    if (!active || !stream) {
      ctx2d.clearRect(0, 0, canvas.width, canvas.height)
      return
    }

    let audioCtx: AudioContext
    try { audioCtx = new AudioContext() } catch { return }
    ctxRef.current = audioCtx

    const analyser = audioCtx.createAnalyser()
    analyser.fftSize = 128
    analyser.smoothingTimeConstant = 0.72
    try { audioCtx.createMediaStreamSource(stream).connect(analyser) }
    catch { audioCtx.close(); return }

    const W = canvas.width, H = canvas.height
    const bufLen = analyser.frequencyBinCount
    const data = new Uint8Array(bufLen)
    const BARS = 40, barW = 4, gap = 2
    const totalW = BARS * barW + (BARS - 1) * gap
    const startX = (W - totalW) / 2

    const draw = () => {
      rafRef.current = requestAnimationFrame(draw)
      analyser.getByteFrequencyData(data)
      ctx2d.clearRect(0, 0, W, H)
      for (let i = 0; i < BARS; i++) {
        const idx = Math.floor((i / BARS) * bufLen * 0.52)
        const v = data[idx] / 255
        const barH = Math.max(3, v * H)
        const x = startX + i * (barW + gap)
        const y = (H - barH) / 2
        ctx2d.fillStyle = `rgba(168, 85, 58, ${0.18 + v * 0.82})`
        ctx2d.fillRect(x, y, barW, barH)
      }
    }
    draw()

    return () => {
      cancelAnimationFrame(rafRef.current)
      audioCtx.close().catch(() => {})
    }
  }, [active, stream])

  return (
    <canvas
      ref={canvasRef}
      width={320}
      height={44}
      style={{ display: 'block', opacity: active ? 1 : 0, transition: 'opacity 0.35s ease' }}
    />
  )
}

// ── Live transcript display ───────────────────────────────────────────────────

function LiveTranscript({ confirmed, interim }: { confirmed: string; interim: string }) {
  const isEmpty = !confirmed.trim() && !interim.trim()
  return (
    <div
      style={{
        minHeight: 108,
        padding: '18px 22px',
        background: 'var(--paper-1)',
        border: '1px solid var(--line-1)',
        borderRadius: 'var(--r-3)',
        display: 'flex',
        alignItems: isEmpty ? 'center' : 'flex-start',
      }}
    >
      {isEmpty ? (
        <p style={{
          margin: 0, width: '100%', textAlign: 'center',
          fontStyle: 'italic', color: 'var(--ink-4)', fontSize: 14,
        }}>
          Your answer will appear here as you speak…
        </p>
      ) : (
        <p style={{
          margin: 0, fontSize: 15, lineHeight: 1.72,
          color: 'var(--ink-0)', letterSpacing: '-0.01em',
        }}>
          <span>{confirmed}</span>
          {interim && (
            <span style={{ color: 'var(--ink-3)' }}>
              {confirmed ? ' ' : ''}
              {interim}
              <span style={{
                display: 'inline-block', width: 2, height: '0.85em',
                background: 'var(--accent)', marginLeft: 2,
                verticalAlign: 'text-bottom',
                animation: 'blink 0.85s step-end infinite',
              }} />
            </span>
          )}
        </p>
      )}
    </div>
  )
}

// ── Score ring ────────────────────────────────────────────────────────────────

function ScoreRing({ score, outOf = 10 }: { score: number; outOf?: number }) {
  const pct = (score / outOf) * 100
  const r = 54, circ = 2 * Math.PI * r
  const color = pct >= 70 ? 'var(--pos)' : pct >= 50 ? 'var(--warn)' : 'var(--neg)'
  return (
    <div style={{ position: 'relative', width: 144, height: 144, margin: '0 auto' }}>
      <svg width="144" height="144" style={{ transform: 'rotate(-90deg)' }} viewBox="0 0 130 130">
        <circle cx="65" cy="65" r={r} fill="none" stroke="var(--paper-3)" strokeWidth="10" />
        <circle cx="65" cy="65" r={r} fill="none" stroke={color} strokeWidth="10"
          strokeLinecap="round" strokeDasharray={circ}
          strokeDashoffset={circ - circ * (pct / 100)}
          style={{ transition: 'stroke-dashoffset 1.4s ease' }}
        />
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <span className="serif" style={{ fontSize: 30 }}>{score.toFixed(1)}</span>
        <span className="t-xs fg-3">/ {outOf}</span>
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

const PANEL: React.CSSProperties = {
  background: 'var(--paper-1)', border: '1px solid var(--line-1)',
  borderRadius: 'var(--r-4)', padding: 28, width: '100%',
}

export default function ModuleInterviewPage() {
  const { planId, moduleId } = useParams<{ planId: string; moduleId: string }>()
  const navigate = useNavigate()

  const [interview,        setInterview]        = useState<Interview | null>(null)
  const [phase,            setPhase]            = useState<Phase>('loading')
  const [currentQIdx,      setCurrentQIdx]      = useState(0)
  const [isRecording,      setIsRecording]      = useState(false)
  const [transcript,       setTranscript]       = useState('')
  const [interimTranscript, setInterimTranscript] = useState('')
  const [currentEval,      setCurrentEval]      = useState<AnswerResult | null>(null)
  const [finalResult,      setFinalResult]      = useState<FinalResult | null>(null)
  const [isSpeaking,       setIsSpeaking]       = useState(false)
  const [displayedQ,       setDisplayedQ]       = useState('')
  const [micStream,        setMicStream]        = useState<MediaStream | null>(null)

  const mediaRef      = useRef<MediaRecorder | null>(null)
  const recognitionRef = useRef<any>(null)
  const transcriptRef = useRef('')

  const { data: plan } = useQuery({
    queryKey: ['course', planId],
    queryFn: () => coursesAPI.get(planId!).then((r) => r.data),
    enabled: !!planId,
    staleTime: 1000 * 60 * 5,   // same key as CourseDetailPage — shares cache
    gcTime: 1000 * 60 * 15,
  })
  const module = plan?.modules.find((m) => m.id === moduleId)

  // Start interview on mount
  useEffect(() => {
    if (!planId || !moduleId) return
    coursesAPI.startInterview(planId, moduleId)
      .then((r) => { setInterview(r.data); setPhase('intro') })
      .catch(() => { toast.error('Could not start interview'); navigate(`/courses/${planId}`) })
  }, [planId, moduleId])

  const currentQuestion = interview?.questions[currentQIdx]

  // Typewriter reveal when entering question phase
  useEffect(() => {
    if (!currentQuestion) return
    if (phase !== 'question') {
      setDisplayedQ(currentQuestion.text)
      return
    }
    let i = 0
    setDisplayedQ('')
    const full = currentQuestion.text
    const id = setInterval(() => {
      i++
      setDisplayedQ(full.slice(0, i))
      if (i >= full.length) clearInterval(id)
    }, 22)
    return () => clearInterval(id)
  }, [currentQuestion?.id, phase])

  // Auto-speak each new question
  useEffect(() => {
    if (phase !== 'question' || !currentQuestion) return
    const timer = setTimeout(() => {
      setIsSpeaking(true)
      const utt = new SpeechSynthesisUtterance(
        `Question ${currentQIdx + 1}. ${currentQuestion.text}`
      )
      utt.rate = 0.92
      const voices = window.speechSynthesis?.getVoices() ?? []
      const preferred = voices.find((v) => v.lang.startsWith('en') && v.localService)
      if (preferred) utt.voice = preferred
      utt.onend = () => setIsSpeaking(false)
      utt.onerror = () => setIsSpeaking(false)
      window.speechSynthesis?.cancel()
      window.speechSynthesis?.speak(utt)
    }, 350)
    return () => {
      clearTimeout(timer)
      window.speechSynthesis?.cancel()
      setIsSpeaking(false)
    }
  }, [currentQIdx, phase])

  const reSpeak = useCallback(() => {
    if (!currentQuestion) return
    setIsSpeaking(true)
    const utt = new SpeechSynthesisUtterance(
      `Question ${currentQIdx + 1}. ${currentQuestion.text}`
    )
    utt.rate = 0.92
    const voices = window.speechSynthesis?.getVoices() ?? []
    const preferred = voices.find((v) => v.lang.startsWith('en') && v.localService)
    if (preferred) utt.voice = preferred
    utt.onend = () => setIsSpeaking(false)
    utt.onerror = () => setIsSpeaking(false)
    window.speechSynthesis?.cancel()
    window.speechSynthesis?.speak(utt)
  }, [currentQuestion, currentQIdx])

  const updateTranscript = useCallback((updater: string | ((prev: string) => string)) => {
    setTranscript((prev) => {
      const next = typeof updater === 'function' ? updater(prev) : updater
      transcriptRef.current = next
      return next
    })
  }, [])

  const startRecording = async () => {
    updateTranscript('')
    setInterimTranscript('')
    let stream: MediaStream | null = null
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      setMicStream(stream)
      const recorder = new MediaRecorder(stream)
      recorder.onstop = () => { stream?.getTracks().forEach((t) => t.stop()); setMicStream(null) }
      recorder.start()
      mediaRef.current = recorder
    } catch { /* proceed without MediaRecorder */ }

    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (SR) {
      const rec = new SR()
      rec.continuous = true
      rec.interimResults = true
      rec.lang = 'en-US'
      rec.onresult = (event: any) => {
        let finalText = '', interimText = ''
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const r = event.results[i]?.[0]
          if (!r) continue
          if (event.results[i].isFinal) finalText += r.transcript + ' '
          else interimText += r.transcript
        }
        if (finalText) updateTranscript((prev) => prev + finalText)
        setInterimTranscript(interimText)
      }
      rec.onerror = () => {}
      rec.start()
      recognitionRef.current = rec
    } else {
      toast('Speech recognition not supported — type below', { icon: 'ℹ️' })
    }
    setIsRecording(true)
    setPhase('recording')
  }

  const stopRecording = () => {
    mediaRef.current?.stop()
    recognitionRef.current?.stop()
    recognitionRef.current = null
    setInterimTranscript('')
    setIsRecording(false)
    setPhase('evaluating')
    setTimeout(() => evaluateAnswer(transcriptRef.current || '[No answer recorded]'), 350)
  }

  const evaluateAnswer = async (answerText: string) => {
    if (!interview || !currentQuestion) return
    try {
      const { data } = await coursesAPI.submitAnswer(
        planId!, moduleId!, interview.interview_id, currentQuestion.id, answerText
      )
      setCurrentEval(data as AnswerResult)
      setPhase('feedback')
      const r = data as AnswerResult
      const utt = new SpeechSynthesisUtterance(
        `Score: ${r.score} out of 10. ${r.feedback}`
      )
      utt.rate = 0.92
      window.speechSynthesis?.cancel()
      window.speechSynthesis?.speak(utt)
    } catch {
      toast.error('Evaluation failed')
      setPhase('question')
    }
  }

  const handleNext = () => {
    window.speechSynthesis?.cancel()
    setCurrentEval(null)
    updateTranscript('')
    if (currentQIdx < (interview?.questions.length ?? 0) - 1) {
      setCurrentQIdx((i) => i + 1)
      setPhase('question')
    } else {
      handleComplete()
    }
  }

  const handleComplete = async () => {
    if (!interview) return
    setPhase('scoring')
    try {
      const { data } = await coursesAPI.completeInterview(planId!, moduleId!, interview.interview_id)
      setFinalResult(data as FinalResult)
      setPhase('complete')
      const r = data as FinalResult
      const utt = new SpeechSynthesisUtterance(
        r.passed
          ? `Congratulations! You scored ${r.final_score.toFixed(1)} out of 10 and passed.`
          : `You scored ${r.final_score.toFixed(1)} out of 10. Review and try again.`
      )
      utt.rate = 0.92
      window.speechSynthesis?.cancel()
      window.speechSynthesis?.speak(utt)
    } catch {
      toast.error('Could not finalize interview')
      setPhase('feedback')
    }
  }

  // ── Loading ──────────────────────────────────────────────────────────────────
  if (phase === 'loading') {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ textAlign: 'center' }}>
          <Icon name="mic" size={28} style={{ color: 'var(--ink-2)', marginBottom: 12, animation: 'pulse-soft 2s ease-in-out infinite' }} />
          <div className="t-sm fg-3">Preparing your interview…</div>
        </div>
      </div>
    )
  }

  // ── Scoring ──────────────────────────────────────────────────────────────────
  if (phase === 'scoring') {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        <div style={{ ...PANEL, maxWidth: 460, textAlign: 'center' }}>
          <Icon name="sparkle" size={28} style={{ color: 'var(--accent)', marginBottom: 12, animation: 'pulse-soft 2s ease-in-out infinite' }} />
          <h2 className="serif" style={{ fontSize: 22, fontWeight: 400, marginBottom: 8 }}>Scoring Agent Running</h2>
          <p className="t-sm fg-2" style={{ marginBottom: 20 }}>Analysing your answers and computing the final score…</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {['Analysing answers', 'Building scoring matrix', 'Computing final score'].map((step, i) => (
              <div key={step} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent)', animation: `blink 1.4s ease-in-out ${i * 0.35}s infinite`, flexShrink: 0 }} />
                <span className="t-sm fg-2">{step}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    )
  }

  // ── Complete ─────────────────────────────────────────────────────────────────
  if (phase === 'complete' && finalResult) {
    return (
      <div style={{ height: '100%', overflowY: 'auto', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        <div style={{ ...PANEL, maxWidth: 520 }}>
          <h2 className="serif" style={{ fontSize: 26, fontWeight: 400, textAlign: 'center', marginBottom: 20 }}>Interview Complete</h2>
          <ScoreRing score={finalResult.final_score} />
          <div style={{ textAlign: 'center', margin: '16px 0 20px' }}>
            <Badge tone={finalResult.passed ? 'pos' : 'neg'} size="sm">
              {finalResult.passed ? 'Module Passed' : 'Not Passed — Review & Retry'}
            </Badge>
          </div>
          {finalResult.summary && (
            <div style={{ background: 'color-mix(in srgb, var(--accent) 8%, var(--paper-1))', border: '1px solid color-mix(in srgb, var(--accent) 20%, transparent)', borderRadius: 'var(--r-2)', padding: '10px 14px', marginBottom: 16 }}>
              <div className="caps" style={{ color: 'var(--accent)', marginBottom: 4 }}>AI Assessment</div>
              <div className="t-sm fg-1" style={{ lineHeight: 1.6 }}>{finalResult.summary}</div>
            </div>
          )}
          {finalResult.scoring_matrix?.length > 0 && (
            <div style={{ marginBottom: 20 }}>
              <div className="caps fg-2" style={{ marginBottom: 8 }}>Scoring Matrix</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {finalResult.scoring_matrix.map((entry, i) => (
                  <div key={i} style={{ background: 'var(--paper-2)', borderRadius: 'var(--r-2)', padding: '10px 12px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <span className="t-xs fg-3">Q{entry.question_id}</span>
                      <Badge tone={entry.score >= 7 ? 'pos' : entry.score >= 5 ? 'warn' : 'neg'} size="xs">{entry.score}/10</Badge>
                    </div>
                    <div className="t-xs fg-2" style={{ marginBottom: 6 }}>{entry.justification}</div>
                    {entry.concepts_covered?.length > 0 && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, marginBottom: 3 }}>
                        {entry.concepts_covered.map((c) => <Badge key={c} tone="pos" size="xs">{c}</Badge>)}
                      </div>
                    )}
                    {entry.concepts_missed?.length > 0 && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
                        {entry.concepts_missed.map((c) => <Badge key={c} tone="neg" size="xs">{c}</Badge>)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
          <div style={{ display: 'flex', gap: 8 }}>
            <Button variant="secondary" full onClick={() => navigate(`/courses/${planId}`)}>Back to Plan</Button>
            {!finalResult.passed && (
              <Button variant="primary" full onClick={() => window.location.reload()}>Retry Interview</Button>
            )}
          </div>
        </div>
      </div>
    )
  }

  // ── Main interview UI ─────────────────────────────────────────────────────────
  const totalQ = interview?.questions.length ?? 1
  const progress = phase === 'intro'
    ? 0
    : ((currentQIdx + (phase === 'feedback' ? 1 : 0)) / totalQ) * 100

  return (
    <div style={{
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      background: 'var(--paper-0)',
      overflow: 'hidden',
    }}>

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div style={{
        padding: '10px 20px',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        borderBottom: '1px solid var(--line-1)',
        background: 'var(--paper-1)',
        flexShrink: 0,
      }}>
        <button
          onClick={() => { window.speechSynthesis?.cancel(); navigate(`/courses/${planId}`) }}
          style={{ display: 'flex', alignItems: 'center', gap: 5, color: 'var(--ink-2)', cursor: 'pointer', flexShrink: 0 }}
        >
          <Icon name="arrow-left" size={13} />
          <span className="t-sm">Back</span>
        </button>

        {module && (
          <span className="t-xs fg-3" style={{ flexShrink: 0, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {module.title}
          </span>
        )}

        {/* Progress bar */}
        <div style={{ flex: 1, height: 3, borderRadius: 2, background: 'var(--paper-3)', overflow: 'hidden' }}>
          <div style={{
            height: '100%', borderRadius: 2,
            background: 'var(--accent)',
            width: `${progress}%`,
            transition: 'width 0.7s var(--ease-out)',
          }} />
        </div>

        <span className="t-xs fg-3" style={{ flexShrink: 0 }}>
          {phase === 'intro' ? 'Intro' : `${currentQIdx + 1} / ${totalQ}`}
        </span>
      </div>

      {/* ── Scrollable content ───────────────────────────────────────────────── */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: '28px 20px 20px',
        gap: 20,
      }}>
        <div style={{ width: '100%', maxWidth: 580 }}>

          {/* ── Intro ─────────────────────────────────────────────────────── */}
          {phase === 'intro' && (
            <div style={PANEL}>
              <div style={{ textAlign: 'center', marginBottom: 24 }}>
                <div style={{
                  width: 56, height: 56, borderRadius: '50%',
                  background: 'var(--ink-1)', color: 'var(--paper-0)',
                  display: 'grid', placeItems: 'center', margin: '0 auto 16px',
                }}>
                  <Icon name="mic" size={22} />
                </div>
                <h2 className="serif" style={{ fontSize: 22, fontWeight: 400, marginBottom: 8 }}>
                  Ready to be assessed?
                </h2>
                <p className="t-sm fg-2" style={{ marginBottom: 4 }}>
                  {interview?.questions.length} questions about <strong>{module?.title}</strong>
                </p>
                <p className="t-xs fg-3" style={{ marginBottom: 16 }}>
                  Speak your answers out loud. Real-time transcription will capture every word. Pass threshold: 6 / 10.
                </p>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, justifyContent: 'center', marginBottom: 24 }}>
                  {module?.topics.map((t) => <Badge key={t} tone="outline" size="xs">{t}</Badge>)}
                </div>
              </div>

              {/* Instructions */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 24 }}>
                {[
                  ['mic',     'Tap the mic button to start speaking. Tap again to stop.'],
                  ['sparkle', 'AI will transcribe your speech in real time.'],
                  ['book',    'You\'ll get instant feedback after each answer.'],
                ].map(([icon, text]) => (
                  <div key={icon} style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                    <Icon name={icon as any} size={13} style={{ color: 'var(--ink-3)', marginTop: 2, flexShrink: 0 }} />
                    <span className="t-sm fg-2">{text}</span>
                  </div>
                ))}
              </div>

              <Button variant="primary" full iconRight="arrow" onClick={() => setPhase('question')}>
                Start Interview
              </Button>
            </div>
          )}

          {/* ── Question + Recording ──────────────────────────────────────── */}
          {(phase === 'question' || phase === 'recording') && currentQuestion && (
            <>
              {/* AI interviewer card */}
              <div style={{
                background: 'var(--paper-1)',
                border: '1px solid var(--line-1)',
                borderRadius: 'var(--r-4)',
                padding: '28px 24px 22px',
                marginBottom: 16,
                textAlign: 'center',
              }}>
                {/* Avatar + status */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, marginBottom: 18 }}>
                  <div style={{
                    width: 38, height: 38, borderRadius: '50%',
                    background: isSpeaking ? 'var(--accent)' : 'var(--ink-1)',
                    color: 'var(--paper-0)',
                    display: 'grid', placeItems: 'center',
                    transition: 'background 0.4s ease',
                    flexShrink: 0,
                  }}>
                    <Icon name="sparkle" size={17} />
                  </div>
                  <div style={{ textAlign: 'left' }}>
                    <div className="t-sm" style={{ fontWeight: 600, color: 'var(--ink-0)' }}>AI Interviewer</div>
                    <div className="t-xs" style={{ color: isSpeaking ? 'var(--accent)' : 'var(--ink-3)' }}>
                      {isSpeaking ? 'Speaking…' : phase === 'recording' ? 'Listening to your answer' : 'Ready'}
                    </div>
                  </div>
                </div>

                {/* Voice waveform */}
                <VoiceWave active={isSpeaking} />

                {/* Question text with typewriter */}
                <p
                  className="serif"
                  style={{
                    fontSize: 'clamp(17px, 3vw, 21px)',
                    lineHeight: 1.48,
                    color: 'var(--ink-0)',
                    fontWeight: 400,
                    margin: '18px 0 16px',
                    minHeight: 60,
                  }}
                >
                  {displayedQ}
                  {displayedQ.length < currentQuestion.text.length && (
                    <span style={{
                      display: 'inline-block', width: 2, height: '0.8em',
                      background: 'var(--accent)', marginLeft: 3,
                      verticalAlign: 'text-bottom',
                      animation: 'blink 0.8s step-end infinite',
                    }} />
                  )}
                </p>

                {/* Depth badge + re-listen */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <Badge tone="outline" size="xs">{currentQuestion.expected_depth}</Badge>
                  <button
                    onClick={reSpeak}
                    disabled={isSpeaking}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 4,
                      fontSize: 11, color: 'var(--ink-3)', cursor: 'pointer',
                      opacity: isSpeaking ? 0.35 : 1, padding: '3px 6px', borderRadius: 'var(--r-1)',
                    }}
                  >
                    <Icon name="mic" size={10} />
                    Re-listen
                  </button>
                </div>
              </div>

              {/* User response zone */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

                {/* Live transcript */}
                <LiveTranscript confirmed={transcript} interim={isRecording ? interimTranscript : ''} />

                {/* Optional manual textarea (only when not recording) */}
                {!isRecording && (
                  <textarea
                    value={transcript}
                    onChange={(e) => updateTranscript(e.target.value)}
                    placeholder="Or type your answer here…"
                    style={{
                      width: '100%', background: 'var(--paper-0)',
                      border: '1px solid var(--line-1)', borderRadius: 'var(--r-2)',
                      padding: '10px 12px', fontSize: 13, color: 'var(--ink-0)',
                      fontFamily: 'inherit', outline: 'none', resize: 'none',
                      height: 72, boxSizing: 'border-box',
                    }}
                  />
                )}

                {/* Mic button + audio visualizer */}
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, padding: '8px 0' }}>

                  {/* Ripple rings + button */}
                  <div style={{ position: 'relative', width: 84, height: 84, display: 'grid', placeItems: 'center' }}>
                    {isRecording && [0, 1, 2].map((i) => (
                      <div key={i} style={{
                        position: 'absolute',
                        width: 80, height: 80,
                        borderRadius: '50%',
                        border: '2px solid var(--neg)',
                        animation: `rippleRing 2s ease-out ${i * 0.65}s infinite`,
                        pointerEvents: 'none',
                      }} />
                    ))}
                    <button
                      onClick={isRecording ? stopRecording : startRecording}
                      style={{
                        width: 72, height: 72, borderRadius: '50%',
                        background: isRecording ? 'var(--neg)' : 'var(--ink-0)',
                        color: 'var(--paper-0)', border: 'none',
                        display: 'grid', placeItems: 'center',
                        cursor: 'pointer', position: 'relative', zIndex: 1,
                        transition: 'background 0.25s ease, transform 0.12s ease',
                        boxShadow: 'var(--shadow-3)',
                      }}
                      onMouseDown={(e) => (e.currentTarget.style.transform = 'scale(0.92)')}
                      onMouseUp={(e)   => (e.currentTarget.style.transform = 'scale(1)')}
                      onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
                    >
                      <Icon name="mic" size={26} />
                    </button>
                  </div>

                  <span className="t-xs fg-3">
                    {isRecording ? 'Tap to stop' : 'Tap to record'}
                  </span>

                  {/* Real mic audio bars */}
                  <MicCanvas stream={micStream} active={isRecording} />
                </div>

                {/* Submit when not recording + has text */}
                {!isRecording && transcript.trim() && (
                  <Button
                    variant="primary"
                    full
                    onClick={() => evaluateAnswer(transcript)}
                  >
                    Submit Answer
                  </Button>
                )}
              </div>
            </>
          )}

          {/* ── Evaluating ────────────────────────────────────────────────── */}
          {phase === 'evaluating' && (
            <div style={{ ...PANEL, textAlign: 'center' }}>
              <Icon name="sparkle" size={24} style={{ color: 'var(--accent)', marginBottom: 12, animation: 'pulse-soft 1.6s ease-in-out infinite' }} />
              <p className="t-md fg-1" style={{ marginBottom: 10 }}>Evaluating your answer…</p>
              <div style={{ display: 'flex', justifyContent: 'center', gap: 5 }}>
                {[0, 1, 2].map((i) => (
                  <span key={i} style={{
                    width: 6, height: 6, borderRadius: '50%',
                    background: 'var(--accent)',
                    animation: `blink 1.2s ease-in-out ${i * 0.2}s infinite`,
                  }} />
                ))}
              </div>
            </div>
          )}

          {/* ── Per-question feedback ─────────────────────────────────────── */}
          {phase === 'feedback' && currentEval && (
            <div style={PANEL}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
                <span className="t-sm fg-2" style={{ fontWeight: 500 }}>Q{currentQIdx + 1} result</span>
                <Badge tone={currentEval.score >= 7 ? 'pos' : currentEval.score >= 5 ? 'warn' : 'neg'} size="sm">
                  {currentEval.score}/10
                </Badge>
              </div>

              {/* Transcribed answer */}
              <div style={{ background: 'var(--paper-2)', borderRadius: 'var(--r-2)', padding: '10px 14px', marginBottom: 12 }}>
                <div className="t-xs fg-3" style={{ marginBottom: 4 }}>Your answer (transcribed)</div>
                <div className="t-sm fg-1" style={{ fontStyle: 'italic', lineHeight: 1.55 }}>"{currentEval.answer_text}"</div>
              </div>

              {/* AI feedback */}
              <div style={{
                background: 'color-mix(in srgb, var(--accent) 8%, var(--paper-1))',
                border: '1px solid color-mix(in srgb, var(--accent) 20%, transparent)',
                borderRadius: 'var(--r-2)', padding: '12px 14px', marginBottom: 16,
              }}>
                <div className="t-xs" style={{ color: 'var(--accent)', marginBottom: 4, fontWeight: 500 }}>Quick feedback</div>
                <div className="t-sm fg-1" style={{ lineHeight: 1.6 }}>{currentEval.feedback}</div>
                {currentEval.key_points_covered?.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 10 }}>
                    {currentEval.key_points_covered.map((kp) => (
                      <Badge key={kp} tone="pos" size="xs">{kp}</Badge>
                    ))}
                  </div>
                )}
              </div>

              <Button variant="primary" full iconRight="arrow" onClick={handleNext}>
                {currentQIdx < (interview?.questions.length ?? 0) - 1
                  ? 'Next Question'
                  : 'Submit for Final Scoring'}
              </Button>
            </div>
          )}

        </div>
      </div>

      {/* ── Progress dots ────────────────────────────────────────────────────── */}
      {interview && !['intro', 'loading'].includes(phase) && (
        <div style={{
          padding: '10px 0',
          display: 'flex',
          justifyContent: 'center',
          gap: 6,
          borderTop: '1px solid var(--line-1)',
          background: 'var(--paper-1)',
          flexShrink: 0,
        }}>
          {interview.questions.map((_, i) => (
            <div key={i} style={{
              height: 6,
              width: i === currentQIdx ? 22 : 6,
              borderRadius: 3,
              background: i < currentQIdx
                ? 'var(--pos)'
                : i === currentQIdx
                  ? 'var(--ink-0)'
                  : 'var(--paper-3)',
              transition: 'all 0.35s var(--ease-spring)',
            }} />
          ))}
        </div>
      )}
    </div>
  )
}

import { useState, useEffect, useRef, useCallback, lazy, Suspense } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Icon } from '@/components/ui/Icon'
import { AgentTimeline } from '@/components/ui/AgentTimeline'
import { useAgentTimeline } from '@/hooks/useAgentTimeline'
import { coursesAPI, streamSSE, type Interview } from '@/lib/api'

// Lazy-load Monaco so it doesn't bloat the initial bundle
const MonacoEditor = lazy(() => import('@monaco-editor/react'))

// ── Types ─────────────────────────────────────────────────────────────────────

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

// ── Shared styles ─────────────────────────────────────────────────────────────

const S = {
  card: {
    background: 'var(--paper-1)',
    border: '1px solid var(--line-1)',
    borderRadius: 16,
    padding: '28px 28px',
    width: '100%',
  } as React.CSSProperties,
  fadeIn: {
    animation: 'fadeSlideUp 0.35s var(--ease-out) both',
  } as React.CSSProperties,
}

// ── ScoreRing ─────────────────────────────────────────────────────────────────

function ScoreRing({ score, outOf = 10 }: { score: number; outOf?: number }) {
  const pct = Math.min((score / outOf) * 100, 100)
  const r = 48, circ = 2 * Math.PI * r
  const color = pct >= 70 ? 'var(--pos)' : pct >= 50 ? 'var(--warn)' : 'var(--neg)'
  return (
    <div style={{ position: 'relative', width: 120, height: 120, margin: '0 auto' }}>
      <svg width="120" height="120" viewBox="0 0 116 116" style={{ transform: 'rotate(-90deg)' }}>
        <circle cx="58" cy="58" r={r} fill="none" stroke="var(--paper-3)" strokeWidth="9" />
        <circle cx="58" cy="58" r={r} fill="none" stroke={color} strokeWidth="9"
          strokeLinecap="round" strokeDasharray={circ}
          strokeDashoffset={circ - circ * (pct / 100)}
          style={{ transition: 'stroke-dashoffset 1.6s cubic-bezier(.4,0,.2,1)' }}
        />
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <span className="serif" style={{ fontSize: 26, fontWeight: 400, lineHeight: 1 }}>{score.toFixed(1)}</span>
        <span className="t-xs fg-3">/ {outOf}</span>
      </div>
    </div>
  )
}

// ── MicWave — animated bars while recording ───────────────────────────────────

function MicWave({ active }: { active: boolean }) {
  const heights = [12, 20, 28, 36, 44, 36, 28, 20, 12]
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 3, height: 44 }}>
      {heights.map((h, i) => (
        <div key={i} style={{
          width: 4, borderRadius: 2,
          background: active ? 'var(--neg)' : 'var(--line-2)',
          height: active ? h : 4,
          transition: 'height 0.3s ease, background 0.3s ease',
          animation: active ? `voiceBar ${0.6 + i * 0.07}s ease-in-out ${i * 0.05}s infinite alternate` : 'none',
        }} />
      ))}
    </div>
  )
}

// ── Live transcript ───────────────────────────────────────────────────────────

function Transcript({ confirmed, interim }: { confirmed: string; interim: string }) {
  const empty = !confirmed && !interim
  return (
    <div style={{
      minHeight: 96,
      maxHeight: 200,
      overflowY: 'auto',
      padding: '14px 16px',
      background: 'var(--paper-0)',
      border: '1px solid var(--line-1)',
      borderRadius: 10,
      boxSizing: 'border-box',
    }}>
      {empty ? (
        <p style={{ margin: 0, color: 'var(--ink-4)', fontSize: 13, fontStyle: 'italic' }}>
          Your answer appears here as you speak…
        </p>
      ) : (
        <p style={{ margin: 0, fontSize: 14, lineHeight: 1.7, color: 'var(--ink-0)', wordBreak: 'break-word', whiteSpace: 'pre-wrap' }}>
          <span>{confirmed}</span>
          {interim && (
            <span style={{ color: 'var(--ink-3)' }}>
              {confirmed ? ' ' : ''}{interim}
              <span style={{ display: 'inline-block', width: 2, height: '0.85em', background: 'var(--accent)', marginLeft: 2, verticalAlign: 'text-bottom', animation: 'blink 0.8s step-end infinite' }} />
            </span>
          )}
        </p>
      )}
    </div>
  )
}

// ── Code Environment ──────────────────────────────────────────────────────────

interface CodeEnvProps {
  planId: string
  moduleId: string
  interviewId: string
  language: string
  value: string
  onChange: (v: string) => void
}

// Languages the editor offers (matches backend code_runner.SUPPORTED_LANGUAGES). `monaco` = the
// Monaco highlighting id; `id` is what we send to the run-code API.
const CODE_LANGUAGES: { id: string; label: string; monaco: string }[] = [
  { id: 'python', label: 'Python', monaco: 'python' },
  { id: 'javascript', label: 'JavaScript', monaco: 'javascript' },
  { id: 'typescript', label: 'TypeScript', monaco: 'typescript' },
  { id: 'java', label: 'Java', monaco: 'java' },
  { id: 'c', label: 'C', monaco: 'c' },
  { id: 'cpp', label: 'C++', monaco: 'cpp' },
  { id: 'csharp', label: 'C#', monaco: 'csharp' },
  { id: 'go', label: 'Go', monaco: 'go' },
  { id: 'rust', label: 'Rust', monaco: 'rust' },
  { id: 'ruby', label: 'Ruby', monaco: 'ruby' },
  { id: 'php', label: 'PHP', monaco: 'php' },
  { id: 'kotlin', label: 'Kotlin', monaco: 'kotlin' },
  { id: 'swift', label: 'Swift', monaco: 'swift' },
  { id: 'bash', label: 'Bash', monaco: 'shell' },
]
const monacoLang = (id: string) => CODE_LANGUAGES.find((l) => l.id === id)?.monaco ?? (id === 'python3' ? 'python' : id)

function CodeEnvironment({ planId, moduleId, interviewId, language, value, onChange }: CodeEnvProps) {
  const [output, setOutput] = useState<{ stdout: string; stderr: string; exit_code: number } | null>(null)
  const [running, setRunning] = useState(false)
  // Question suggests a language, but the learner can switch.
  const [selectedLang, setSelectedLang] = useState(language === 'python3' ? 'python' : language)

  const handleRun = async () => {
    if (!value.trim()) return
    setRunning(true)
    setOutput(null)
    try {
      const { data } = await coursesAPI.runCode(planId, moduleId, interviewId, value, selectedLang)
      setOutput(data)
    } catch {
      setOutput({ stdout: '', stderr: 'Execution failed — check your code and try again.', exit_code: 1 })
    } finally {
      setRunning(false)
    }
  }

  const hasError = output && (output.exit_code !== 0 || output.stderr)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* Editor */}
      <div style={{
        border: '1px solid var(--line-1)',
        borderRadius: 10,
        overflow: 'hidden',
        background: '#1e1e1e',
      }}>
        {/* Editor toolbar */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '8px 14px',
          background: '#2d2d2d',
          borderBottom: '1px solid #3a3a3a',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <select
              value={selectedLang}
              onChange={(e) => setSelectedLang(e.target.value)}
              aria-label="Language"
              style={{
                fontSize: 11, fontFamily: 'var(--font-mono)', letterSpacing: '0.04em',
                background: '#1e1e1e', color: '#ddd', border: '1px solid #3a3a3a',
                borderRadius: 4, padding: '2px 6px', cursor: 'pointer',
              }}
            >
              {CODE_LANGUAGES.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
            </select>
          </div>
          <button
            onClick={handleRun}
            disabled={running || !value.trim()}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '4px 12px', borderRadius: 6,
              background: running ? '#3a3a3a' : '#22c55e',
              color: running ? '#888' : '#fff',
              fontSize: 12, fontWeight: 600, fontFamily: 'inherit',
              cursor: running ? 'default' : 'pointer',
              border: 'none',
              transition: 'background 0.15s ease',
            }}
          >
            {running
              ? <><Icon name="refresh" size={11} style={{ animation: 'spin 1s linear infinite' }} /> Running…</>
              : <><Icon name="play" size={11} /> Run Code</>
            }
          </button>
        </div>

        <Suspense fallback={
          <div style={{ height: 220, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#1e1e1e' }}>
            <span style={{ color: '#888', fontSize: 13 }}>Loading editor…</span>
          </div>
        }>
          <MonacoEditor
            height="220px"
            language={monacoLang(selectedLang)}
            value={value}
            onChange={(v) => onChange(v ?? '')}
            theme="vs-dark"
            options={{
              fontSize: 13,
              fontFamily: 'var(--font-mono)',
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              lineNumbers: 'on',
              wordWrap: 'on',
              padding: { top: 12, bottom: 12 },
              renderLineHighlight: 'gutter',
              automaticLayout: true,
              tabSize: 4,
            }}
          />
        </Suspense>
      </div>

      {/* Output panel */}
      {output && (
        <div style={{
          ...S.fadeIn,
          border: `1px solid ${hasError ? 'color-mix(in srgb, var(--neg) 30%, var(--line-1))' : 'color-mix(in srgb, var(--pos) 30%, var(--line-1))'}`,
          borderRadius: 10,
          overflow: 'hidden',
          background: 'var(--paper-0)',
        }}>
          <div style={{
            padding: '7px 14px',
            background: hasError ? 'color-mix(in srgb, var(--neg) 8%, var(--paper-1))' : 'color-mix(in srgb, var(--pos) 8%, var(--paper-1))',
            borderBottom: '1px solid var(--line-1)',
            display: 'flex', alignItems: 'center', gap: 6,
          }}>
            <span style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: hasError ? 'var(--neg)' : 'var(--pos)' }}>
              {hasError ? 'Error' : 'Output'}
            </span>
            <span style={{ fontSize: 10, color: 'var(--ink-4)', fontFamily: 'var(--font-mono)' }}>exit {output.exit_code}</span>
          </div>
          <pre style={{
            margin: 0, padding: '12px 14px',
            fontSize: 12, fontFamily: 'var(--font-mono)',
            color: hasError ? 'var(--neg)' : 'var(--ink-1)',
            whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            maxHeight: 160, overflowY: 'auto',
            lineHeight: 1.6,
          }}>
            {output.stderr || output.stdout || '(no output)'}
          </pre>
        </div>
      )}

      {!output && (
        <p style={{ margin: 0, fontSize: 12, color: 'var(--ink-4)', textAlign: 'center' }}>
          Write your solution above, then click Run to test it.
        </p>
      )}
    </div>
  )
}

// ── Step dots ─────────────────────────────────────────────────────────────────

function StepDots({ total, current, evals }: { total: number; current: number; evals: AnswerResult[] }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      {Array.from({ length: total }, (_, i) => {
        const done = i < current
        const active = i === current
        const score = evals[i]?.score ?? null
        const color = score != null ? (score >= 7 ? 'var(--pos)' : score >= 5 ? 'var(--warn)' : 'var(--neg)') : undefined
        return (
          <div key={i} style={{
            height: 6, borderRadius: 3,
            width: active ? 24 : 6,
            background: color ?? (done ? 'var(--pos)' : active ? 'var(--ink-0)' : 'var(--paper-3)'),
            transition: 'all 0.4s cubic-bezier(.4,0,.2,1)',
          }} />
        )
      })}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ModuleInterviewPage() {
  const { planId, moduleId } = useParams<{ planId: string; moduleId: string }>()
  const navigate = useNavigate()

  const [interview,          setInterview]          = useState<Interview | null>(null)
  const [phase,              setPhase]              = useState<Phase>('loading')
  const { steps: scoringSteps, applyStep: applyScoringStep, reset: resetScoring } = useAgentTimeline()
  const [currentQIdx,        setCurrentQIdx]        = useState(0)
  const [isRecording,        setIsRecording]        = useState(false)
  const [transcript,         setTranscript]         = useState('')
  const [interimTranscript,  setInterimTranscript]  = useState('')
  const [codeValue,          setCodeValue]          = useState('')
  const [currentEval,        setCurrentEval]        = useState<AnswerResult | null>(null)
  const [evalHistory,        setEvalHistory]        = useState<AnswerResult[]>([])
  const [finalResult,        setFinalResult]        = useState<FinalResult | null>(null)
  const [isSpeaking,         setIsSpeaking]         = useState(false)
  const [displayedQ,         setDisplayedQ]         = useState('')

  const mediaRef       = useRef<MediaRecorder | null>(null)
  const recognitionRef = useRef<any>(null)
  const transcriptRef  = useRef('')

  const { data: plan } = useQuery({
    queryKey: ['course', planId],
    queryFn: () => coursesAPI.get(planId!).then((r) => r.data),
    enabled: !!planId,
    staleTime: 1000 * 60 * 5,
    gcTime: 1000 * 60 * 15,
  })
  const currentModule = plan?.modules.find((m) => m.id === moduleId)

  // Start interview on mount
  useEffect(() => {
    if (!planId || !moduleId) return
    coursesAPI.startInterview(planId, moduleId)
      .then((r) => { setInterview(r.data); setPhase('intro') })
      .catch(() => { toast.error('Could not start interview'); navigate(`/courses/${planId}`) })
  }, [planId, moduleId])

  const currentQuestion = interview?.questions[currentQIdx]
  const isCoding = !!currentQuestion?.is_coding_question
  const codingLang = currentQuestion?.language ?? 'python'

  // Typewriter for question text
  useEffect(() => {
    if (!currentQuestion) return
    if (phase !== 'question') { setDisplayedQ(currentQuestion.text); return }
    let i = 0
    setDisplayedQ('')
    const full = currentQuestion.text
    const id = setInterval(() => { i++; setDisplayedQ(full.slice(0, i)); if (i >= full.length) clearInterval(id) }, 20)
    return () => clearInterval(id)
  }, [currentQuestion?.id, phase])

  // Reset code editor when question changes
  useEffect(() => { setCodeValue('') }, [currentQIdx])

  // Auto-speak question (verbal only)
  useEffect(() => {
    if (phase !== 'question' || !currentQuestion || isCoding) return
    const t = setTimeout(() => {
      setIsSpeaking(true)
      const utt = new SpeechSynthesisUtterance(`Question ${currentQIdx + 1}. ${currentQuestion.text}`)
      utt.rate = 0.92
      const v = window.speechSynthesis?.getVoices().find((v) => v.lang.startsWith('en') && v.localService)
      if (v) utt.voice = v
      utt.onend = () => setIsSpeaking(false)
      utt.onerror = () => setIsSpeaking(false)
      window.speechSynthesis?.cancel()
      window.speechSynthesis?.speak(utt)
    }, 400)
    return () => { clearTimeout(t); window.speechSynthesis?.cancel(); setIsSpeaking(false) }
  }, [currentQIdx, phase, isCoding])

  // Cleanup media resources when the component unmounts mid-interview
  useEffect(() => {
    return () => {
      window.speechSynthesis?.cancel()
      if (mediaRef.current && mediaRef.current.state !== 'inactive') {
        try { mediaRef.current.stop() } catch { /* ignore */ }
      }
      if (recognitionRef.current) {
        try { recognitionRef.current.stop() } catch { /* ignore */ }
        recognitionRef.current = null
      }
    }
  }, [])

  const updateTranscript = useCallback((upd: string | ((p: string) => string)) => {
    setTranscript((prev) => {
      const next = typeof upd === 'function' ? upd(prev) : upd
      transcriptRef.current = next
      return next
    })
  }, [])

  const startRecording = async () => {
    updateTranscript('')
    setInterimTranscript('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const rec = new MediaRecorder(stream)
      rec.onstop = () => stream.getTracks().forEach((t) => t.stop())
      rec.start()
      mediaRef.current = rec
    } catch { /* mic unavailable */ }

    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (SR) {
      const rec = new SR()
      rec.continuous = true; rec.interimResults = true; rec.lang = 'en-US'
      rec.onresult = (e: any) => {
        let fin = '', int = ''
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const r = e.results[i]?.[0]; if (!r) continue
          if (e.results[i].isFinal) fin += r.transcript + ' '
          else int += r.transcript
        }
        if (fin) updateTranscript((p) => p + fin)
        setInterimTranscript(int)
      }
      rec.onerror = () => {}
      rec.start()
      recognitionRef.current = rec
    } else {
      toast('Speech recognition not available — type your answer below', { icon: 'ℹ️' })
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
    setTimeout(() => evaluateAnswer(transcriptRef.current || '[No answer recorded]'), 300)
  }

  const evaluateAnswer = async (answerText: string) => {
    if (!interview || !currentQuestion) return
    try {
      const { data } = await coursesAPI.submitAnswer(planId!, moduleId!, interview.interview_id, currentQuestion.id, answerText)
      const result = data as AnswerResult
      setCurrentEval(result)
      setEvalHistory((prev) => [...prev, result])
      setPhase('feedback')
      if (!isCoding) {
        const utt = new SpeechSynthesisUtterance(`Score: ${result.score} out of 10. ${result.feedback}`)
        utt.rate = 0.92
        window.speechSynthesis?.cancel()
        window.speechSynthesis?.speak(utt)
      }
    } catch {
      toast.error('Evaluation failed — try again')
      setPhase('question')
    }
  }

  const handleSubmitCode = () => {
    window.speechSynthesis?.cancel()
    setPhase('evaluating')
    const combined = codeValue.trim()
      ? `[Code Answer]\n\`\`\`${codingLang}\n${codeValue}\n\`\`\``
      : '[No code submitted]'
    setTimeout(() => evaluateAnswer(combined), 200)
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
    resetScoring()
    window.speechSynthesis?.cancel()
    let scored: FinalResult | null = null
    try {
      await streamSSE(
        `/courses/${planId}/modules/${moduleId}/interview/${interview.interview_id}/complete/stream`,
        {},
        (event) => {
          if (event.type === 'step') {
            applyScoringStep(event as unknown as { id: string; label: string; status: 'active' | 'done' | 'error' })
          } else if (event.type === 'action' && event.kind === 'interview_scored') {
            scored = event.payload as FinalResult
          } else if (event.type === 'error') {
            toast.error(String(event.message ?? 'Could not finalize interview'))
          }
        },
      )
      if (!scored) throw new Error('no result')
      const r = scored as FinalResult
      setFinalResult(r)
      setPhase('complete')
      const utt = new SpeechSynthesisUtterance(
        r.passed
          ? `Congratulations! You scored ${r.final_score.toFixed(1)} out of 10 and passed.`
          : `You scored ${r.final_score.toFixed(1)} out of 10. Review and try again.`
      )
      utt.rate = 0.92
      window.speechSynthesis?.speak(utt)
    } catch {
      toast.error('Could not finalize interview')
      setPhase('feedback')
    }
  }

  const totalQ = interview?.questions.length ?? 1
  const headerProgress = phase === 'intro' ? 0
    : ((currentQIdx + (phase === 'feedback' || phase === 'evaluating' ? 1 : 0)) / totalQ) * 100

  // ── Layouts ──────────────────────────────────────────────────────────────────

  if (phase === 'loading') {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 12 }}>
        <div style={{ width: 40, height: 40, borderRadius: '50%', border: '3px solid var(--line-2)', borderTopColor: 'var(--ink-0)', animation: 'spin 0.8s linear infinite' }} />
        <span className="t-sm fg-3">Starting interview…</span>
      </div>
    )
  }

  if (phase === 'scoring') {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        <div style={{ ...S.card, maxWidth: 420, textAlign: 'center' }}>
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 20 }}>
            <div style={{ width: 56, height: 56, borderRadius: '50%', background: 'var(--paper-2)', display: 'grid', placeItems: 'center', animation: 'pulse-soft 1.8s ease-in-out infinite' }}>
              <Icon name="sparkle" size={24} style={{ color: 'var(--accent)' }} />
            </div>
          </div>
          <h2 className="serif" style={{ fontSize: 22, fontWeight: 400, marginBottom: 8 }}>Computing your score</h2>
          <p className="t-sm fg-2" style={{ marginBottom: 24 }}>AI is cross-checking all answers against module knowledge…</p>
          <div style={{ display: 'inline-flex', justifyContent: 'flex-start', textAlign: 'left' }}>
            <AgentTimeline steps={scoringSteps} />
          </div>
        </div>
      </div>
    )
  }

  if (phase === 'complete' && finalResult) {
    return (
      <div style={{ height: '100%', overflowY: 'auto', display: 'flex', alignItems: 'flex-start', justifyContent: 'center', padding: '32px 16px' }}>
        <div style={{ ...S.card, ...S.fadeIn, maxWidth: 560 }}>
          <div style={{ textAlign: 'center', marginBottom: 24 }}>
            <h2 className="serif" style={{ fontSize: 26, fontWeight: 400, marginBottom: 16 }}>Interview Complete</h2>
            <ScoreRing score={finalResult.final_score} />
            <div style={{ margin: '14px 0 0' }}>
              <Badge tone={finalResult.passed ? 'pos' : 'neg'} size="sm">
                {finalResult.passed ? 'Module Passed ✓' : 'Not Passed — Review & Retry'}
              </Badge>
            </div>
          </div>

          {finalResult.summary && (
            <div style={{ background: 'color-mix(in srgb, var(--accent) 8%, var(--paper-1))', border: '1px solid color-mix(in srgb, var(--accent) 20%, transparent)', borderRadius: 10, padding: '12px 16px', marginBottom: 20 }}>
              <div className="caps" style={{ color: 'var(--accent)', marginBottom: 4, fontSize: 10 }}>AI Assessment</div>
              <div className="t-sm fg-1" style={{ lineHeight: 1.65 }}>{finalResult.summary}</div>
            </div>
          )}

          {finalResult.scoring_matrix?.length > 0 && (
            <div style={{ marginBottom: 20 }}>
              <div className="caps fg-3" style={{ marginBottom: 10, fontSize: 10 }}>Question Breakdown</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {finalResult.scoring_matrix.map((entry, i) => (
                  <div key={i} style={{ background: 'var(--paper-2)', borderRadius: 10, padding: '12px 14px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                      <span className="t-xs fg-3" style={{ fontWeight: 500 }}>Q{entry.question_id}</span>
                      <Badge tone={entry.score >= 7 ? 'pos' : entry.score >= 5 ? 'warn' : 'neg'} size="xs">{entry.score}/10</Badge>
                    </div>
                    <div className="t-xs fg-2" style={{ marginBottom: 8, lineHeight: 1.55 }}>{entry.justification}</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {entry.concepts_covered?.map((c) => <Badge key={c} tone="pos" size="xs">{c}</Badge>)}
                      {entry.concepts_missed?.map((c) => <Badge key={c} tone="neg" size="xs">✕ {c}</Badge>)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div style={{ display: 'flex', gap: 8 }}>
            <Button variant="secondary" full onClick={() => navigate(`/courses/${planId}`)}>Back to Plan</Button>
            {!finalResult.passed && (
              <Button variant="primary" full onClick={() => window.location.reload()}>Retry</Button>
            )}
          </div>
        </div>
      </div>
    )
  }

  // ── Main interview shell ──────────────────────────────────────────────────────

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--paper-0)', overflow: 'hidden' }}>

      {/* ── Header ────────────────────────────────────────────────────────────── */}
      <div style={{ flexShrink: 0, borderBottom: '1px solid var(--line-1)', background: 'var(--paper-1)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 18px' }}>
          <button
            onClick={() => { window.speechSynthesis?.cancel(); navigate(`/courses/${planId}`) }}
            style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--ink-2)', cursor: 'pointer', flexShrink: 0, fontSize: 13, fontFamily: 'inherit' }}
          >
            <Icon name="arrow-left" size={13} /> Back
          </button>

          {currentModule && (
            <span className="t-xs fg-3" style={{ flexShrink: 0, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {currentModule.title}
            </span>
          )}

          <div style={{ flex: 1, height: 3, borderRadius: 2, background: 'var(--paper-3)', overflow: 'hidden' }}>
            <div style={{ height: '100%', borderRadius: 2, background: 'var(--ink-0)', width: `${headerProgress}%`, transition: 'width 0.6s cubic-bezier(.4,0,.2,1)' }} />
          </div>

          <span className="t-xs fg-3 mono" style={{ flexShrink: 0 }}>
            {phase === 'intro' ? 'Intro' : `${currentQIdx + 1} / ${totalQ}`}
          </span>
        </div>
      </div>

      {/* ── Body ──────────────────────────────────────────────────────────────── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '24px 16px 32px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <div style={{ width: '100%', maxWidth: 640, display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* ── Intro ─────────────────────────────────────────────────────── */}
          {phase === 'intro' && (
            <div style={{ ...S.card, ...S.fadeIn }}>
              <div style={{ textAlign: 'center', marginBottom: 24 }}>
                <div style={{ width: 52, height: 52, borderRadius: '50%', background: 'var(--ink-0)', color: 'var(--paper-0)', display: 'grid', placeItems: 'center', margin: '0 auto 16px' }}>
                  <Icon name="mic" size={22} />
                </div>
                <h2 className="serif" style={{ fontSize: 22, fontWeight: 400, marginBottom: 6 }}>Ready to be assessed?</h2>
                <p className="t-sm fg-2">{interview?.questions.length} questions on <strong>{currentModule?.title}</strong></p>
                <p className="t-xs fg-3" style={{ marginTop: 4 }}>Pass threshold: 6 / 10 per question average</p>
              </div>

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, justifyContent: 'center', marginBottom: 22 }}>
                {currentModule?.topics.map((t) => <Badge key={t} tone="outline" size="xs">{t}</Badge>)}
              </div>

              {/* Question type preview */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 24 }}>
                {interview?.questions.map((q, i) => (
                  <div key={q.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderRadius: 8, background: 'var(--paper-2)' }}>
                    <span className="t-xs mono fg-3" style={{ minWidth: 18 }}>Q{i + 1}</span>
                    {q.is_coding_question
                      ? <Badge tone="warn" size="xs" icon="code">Coding · {q.language ?? 'python'}</Badge>
                      : <Badge tone="outline" size="xs" icon="mic">Verbal</Badge>
                    }
                    <span className="t-xs fg-2" style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{q.text.slice(0, 60)}{q.text.length > 60 ? '…' : ''}</span>
                  </div>
                ))}
              </div>

              <Button variant="primary" full iconRight="arrow" onClick={() => setPhase('question')}>
                Start Interview
              </Button>
            </div>
          )}

          {/* ── Question phase ────────────────────────────────────────────── */}
          {(phase === 'question' || phase === 'recording') && currentQuestion && (
            <div style={{ ...S.fadeIn, display: 'flex', flexDirection: 'column', gap: 14 }}>

              {/* Question card */}
              <div style={{ ...S.card }}>
                {/* AI interviewer row */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
                  <div style={{
                    width: 34, height: 34, borderRadius: '50%', flexShrink: 0,
                    background: isSpeaking ? 'var(--accent)' : 'var(--ink-1)',
                    color: 'var(--paper-0)', display: 'grid', placeItems: 'center',
                    transition: 'background 0.4s ease',
                    boxShadow: isSpeaking ? '0 0 0 4px color-mix(in srgb, var(--accent) 22%, transparent)' : 'none',
                  }}>
                    <Icon name="sparkle" size={15} />
                  </div>
                  <div>
                    <span className="t-sm fg-0" style={{ fontWeight: 600 }}>AI Interviewer</span>
                    <span className="t-xs fg-3" style={{ marginLeft: 8 }}>{isSpeaking ? 'Speaking…' : 'Listening'}</span>
                  </div>
                  <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
                    {currentQuestion.is_coding_question && (
                      <Badge tone="warn" size="xs" icon="code">Coding</Badge>
                    )}
                    <Badge tone="outline" size="xs">{currentQuestion.expected_depth}</Badge>
                  </div>
                </div>

                {/* Question text */}
                <p className="serif" style={{
                  fontSize: 'clamp(16px, 3vw, 20px)', lineHeight: 1.5, fontWeight: 400,
                  color: 'var(--ink-0)', margin: 0, minHeight: 48,
                }}>
                  {displayedQ}
                  {displayedQ.length < currentQuestion.text.length && (
                    <span style={{ display: 'inline-block', width: 2, height: '0.85em', background: 'var(--accent)', marginLeft: 3, verticalAlign: 'text-bottom', animation: 'blink 0.8s step-end infinite' }} />
                  )}
                </p>
              </div>

              {/* Answer zone */}
              {isCoding ? (
                // ── Coding environment ──
                <div style={S.card}>
                  <div className="caps fg-3" style={{ fontSize: 10, marginBottom: 12 }}>Write your solution</div>
                  <CodeEnvironment
                    planId={planId!}
                    moduleId={moduleId!}
                    interviewId={interview!.interview_id}
                    language={codingLang}
                    value={codeValue}
                    onChange={setCodeValue}
                  />
                  <div style={{ marginTop: 14 }}>
                    <Button
                      variant="primary"
                      full
                      iconRight="arrow"
                      onClick={handleSubmitCode}
                      disabled={!codeValue.trim()}
                    >
                      Submit Answer
                    </Button>
                  </div>
                </div>
              ) : (
                // ── Verbal answer zone ──
                <div style={S.card}>
                  <div className="caps fg-3" style={{ fontSize: 10, marginBottom: 12 }}>Your answer</div>
                  <Transcript confirmed={transcript} interim={isRecording ? interimTranscript : ''} />

                  {/* Typed fallback */}
                  {!isRecording && (
                    <textarea
                      value={transcript}
                      onChange={(e) => updateTranscript(e.target.value)}
                      placeholder="Or type your answer here…"
                      style={{
                        marginTop: 10, width: '100%', boxSizing: 'border-box',
                        background: 'var(--paper-0)', border: '1px solid var(--line-1)',
                        borderRadius: 8, padding: '10px 12px', fontSize: 13,
                        color: 'var(--ink-0)', fontFamily: 'inherit', outline: 'none',
                        resize: 'vertical', minHeight: 68, maxHeight: 200,
                        wordBreak: 'break-word', overflowWrap: 'break-word', whiteSpace: 'pre-wrap',
                      }}
                    />
                  )}

                  {/* Mic button */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 16, justifyContent: 'center', flexWrap: 'wrap' }}>
                    <div style={{ position: 'relative', display: 'grid', placeItems: 'center', width: 64, height: 64 }}>
                      {isRecording && [0, 1, 2].map((i) => (
                        <div key={i} style={{
                          position: 'absolute', width: 64, height: 64, borderRadius: '50%',
                          border: '1.5px solid var(--neg)',
                          animation: `rippleRing 1.8s ease-out ${i * 0.55}s infinite`,
                          pointerEvents: 'none',
                        }} />
                      ))}
                      <button
                        onClick={isRecording ? stopRecording : startRecording}
                        style={{
                          width: 56, height: 56, borderRadius: '50%',
                          background: isRecording ? 'var(--neg)' : 'var(--ink-0)',
                          color: 'var(--paper-0)', border: 'none', cursor: 'pointer',
                          display: 'grid', placeItems: 'center', position: 'relative', zIndex: 1,
                          transition: 'background 0.2s ease, transform 0.1s ease',
                          boxShadow: 'var(--shadow-2)',
                        }}
                        onMouseDown={(e) => (e.currentTarget.style.transform = 'scale(0.92)')}
                        onMouseUp={(e) => (e.currentTarget.style.transform = 'scale(1)')}
                        onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
                      >
                        <Icon name="mic" size={22} />
                      </button>
                    </div>
                    <MicWave active={isRecording} />
                    <span className="t-xs fg-3">{isRecording ? 'Tap to stop' : 'Tap to record'}</span>
                  </div>

                  {/* Submit typed answer */}
                  {!isRecording && transcript.trim() && (
                    <Button variant="primary" full style={{ marginTop: 12 }} onClick={() => evaluateAnswer(transcript)}>
                      Submit Answer
                    </Button>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ── Evaluating ────────────────────────────────────────────────── */}
          {phase === 'evaluating' && (
            <div style={{ ...S.card, ...S.fadeIn, textAlign: 'center' }}>
              <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
                <div style={{ width: 44, height: 44, borderRadius: '50%', background: 'var(--paper-2)', display: 'grid', placeItems: 'center' }}>
                  <Icon name="sparkle" size={20} style={{ color: 'var(--accent)', animation: 'pulse-soft 1.2s ease-in-out infinite' }} />
                </div>
              </div>
              <p className="t-md fg-0" style={{ marginBottom: 6, fontWeight: 500 }}>Evaluating your answer</p>
              <p className="t-sm fg-3">Checking key concepts and depth…</p>
            </div>
          )}

          {/* ── Per-question feedback ─────────────────────────────────────── */}
          {phase === 'feedback' && currentEval && (
            <div style={{ ...S.card, ...S.fadeIn }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
                <span className="t-sm fg-2" style={{ fontWeight: 500 }}>Q{currentQIdx + 1} result</span>
                <Badge tone={currentEval.score >= 7 ? 'pos' : currentEval.score >= 5 ? 'warn' : 'neg'} size="sm">
                  {currentEval.score}/10
                </Badge>
              </div>

              {/* Transcribed answer (handle code vs verbal) */}
              <div style={{ background: 'var(--paper-2)', borderRadius: 8, padding: '10px 14px', marginBottom: 14 }}>
                <div className="t-xs fg-3" style={{ marginBottom: 4 }}>Your answer</div>
                {currentEval.answer_text.startsWith('[Code Answer]') ? (
                  <pre style={{ margin: 0, fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--ink-1)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 140, overflowY: 'auto' }}>
                    {currentEval.answer_text.replace('[Code Answer]\n', '')}
                  </pre>
                ) : (
                  <div className="t-sm fg-1" style={{ fontStyle: 'italic', lineHeight: 1.6, wordBreak: 'break-word', whiteSpace: 'pre-wrap' }}>"{currentEval.answer_text}"</div>
                )}
              </div>

              {/* AI feedback */}
              <div style={{ background: 'color-mix(in srgb, var(--accent) 8%, var(--paper-1))', border: '1px solid color-mix(in srgb, var(--accent) 20%, transparent)', borderRadius: 8, padding: '12px 14px', marginBottom: 16 }}>
                <div className="t-xs" style={{ color: 'var(--accent)', marginBottom: 4, fontWeight: 500 }}>Feedback</div>
                <div className="t-sm fg-1" style={{ lineHeight: 1.65 }}>{currentEval.feedback}</div>
                {currentEval.key_points_covered?.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 10 }}>
                    {currentEval.key_points_covered.map((kp) => <Badge key={kp} tone="pos" size="xs">{kp}</Badge>)}
                  </div>
                )}
              </div>

              <Button variant="primary" full iconRight="arrow" onClick={handleNext}>
                {currentQIdx < (interview?.questions.length ?? 0) - 1 ? 'Next Question' : 'Submit for Final Scoring'}
              </Button>
            </div>
          )}

        </div>
      </div>

      {/* ── Footer: step dots ─────────────────────────────────────────────────── */}
      {interview && !['intro', 'loading', 'scoring', 'complete'].includes(phase) && (
        <div style={{ flexShrink: 0, padding: '10px 18px', borderTop: '1px solid var(--line-1)', background: 'var(--paper-1)', display: 'flex', justifyContent: 'center' }}>
          <StepDots total={totalQ} current={currentQIdx} evals={evalHistory} />
        </div>
      )}
    </div>
  )
}

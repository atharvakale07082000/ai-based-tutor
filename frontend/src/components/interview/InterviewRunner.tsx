import { useState, useEffect, useRef, useCallback, lazy, Suspense } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/Button'
import { Select } from '@/components/ui/Select'
import { Badge } from '@/components/ui/Badge'
import { Icon } from '@/components/ui/Icon'
import { ReasoningStream } from '@/components/agents/ReasoningStream'
import { useAgentTimeline } from '@/hooks/useAgentTimeline'
import { api, streamSSE, type InterviewQuestion, type InterviewState } from '@/lib/api'
import type { InterviewEndpoints } from './endpoints'

// Lazy-load Monaco so it doesn't bloat the initial bundle
const MonacoEditor = lazy(() => import('@monaco-editor/react'))

// ── Types ─────────────────────────────────────────────────────────────────────

type Phase =
  | 'loading' | 'resume' | 'intro' | 'question' | 'recording'
  | 'evaluating' | 'feedback' | 'scoring' | 'complete' | 'error'

// Fallback cap, mirrored from backend settings.INTERVIEW_MAX_QUESTIONS. The real ceiling arrives
// on the `interview_started`/`question`/`evaluation` frames (and in the resume payload); this is
// only what we show before the first frame lands.
const MAX_Q = 8

// Mirrors backend agents/bar.py::DEFAULT_BAR — what a module interview passes at. A job-loop
// round overrides it with the seniority-calibrated bar via the `bar` prop.
const DEFAULT_BAR = 6.0

// ── Web Speech API ────────────────────────────────────────────────────────────
// Not in TypeScript's DOM lib (still a draft spec, webkit-prefixed in Chrome/Safari), so the
// slice we actually use is typed here rather than reached for through `any`.

interface SpeechAlternative { transcript: string }
interface SpeechResult { isFinal: boolean; readonly length: number; [i: number]: SpeechAlternative | undefined }
interface SpeechResultList { readonly length: number; [i: number]: SpeechResult | undefined }
interface SpeechRecognitionEventLike { resultIndex: number; results: SpeechResultList }
interface SpeechRecognitionLike {
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((e: SpeechRecognitionEventLike) => void) | null
  onerror: (() => void) | null
  start: () => void
  stop: () => void
}

function getSpeechRecognitionCtor(): (new () => SpeechRecognitionLike) | undefined {
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike
    webkitSpeechRecognition?: new () => SpeechRecognitionLike
  }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition
}

// Map a `question` SSE frame (untyped Record) into a typed question.
function toQuestion(e: Record<string, unknown>): InterviewQuestion {
  return {
    id: Number(e.id ?? 0),
    text: String(e.text ?? ''),
    is_coding_question: Boolean(e.is_coding_question),
    language: (e.language as string | null) ?? null,
    expected_depth: String(e.expected_depth ?? 'conceptual'),
  }
}

interface AnswerResult {
  question_id: number
  /** null when the answer was recorded but never graded (resumed sessions only). */
  score: number | null
  feedback: string
  answer_text: string
  key_points_covered: string[]
}

const scoreTone = (score: number | null) =>
  score == null ? 'outline' : score >= 7 ? 'pos' : score >= 5 ? 'warn' : 'neg'

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

// ── Resume support ────────────────────────────────────────────────────────────
// The whole interview lives server-side (the interview doc + the agent's paused Strands
// session); the browser only holds the id that unlocks it. Keeping that id in localStorage —
// scoped per plan+module — is what lets a reloaded tab or a dropped connection get back in
// instead of abandoning every answered question.

// localStorage throws in private mode / when the quota is full — never let that break the page.
function rememberInterview(key: string, interviewId?: string) {
  if (!interviewId) return
  try { window.localStorage.setItem(key, interviewId) } catch { /* no persistence */ }
}
function recallInterview(key: string): string | null {
  try { return window.localStorage.getItem(key) } catch { return null }
}
function forgetInterview(key: string) {
  try { window.localStorage.removeItem(key) } catch { /* nothing to clear */ }
}

/** Per-answer feedback cards, rebuilt from the server's projection. */
const historyFromState = (s: InterviewState): AnswerResult[] =>
  s.answers.map((a) => ({
    question_id: a.question_id,
    score: a.score,
    feedback: a.feedback ?? '',
    answer_text: a.answer_text ?? '',
    key_points_covered: a.key_points_covered ?? [],
  }))

/**
 * The questions already answered. Only their count and ids matter after a resume (they position
 * the step dots and the "Question n" counter) — the learner is put back on `current_question`.
 */
const askedFromState = (s: InterviewState): InterviewQuestion[] =>
  s.answers.map((a) => ({
    id: a.question_id,
    text: a.question_text ?? '',
    is_coding_question: (a.answer_text ?? '').startsWith('[Code Answer]'),
    language: null,
    expected_depth: 'conceptual',
  }))

/**
 * Rebuild the result screen for an interview that was already graded. The read endpoint
 * withholds the grader's rationale (`scoring_matrix`/`summary`) by design, so the breakdown is
 * reconstructed from the per-answer feedback the learner had already been shown.
 */
const finalFromState = (s: InterviewState): FinalResult => ({
  final_score: s.final_score ?? 0,
  passed: !!s.passed,
  scoring_matrix: s.answers.map((a) => ({
    question_id: a.question_id,
    score: a.score ?? 0,
    justification: a.feedback ?? '',
    concepts_covered: a.key_points_covered ?? [],
    concepts_missed: [],
  })),
  summary: '',
  total_questions: s.answers.length,
})

function formatStarted(iso: string | null | undefined): string | null {
  if (!iso) return null
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
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
        <span className="display tnum" style={{ fontSize: 28, fontWeight: 600, lineHeight: 1 }}>{score.toFixed(1)}</span>
        <span className="t-xs fg-3 mono">/ {outOf}</span>
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
  runCodeUrl: string
  language: string
  value: string
  onChange: (v: string) => void
}

// Languages the editor offers (matches backend code_runner.SUPPORTED_LANGUAGES). `monaco` = the
// Monaco highlighting id; `id` is what we send to the run-code API.
const CODE_LANGUAGES: { id: string; label: string; monaco: string }[] = [
  { id: 'python', label: 'Python', monaco: 'python' },
  { id: 'sql', label: 'SQL', monaco: 'sql' },
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

// Query languages have no stdout to predict. The learner writes them in a normal
// editor and the AI interviewer evaluates the answer when it's submitted.
const QUERY_LANGS = new Set(['sql'])

// Backend returns mode 'ai-review' (an LLM read the code) or 'executed' (real Piston run).
type CodeCheck = {
  stdout: string
  stderr: string
  exit_code: number
  mode?: 'ai-review' | 'executed'
  review?: {
    verdict: 'looks_correct' | 'has_issues' | 'will_not_run'
    predicted_output: string
    issues: string[]
    notes: string
  } | null
}

const VERDICT_LABEL: Record<string, string> = {
  looks_correct: 'AI Review · Looks correct',
  has_issues: 'AI Review · Issues found',
  will_not_run: 'AI Review · Would not run',
}

function CodeEnvironment({ runCodeUrl, language, value, onChange }: CodeEnvProps) {
  const [output, setOutput] = useState<CodeCheck | null>(null)
  const [running, setRunning] = useState(false)
  // Question suggests a language, but the learner can switch.
  const [selectedLang, setSelectedLang] = useState(language === 'python3' ? 'python' : language)
  const isRunnable = !QUERY_LANGS.has(selectedLang)

  const handleRun = async () => {
    if (!value.trim()) return
    setRunning(true)
    setOutput(null)
    try {
      const { data } = await api.post<CodeCheck>(runCodeUrl, { code: value, language: selectedLang })
      setOutput(data)
    } catch {
      setOutput({ stdout: '', stderr: 'Check failed — please try again in a moment.', exit_code: 1 })
    } finally {
      setRunning(false)
    }
  }

  const review = output?.review ?? null
  // Flag issues as well as hard failures, so 'has_issues' doesn't read as a clean pass.
  const hasError = !!output && (output.exit_code !== 0 || !!output.stderr || review?.verdict === 'has_issues')
  const panelLabel = review
    ? VERDICT_LABEL[review.verdict]
    : hasError ? 'Error' : 'Output'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* Editor */}
      <div style={{
        border: '1px solid var(--line-1)',
        borderRadius: 10,
        overflow: 'hidden',
        background: 'var(--code-bg)',
      }}>
        {/* Editor toolbar */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '8px 14px',
          background: 'var(--code-panel)',
          borderBottom: '1px solid var(--code-line)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <Select
              value={selectedLang}
              onChange={(e) => setSelectedLang(e.target.value)}
              aria-label="Language"
              tone="code"
              size="xs"
            >
              {CODE_LANGUAGES.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
            </Select>
          </div>
          {isRunnable ? (
            <button
              onClick={handleRun}
              disabled={running || !value.trim()}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '4px 12px', borderRadius: 'var(--r-2)',
                background: running ? 'var(--code-line)' : 'var(--pos)',
                color: running ? 'var(--code-faint)' : '#fff',
                fontSize: 12, fontWeight: 600, fontFamily: 'inherit',
                cursor: running ? 'default' : 'pointer',
                border: 'none',
                transition: 'background 0.15s ease',
              }}
            >
              {running
                ? <><Icon name="refresh" size={11} style={{ animation: 'spin 1s linear infinite' }} /> Checking…</>
                : <><Icon name="play" size={11} /> Check Code</>
              }
            </button>
          ) : (
            // Query languages (e.g. SQL) can't be executed — the AI interviewer grades the answer.
            <span style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--code-faint)', fontFamily: 'var(--font-mono)' }}>
              <Icon name="sparkle" size={11} style={{ color: 'var(--code-faint)' }} /> AI-evaluated
            </span>
          )}
        </div>

        <Suspense fallback={
          <div style={{ height: 220, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--code-bg)' }}>
            <span style={{ color: 'var(--code-faint)', fontSize: 13 }}>Loading editor…</span>
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

      {/* Query-language hint (no compiler) */}
      {!isRunnable && (
        <div className="t-xs fg-3" style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '0 2px' }}>
          <Icon name="info" size={12} style={{ color: 'var(--ink-3)' }} />
          Write your query here — the AI interviewer reads and grades it when you submit. There's nothing to run.
        </div>
      )}

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
              {panelLabel}
            </span>
            {/* An exit code is only meaningful when the code actually ran. */}
            {!review && (
              <span style={{ fontSize: 10, color: 'var(--ink-4)', fontFamily: 'var(--font-mono)' }}>exit {output.exit_code}</span>
            )}
          </div>
          <pre style={{
            margin: 0, padding: '12px 14px',
            fontSize: 12, fontFamily: 'var(--font-mono)',
            color: hasError ? 'var(--neg)' : 'var(--ink-1)',
            whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            maxHeight: 160, overflowY: 'auto',
            lineHeight: 1.6,
          }}>
            {output.stderr || output.stdout || (review ? '(no output predicted)' : '(no output)')}
          </pre>

          {/* Interviewer's findings — only present on the AI-review path. */}
          {review && (review.issues.length > 0 || review.notes) && (
            <div style={{ padding: '10px 14px', borderTop: '1px solid var(--line-1)', display: 'flex', flexDirection: 'column', gap: 6 }}>
              {review.issues.map((issue, i) => (
                <div key={i} className="t-xs fg-2" style={{ display: 'flex', gap: 7, alignItems: 'flex-start', lineHeight: 1.5 }}>
                  <Icon name="info" size={12} style={{ color: 'var(--neg)', flexShrink: 0, marginTop: 2 }} />
                  <span>{issue}</span>
                </div>
              ))}
              {review.notes && (
                <div className="t-xs fg-3" style={{ display: 'flex', gap: 7, alignItems: 'flex-start', lineHeight: 1.5 }}>
                  <Icon name="sparkle" size={12} style={{ color: 'var(--ink-3)', flexShrink: 0, marginTop: 2 }} />
                  <span>{review.notes}</span>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {!output && (
        <p style={{ margin: 0, fontSize: 12, color: 'var(--ink-4)', textAlign: 'center' }}>
          Write your solution above, then click Check to have the interviewer review it.
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

// ── The runner ────────────────────────────────────────────────────────────────

export interface InterviewSubject {
  title: string
  topics: string[]
  /** One line under the title: what this interview is, in the caller's words. */
  blurb?: string
}

interface InterviewRunnerProps {
  /** Which API this interview's turns live on (module interview vs. loop round). */
  endpoints: InterviewEndpoints
  /** What the interview is about. `undefined` while the caller is still loading it. */
  subject?: InterviewSubject
  /** The score this interview must reach to pass, when the caller knows it up front. */
  bar?: number
  /**
   * This interview's question ceiling, when the caller knows it up front. A loop round
   * sets its own (a system-design round is one deep question); a module interview learns
   * the platform default from the first stream frame.
   */
  maxQuestions?: number
  /**
   * An interview the caller already knows about, used when this browser has nothing in
   * localStorage — e.g. reviewing a round that was graded on another device. Without it a
   * finished interview is unreachable and the learner just gets the intro again.
   */
  knownInterviewId?: string | null
}

export default function InterviewRunner({
  endpoints, subject, bar, maxQuestions: maxQProp, knownInterviewId,
}: InterviewRunnerProps) {
  const navigate = useNavigate()

  const [interviewId,        setInterviewId]        = useState<string | null>(null)
  const [questions,          setQuestions]          = useState<InterviewQuestion[]>([])
  const [finished,           setFinished]           = useState(false)
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
  // Ceiling the agent is working towards (backend INTERVIEW_MAX_QUESTIONS), learnt from the
  // stream frames / resume payload so the learner always sees how far the interview can run.
  const [maxQuestions,       setMaxQuestions]       = useState(maxQProp ?? MAX_Q)
  // A recoverable interview found on mount — offered, never forced.
  const [resumeState,        setResumeState]        = useState<InterviewState | null>(null)
  const [resumeChecked,      setResumeChecked]      = useState(false)
  // Non-null while we're talking to the resume endpoint — doubles as the spinner's caption.
  const [restoring,          setRestoring]          = useState<string | null>(null)
  const [restoredResult,     setRestoredResult]     = useState(false)
  // Mid-interview failure: the server still has everything, so we offer a real retry.
  const [recovery,           setRecovery]           = useState<{ message: string; action: 'resync' | 'complete' | 'restart' } | null>(null)
  // True while an answer turn's SSE stream is still open. The score arrives before the
  // agent has composed the next question, so without this the UI would treat that gap as
  // "no more questions" and offer final scoring mid-interview.
  const [turnStreaming,      setTurnStreaming]      = useState(false)

  const mediaRef       = useRef<MediaRecorder | null>(null)
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const transcriptRef  = useRef('')

  const currentModule = subject

  // Show the intro once the subject (title/topics) has loaded AND we know whether there's an
  // interview to resume — otherwise the intro would flash before the resume offer replaces it.
  // Questions are NOT fetched up front: the agent generates them one at a time once we begin.
  useEffect(() => {
    if (subject && resumeChecked && phase === 'loading') setPhase('intro')
  }, [subject, resumeChecked, phase])

  // The caller usually learns its ceiling from an async fetch, so it arrives after the
  // initial state was seeded. Adopt it while the interview hasn't started — otherwise the
  // intro promises the platform default (8) for a round that only runs 4 questions.
  useEffect(() => {
    if (maxQProp && !interviewId) setMaxQuestions(maxQProp)
  }, [maxQProp, interviewId])

  // On mount, look for an interview this tab (or a previous one) left running server-side.
  useEffect(() => {
    const stored = recallInterview(endpoints.storageKey) ?? knownInterviewId
    if (!stored) { setResumeChecked(true); return }
    let cancelled = false
    setRestoring('Checking for an interview in progress…')
    api.get<InterviewState>(endpoints.resume(stored))
      .then(({ data }) => {
        if (cancelled) return
        if (data.status === 'complete') {
          // Already graded — show the verdict, don't re-run scoring, and stop tracking it.
          forgetInterview(endpoints.storageKey)
          setMaxQuestions(data.max_questions || maxQProp || MAX_Q)
          setEvalHistory(historyFromState(data))
          setFinalResult(finalFromState(data))
          setRestoredResult(true)
          setFinished(true)
          setPhase('complete')
          return
        }
        if (data.status === 'in_progress' && data.answered_count === 0) {
          // The start turn died before the agent asked anything: no answers, no pending question,
          // and no interrupt to resume from. There is nothing to save — drop it silently.
          forgetInterview(endpoints.storageKey)
          return
        }
        setResumeState(data)
        setPhase('resume')
      })
      // 404 / 403 / stale id — the interview is gone. Clear it and let the intro render as usual;
      // the learner never asked about this id, so there's nothing to alarm them with.
      .catch(() => { if (!cancelled) forgetInterview(endpoints.storageKey) })
      .finally(() => { if (!cancelled) { setRestoring(null); setResumeChecked(true) } })
    return () => { cancelled = true }
  }, [endpoints, maxQProp, knownInterviewId])

  const currentQuestion = questions[currentQIdx]
  const questionText = currentQuestion?.text ?? ''
  const isCoding = !!currentQuestion?.is_coding_question
  const codingLang = currentQuestion?.language ?? 'python'

  // Begin the interview: open the start SSE and stream the agent's first question.
  const startInterviewStream = async () => {
    setQuestions([]); setCurrentQIdx(0); setEvalHistory([]); setFinished(false); setCurrentEval(null)
    setRecovery(null); setFinalResult(null); setRestoredResult(false)
    setPhase('question')  // shows a "preparing question" state until the first question arrives
    let gotQuestion = false
    let startedId: string | null = null
    try {
      await streamSSE(
        endpoints.start,
        {},
        (event) => {
          if (event.type === 'interview_started') {
            startedId = String(event.interview_id)
            setInterviewId(startedId)
            // Persist immediately: from here on a reload can find its way back.
            rememberInterview(endpoints.storageKey, startedId)
            if (event.max_questions) setMaxQuestions(Number(event.max_questions))
          } else if (event.type === 'question') {
            gotQuestion = true
            if (event.max_questions) setMaxQuestions(Number(event.max_questions))
            setQuestions([toQuestion(event)]); setCurrentQIdx(0)
          }
          else if (event.type === 'finished') setFinished(true)
          else if (event.type === 'error') toast.error(String(event.message ?? 'Could not start the interview — try again'))
        },
      )
      if (!gotQuestion) throw new Error('no question')
    } catch {
      if (startedId) {
        // The interview exists server-side but never produced a question — retry, don't strand it.
        setRecovery({ message: 'The interviewer never sent your first question. Nothing is lost — try again.', action: 'restart' })
        setPhase('error')
      } else {
        toast.error('Could not start the interview — try again')
        setPhase('intro')
      }
    }
  }

  /** Discard whatever is stored and put the learner back on the intro, ready to start fresh. */
  const startOver = () => {
    window.speechSynthesis?.cancel()
    forgetInterview(endpoints.storageKey)
    setResumeState(null); setInterviewId(null); setFinalResult(null); setRestoredResult(false)
    setQuestions([]); setCurrentQIdx(0); setEvalHistory([]); setCurrentEval(null); setFinished(false)
    setMaxQuestions(maxQProp ?? MAX_Q); setRecovery(null)
    updateTranscript(''); setInterimTranscript(''); setCodeValue('')
    setPhase('intro')
  }

  // Typewriter for question text
  useEffect(() => {
    if (!questionText) return
    if (phase !== 'question') { setDisplayedQ(questionText); return }
    let i = 0
    setDisplayedQ('')
    const id = setInterval(() => { i++; setDisplayedQ(questionText.slice(0, i)); if (i >= questionText.length) clearInterval(id) }, 20)
    return () => clearInterval(id)
  }, [questionText, phase])

  // Reset code editor when question changes
  useEffect(() => { setCodeValue('') }, [currentQIdx])

  // Auto-speak question (verbal only)
  useEffect(() => {
    if (phase !== 'question' || !questionText || isCoding) return
    const t = setTimeout(() => {
      setIsSpeaking(true)
      const utt = new SpeechSynthesisUtterance(`Question ${currentQIdx + 1}. ${questionText}`)
      utt.rate = 0.92
      const v = window.speechSynthesis?.getVoices().find((v) => v.lang.startsWith('en') && v.localService)
      if (v) utt.voice = v
      utt.onend = () => setIsSpeaking(false)
      utt.onerror = () => setIsSpeaking(false)
      window.speechSynthesis?.cancel()
      window.speechSynthesis?.speak(utt)
    }, 400)
    return () => { clearTimeout(t); window.speechSynthesis?.cancel(); setIsSpeaking(false) }
  }, [currentQIdx, questionText, phase, isCoding])

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

    const SR = getSpeechRecognitionCtor()
    if (SR) {
      const rec = new SR()
      rec.continuous = true; rec.interimResults = true; rec.lang = 'en-US'
      rec.onresult = (e) => {
        let fin = '', int = ''
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const res = e.results[i]
          const alt = res?.[0]
          if (!res || !alt) continue
          if (res.isFinal) fin += alt.transcript + ' '
          else int += alt.transcript
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
    if (!interviewId || !currentQuestion) return
    const qid = currentQuestion.id
    const coding = isCoding
    let gotEval = false
    setTurnStreaming(true)
    try {
      // One turn: the answer is scored (evaluation event), then the agent resumes and streams the
      // NEXT question (appended) or a `finished` event — all before the stream resolves at [DONE].
      await streamSSE(
        endpoints.answer(interviewId),
        { question_id: qid, answer_text: answerText },
        (event) => {
          if (event.type === 'evaluation') {
            gotEval = true
            if (event.max_questions) setMaxQuestions(Number(event.max_questions))
            const result: AnswerResult = {
              question_id: Number(event.question_id ?? qid),
              score: Number(event.score ?? 0),
              feedback: String(event.feedback ?? ''),
              answer_text: answerText,
              key_points_covered: (event.key_points_covered as string[]) ?? [],
            }
            setCurrentEval(result)
            setEvalHistory((prev) => [...prev, result])
            setPhase('feedback')
            if (!coding) {
              const utt = new SpeechSynthesisUtterance(`Score: ${result.score} out of 10. ${result.feedback}`)
              utt.rate = 0.92
              window.speechSynthesis?.cancel()
              window.speechSynthesis?.speak(utt)
            }
          } else if (event.type === 'question') {
            if (event.max_questions) setMaxQuestions(Number(event.max_questions))
            setQuestions((prev) => [...prev, toQuestion(event)])
          } else if (event.type === 'finished') {
            setFinished(true)
          } else if (event.type === 'error') {
            toast.error(String(event.message ?? 'Could not score that answer — your answer was saved, try again'))
          }
        },
      )
      if (!gotEval) throw new Error('no evaluation')
    } catch {
      if (gotEval) {
        // Scored, but the turn died before the next question arrived. The feedback on screen is
        // real; the Next button will re-sync with the server.
        toast('Connection dropped after scoring — your answer was saved', { icon: 'ℹ️' })
      } else {
        // We don't know whether the server scored it. Don't guess and don't discard the
        // interview — read the authoritative state back and carry on from there.
        setRecovery({ message: 'We lost the connection while your answer was being scored. Your interview is saved on our side.', action: 'resync' })
        setPhase('error')
      }
    } finally {
      setTurnStreaming(false)
    }
  }

  /**
   * Pull the authoritative interview state from the server and put the UI back on it.
   * Used both by the resume offer and by mid-interview error recovery.
   */
  const applyServerState = (s: InterviewState) => {
    setInterviewId(s.interview_id)
    setMaxQuestions(s.max_questions || maxQProp || MAX_Q)
    setResumeState(null); setRecovery(null); setCurrentEval(null)
    setInterimTranscript('')
    // Reconnecting onto the very question the learner was answering? Keep their draft.
    if (!(s.status === 'awaiting_answer' && s.current_question?.id === currentQuestion?.id)) {
      updateTranscript(''); setCodeValue('')
    }
    const history = historyFromState(s)
    const asked = askedFromState(s)
    setEvalHistory(history)

    if (s.status === 'complete') {
      forgetInterview(endpoints.storageKey)
      setQuestions(asked); setCurrentQIdx(Math.max(asked.length - 1, 0)); setFinished(true)
      setFinalResult(finalFromState(s)); setRestoredResult(true); setPhase('complete')
      return
    }
    if (s.status === 'awaiting_answer' && s.current_question) {
      setQuestions([...asked, s.current_question])
      setCurrentQIdx(asked.length)
      setFinished(false)
      setPhase('question')
      return
    }
    // `awaiting_final` (the agent concluded) and `in_progress` with answers already banked both
    // end the same way: there is no question left to ask and no interrupt to resume, so the only
    // way to honour the work already done is to send it for final scoring.
    setQuestions(asked); setCurrentQIdx(Math.max(asked.length - 1, 0)); setFinished(true)
    if (history.length > 0) {
      void handleComplete(s.interview_id)
    } else {
      forgetInterview(endpoints.storageKey)
      setPhase('intro')
    }
  }

  /** Retry after a mid-interview failure — keeps the session instead of reloading the page. */
  const retryRecovery = async () => {
    const action = recovery?.action
    setRecovery(null)
    if (action === 'complete') { void handleComplete(); return }
    if (action === 'restart') { forgetInterview(endpoints.storageKey); setInterviewId(null); void startInterviewStream(); return }
    if (!interviewId) { startOver(); return }
    setPhase('loading'); setRestoring('Reconnecting to your interview…')
    try {
      const { data } = await api.get<InterviewState>(endpoints.resume(interviewId))
      applyServerState(data)
    } catch {
      setRecovery({ message: "We still can't reach your interview. It's safe on our side — try again in a moment.", action: 'resync' })
      setPhase('error')
    } finally {
      setRestoring(null)
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

  // The agent tells us when it's done (finished) or hands us a next question to advance to.
  // While the turn is still streaming, the next question may yet arrive, so "no question after
  // this one" is not yet knowable — treating it as the end there would end an 8-question
  // interview at question 1.
  const nextReady = currentQIdx + 1 < questions.length
  const awaitingNext = !finished && !nextReady && turnStreaming
  const isLastQuestion = finished || (!nextReady && !turnStreaming)

  const handleNext = () => {
    window.speechSynthesis?.cancel()
    setCurrentEval(null)
    updateTranscript('')
    if (!isLastQuestion) {
      setCurrentQIdx((i) => i + 1)
      setPhase('question')
    } else {
      handleComplete()
    }
  }

  // `idOverride` lets a resume kick off scoring before the interviewId state has settled.
  const handleComplete = async (idOverride?: string) => {
    const id = idOverride ?? interviewId
    if (!id) return
    setPhase('scoring')
    setRecovery(null)
    resetScoring()
    window.speechSynthesis?.cancel()
    let scored: FinalResult | null = null
    try {
      await streamSSE(
        endpoints.complete(id),
        {},
        (event) => {
          if (event.type === 'step') {
            applyScoringStep(event as unknown as { id: string; label: string; status: 'active' | 'done' | 'error' })
          } else if (event.type === 'action' && event.kind === 'interview_scored') {
            scored = event.payload as FinalResult
          } else if (event.type === 'error') {
            toast.error(String(event.message ?? 'Could not finish scoring — try again'))
          }
        },
      )
      if (!scored) throw new Error('no result')
      const r = scored as FinalResult
      // Graded and banked — there is nothing left to resume.
      forgetInterview(endpoints.storageKey)
      setRestoredResult(false)
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
      // Scoring is replayable — the answers are all stored server-side.
      setRecovery({ message: 'Scoring didn’t finish. Every answer is saved — run it again.', action: 'complete' })
      setPhase('error')
    }
  }

  // ── Progress ─────────────────────────────────────────────────────────────────
  // The agent picks questions adaptively, so the total is unknown until it concludes — what the
  // learner gets is their position and the ceiling ("Question 3 · up to 6").
  const questionNo = Math.min(currentQIdx + 1, maxQuestions)
  const progressLabel = `Question ${questionNo} · up to ${maxQuestions}`
  const headerLabel = phase === 'intro' ? 'Intro'
    : phase === 'resume' ? 'Paused'
    : phase === 'error' ? 'Paused'
    : progressLabel
  const headerProgress = phase === 'intro' ? 0
    : finished || phase === 'complete' ? 100
    : phase === 'resume' ? Math.min(((resumeState?.answered_count ?? 0) / maxQuestions) * 100, 96)
    : Math.min((evalHistory.length / maxQuestions) * 100 + 8, 96)

  // ── Layouts ──────────────────────────────────────────────────────────────────

  if (phase === 'loading') {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 12 }}>
        <div style={{ width: 40, height: 40, borderRadius: '50%', border: '3px solid var(--line-2)', borderTopColor: 'var(--ink-0)', animation: 'spin 0.8s linear infinite' }} />
        <span className="t-sm fg-3" role="status">{restoring ?? 'Starting interview…'}</span>
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
          <h2 className="display" style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.03em', marginBottom: 8 }}>Computing your score</h2>
          <p className="t-sm fg-2" style={{ marginBottom: 24 }}>AI is cross-checking all answers against module knowledge…</p>
          <div style={{ display: 'inline-flex', justifyContent: 'flex-start', textAlign: 'left', width: '100%' }}>
            <ReasoningStream
              segments={scoringSteps.map((s) => ({ id: s.id, text: s.label, status: s.status }))}
              style={{ width: '100%' }}
            />
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
            <h2 className="display" style={{ fontSize: 28, fontWeight: 600, letterSpacing: '-0.03em', marginBottom: 16 }}>Interview complete</h2>
            <ScoreRing score={finalResult.final_score} />
            <div style={{ margin: '14px 0 0' }}>
              <Badge tone={finalResult.passed ? 'pos' : 'neg'} size="sm">
                {finalResult.passed ? 'Passed ✓' : 'Not Passed — Review & Retry'}
              </Badge>
            </div>
            {/* A score means nothing without the mark it was judged against — and for a job
                loop that mark moves with the role's seniority, so always show it. */}
            {bar != null && (
              <p className="t-xs fg-3" style={{ marginTop: 8 }}>
                Graded against a bar of {bar.toFixed(1)}/10 for this role.
              </p>
            )}
            {restoredResult && (
              <p className="t-xs fg-3" style={{ marginTop: 10 }}>
                Restored from your previous session — this interview was already graded.
              </p>
            )}
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
            <Button variant="secondary" size="lg" full style={{ minHeight: 44 }} onClick={() => navigate(endpoints.backHref)}>{endpoints.backLabel}</Button>
            {!finalResult.passed && (
              // Was a full page reload, which threw the SPA away to get back to the intro.
              <Button variant="primary" size="lg" full style={{ minHeight: 44 }} onClick={startOver}>Retry</Button>
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
            onClick={() => { window.speechSynthesis?.cancel(); navigate(endpoints.backHref) }}
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

          <span
            className="t-xs fg-3 mono"
            style={{ flexShrink: 0, whiteSpace: 'nowrap' }}
            role="status"
            aria-live="polite"
            aria-label={phase === 'intro' || phase === 'resume' || phase === 'error'
              ? headerLabel
              : `Question ${questionNo} of up to ${maxQuestions}`}
          >
            {headerLabel}
          </span>
        </div>
      </div>

      {/* ── Body ──────────────────────────────────────────────────────────────── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '24px 16px 32px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <div style={{ width: '100%', maxWidth: 640, display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* ── Resume offer ──────────────────────────────────────────────── */}
          {/* An interview is still open server-side. Offering it (rather than silently resuming,
              or silently starting over) keeps a fresh interview one click away. */}
          {phase === 'resume' && resumeState && (
            <div style={{ ...S.card, ...S.fadeIn }}>
              <div style={{ textAlign: 'center', marginBottom: 20 }}>
                <div style={{ width: 52, height: 52, borderRadius: '50%', background: 'var(--paper-2)', display: 'grid', placeItems: 'center', margin: '0 auto 16px' }}>
                  <Icon name="refresh" size={22} style={{ color: 'var(--accent)' }} />
                </div>
                <h2 className="display" style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.03em', marginBottom: 6 }}>
                  Pick up where you left off?
                </h2>
                <p className="t-sm fg-2">
                  You have an unfinished interview on <strong>{resumeState.module_title || currentModule?.title}</strong>.
                </p>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 22 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderRadius: 8, background: 'var(--paper-2)' }}>
                  <Icon name="check" size={15} style={{ color: 'var(--accent)', flexShrink: 0 }} />
                  <span className="t-xs fg-2" style={{ flex: 1, lineHeight: 1.5 }}>
                    {resumeState.answered_count} of up to {resumeState.max_questions} questions answered and scored.
                  </span>
                </div>
                {formatStarted(resumeState.created_at) && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderRadius: 8, background: 'var(--paper-2)' }}>
                    <Icon name="clock" size={15} style={{ color: 'var(--accent)', flexShrink: 0 }} />
                    <span className="t-xs fg-2" style={{ flex: 1, lineHeight: 1.5 }}>Started {formatStarted(resumeState.created_at)}</span>
                  </div>
                )}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderRadius: 8, background: 'var(--paper-2)' }}>
                  <Icon name="sparkle" size={15} style={{ color: 'var(--accent)', flexShrink: 0 }} />
                  <span className="t-xs fg-2" style={{ flex: 1, lineHeight: 1.5 }}>
                    {resumeState.status === 'awaiting_answer'
                      ? 'The interviewer is waiting on your next answer.'
                      : resumeState.status === 'awaiting_final'
                        ? 'The interviewer is done asking — only the final score is left.'
                        : 'The interviewer stopped between questions, so we can score the answers you gave.'}
                  </span>
                </div>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <Button
                  variant="primary" size="lg" full iconRight="arrow" style={{ minHeight: 44 }}
                  onClick={() => applyServerState(resumeState)}
                >
                  {resumeState.status === 'awaiting_answer'
                    ? 'Resume interview'
                    : resumeState.status === 'awaiting_final'
                      ? 'Finish & get my score'
                      : 'Score my answers so far'}
                </Button>
                <Button variant="secondary" size="lg" full style={{ minHeight: 44 }} onClick={startOver}>
                  Discard it and start a new interview
                </Button>
              </div>
            </div>
          )}

          {/* ── Recovery ──────────────────────────────────────────────────── */}
          {/* Something failed mid-interview. Server state survives, so retry means "re-sync and
              carry on", never "throw the session away and reload". */}
          {phase === 'error' && recovery && (
            <div style={{ ...S.card, ...S.fadeIn }}>
              <div style={{ textAlign: 'center', marginBottom: 20 }}>
                <div style={{ width: 52, height: 52, borderRadius: '50%', background: 'var(--paper-2)', display: 'grid', placeItems: 'center', margin: '0 auto 16px' }}>
                  <Icon name="alert" size={22} style={{ color: 'var(--warn)' }} />
                </div>
                <h2 className="display" style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.03em', marginBottom: 6 }}>
                  Interview interrupted
                </h2>
                <p className="t-sm fg-2" role="alert">{recovery.message}</p>
                {evalHistory.length > 0 && (
                  <p className="t-xs fg-3" style={{ marginTop: 6 }}>
                    {evalHistory.length} answer{evalHistory.length === 1 ? '' : 's'} already scored and kept.
                  </p>
                )}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <Button variant="primary" size="lg" full iconRight="arrow" style={{ minHeight: 44 }} onClick={() => { void retryRecovery() }}>
                  {recovery.action === 'complete' ? 'Score my answers' : recovery.action === 'restart' ? 'Try again' : 'Reconnect and continue'}
                </Button>
                <Button variant="secondary" size="lg" full style={{ minHeight: 44 }} onClick={startOver}>
                  Discard it and start a new interview
                </Button>
              </div>
            </div>
          )}

          {/* ── Intro ─────────────────────────────────────────────────────── */}
          {phase === 'intro' && (
            <div style={{ ...S.card, ...S.fadeIn }}>
              <div style={{ textAlign: 'center', marginBottom: 24 }}>
                <div style={{ width: 52, height: 52, borderRadius: '50%', background: 'var(--ink-0)', color: 'var(--paper-0)', display: 'grid', placeItems: 'center', margin: '0 auto 16px' }}>
                  <Icon name="mic" size={22} />
                </div>
                <h2 className="display" style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.03em', marginBottom: 6 }}>Ready to be assessed?</h2>
                <p className="t-sm fg-2">An adaptive interview on <strong>{currentModule?.title}</strong></p>
                {currentModule?.blurb && <p className="t-xs fg-3" style={{ marginTop: 2 }}>{currentModule.blurb}</p>}
                {/* The bar moves with the role's seniority for a job loop, so never state a
                    threshold the caller hasn't given us. */}
                <p className="t-xs fg-3" style={{ marginTop: 4 }}>
                  Pass threshold: {(bar ?? DEFAULT_BAR).toFixed(1)} / 10 per question average
                </p>
              </div>

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, justifyContent: 'center', marginBottom: 22 }}>
                {currentModule?.topics.map((t) => <Badge key={t} tone="outline" size="xs">{t}</Badge>)}
              </div>

              {/* How it works — the interviewer is a live agent that adapts to each answer */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 24 }}>
                {[
                  { icon: 'sparkle', text: 'An AI interviewer asks one question at a time, adapting to your answers.' },
                  { icon: 'mic', text: 'Answer by voice or by typing — coding questions open a live editor.' },
                  { icon: 'check', text: `Up to ${maxQuestions} questions; each is scored, then you get a final assessment.` },
                ].map((row) => (
                  <div key={row.text} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderRadius: 8, background: 'var(--paper-2)' }}>
                    <Icon name={row.icon} size={15} style={{ color: 'var(--accent)', flexShrink: 0 }} />
                    <span className="t-xs fg-2" style={{ flex: 1, lineHeight: 1.5 }}>{row.text}</span>
                  </div>
                ))}
              </div>

              <Button variant="primary" full iconRight="arrow" onClick={startInterviewStream}>
                Start Interview
              </Button>
            </div>
          )}

          {/* ── Preparing next question (agent thinking) ─────────────────── */}
          {(phase === 'question' || phase === 'recording') && !currentQuestion && (
            <div style={{ ...S.card, ...S.fadeIn, textAlign: 'center' }}>
              <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
                <div style={{ width: 44, height: 44, borderRadius: '50%', background: 'var(--paper-2)', display: 'grid', placeItems: 'center' }}>
                  <Icon name="sparkle" size={20} style={{ color: 'var(--accent)', animation: 'pulse-soft 1.2s ease-in-out infinite' }} />
                </div>
              </div>
              <p className="t-md fg-0" style={{ marginBottom: 6, fontWeight: 500 }}>The interviewer is preparing your question…</p>
              <p className="t-sm fg-3">Reading your profile and the module topics.</p>
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
                    runCodeUrl={endpoints.runCode(interviewId!)}
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
                <span className="t-sm fg-2" style={{ fontWeight: 500 }}>Question {questionNo} result</span>
                <Badge tone={scoreTone(currentEval.score)} size="sm">
                  {currentEval.score != null ? `${currentEval.score}/10` : 'Not graded'}
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

              <Button variant="primary" full iconRight="arrow" onClick={handleNext} disabled={awaitingNext}>
                {awaitingNext
                  ? 'Preparing next question…'
                  : isLastQuestion ? 'Submit for Final Scoring' : 'Next Question'}
              </Button>
            </div>
          )}

        </div>
      </div>

      {/* ── Footer: step dots ─────────────────────────────────────────────────── */}
      {interviewId && currentQuestion && !['intro', 'loading', 'resume', 'error', 'scoring', 'complete'].includes(phase) && (
        <div
          style={{ flexShrink: 0, padding: '10px 18px', borderTop: '1px solid var(--line-1)', background: 'var(--paper-1)', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10 }}
          aria-hidden="true"  /* the header counter carries this for screen readers */
        >
          <StepDots total={Math.max(questions.length, currentQIdx + 1, maxQuestions)} current={currentQIdx} evals={evalHistory} />
          <span className="t-xs fg-3 mono">{questionNo}/{maxQuestions}</span>
        </div>
      )}
    </div>
  )
}

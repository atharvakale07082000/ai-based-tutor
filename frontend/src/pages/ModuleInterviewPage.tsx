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
  scoring_matrix: Array<{ question_id: number; score: number; justification: string; concepts_covered: string[]; concepts_missed: string[] }>
  summary: string
  total_questions: number
}

function ScoreRing({ score, outOf = 10 }: { score: number; outOf?: number }) {
  const pct = (score / outOf) * 100
  const r = 54
  const circ = 2 * Math.PI * r
  const color = pct >= 70 ? 'var(--pos)' : pct >= 50 ? 'var(--warn)' : 'var(--neg)'

  return (
    <div style={{ position: 'relative', width: 144, height: 144, margin: '0 auto' }}>
      <svg width="144" height="144" style={{ transform: 'rotate(-90deg)' }} viewBox="0 0 130 130">
        <circle cx="65" cy="65" r={r} fill="none" stroke="var(--paper-3)" strokeWidth="10" />
        <circle
          cx="65" cy="65" r={r} fill="none"
          stroke={color} strokeWidth="10" strokeLinecap="round"
          strokeDasharray={circ}
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

function useTTS() {
  const speak = useCallback((text: string) => {
    if (!window.speechSynthesis) return
    window.speechSynthesis.cancel()
    const utt = new SpeechSynthesisUtterance(text)
    utt.rate = 0.95
    const voices = window.speechSynthesis.getVoices()
    const preferred = voices.find((v) => v.lang.startsWith('en') && v.localService)
    if (preferred) utt.voice = preferred
    window.speechSynthesis.speak(utt)
  }, [])
  const stop = useCallback(() => { window.speechSynthesis?.cancel() }, [])
  return { speak, stop }
}

const panelStyle: React.CSSProperties = {
  background: 'var(--paper-1)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', padding: 28, width: '100%', maxWidth: 560,
}

export default function ModuleInterviewPage() {
  const { planId, moduleId } = useParams<{ planId: string; moduleId: string }>()
  const navigate = useNavigate()
  const { speak, stop } = useTTS()

  const [interview, setInterview] = useState<Interview | null>(null)
  const [phase, setPhase] = useState<Phase>('loading')
  const [currentQIdx, setCurrentQIdx] = useState(0)
  const [isRecording, setIsRecording] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [interimTranscript, setInterimTranscript] = useState('')
  const [currentEval, setCurrentEval] = useState<AnswerResult | null>(null)
  const [finalResult, setFinalResult] = useState<FinalResult | null>(null)
  const [isSpeaking, setIsSpeaking] = useState(false)

  const mediaRef = useRef<MediaRecorder | null>(null)
  const recognitionRef = useRef<any>(null)
  const transcriptRef = useRef('')

  const updateTranscript = useCallback((updater: string | ((prev: string) => string)) => {
    setTranscript((prev) => {
      const next = typeof updater === 'function' ? updater(prev) : updater
      transcriptRef.current = next
      return next
    })
  }, [])

  const { data: plan } = useQuery({
    queryKey: ['course', planId],
    queryFn: () => coursesAPI.get(planId!).then((r) => r.data),
    enabled: !!planId,
  })

  const module = plan?.modules.find((m) => m.id === moduleId)

  useEffect(() => {
    if (!planId || !moduleId) return
    coursesAPI.startInterview(planId, moduleId)
      .then((r) => { setInterview(r.data); setPhase('intro') })
      .catch(() => { toast.error('Could not start interview'); navigate(`/courses/${planId}`) })
  }, [planId, moduleId])

  const currentQuestion = interview?.questions[currentQIdx]

  const speakQuestion = useCallback(() => {
    if (!currentQuestion) return
    setIsSpeaking(true)
    const utt = new SpeechSynthesisUtterance(`Question ${currentQIdx + 1}. ${currentQuestion.text}`)
    utt.rate = 0.95
    const voices = window.speechSynthesis?.getVoices() ?? []
    const preferred = voices.find((v) => v.lang.startsWith('en') && v.localService)
    if (preferred) utt.voice = preferred
    utt.onend = () => setIsSpeaking(false)
    window.speechSynthesis?.cancel()
    window.speechSynthesis?.speak(utt)
  }, [currentQuestion, currentQIdx])

  const startRecording = async () => {
    updateTranscript('')
    setInterimTranscript('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream)
      recorder.onstop = () => stream.getTracks().forEach((t) => t.stop())
      recorder.start()
      mediaRef.current = recorder
    } catch { /* proceed without MediaRecorder */ }

    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (SR) {
      const recognition = new SR()
      recognition.continuous = true
      recognition.interimResults = true
      recognition.lang = 'en-US'
      recognition.onresult = (event: any) => {
        let finalText = ''
        let interimText = ''
        for (let i = event.resultIndex; i < event.results.length; i++) {
          if (event.results[i].isFinal) finalText += event.results[i][0].transcript + ' '
          else interimText += event.results[i][0].transcript
        }
        if (finalText) updateTranscript((prev) => prev + finalText)
        setInterimTranscript(interimText)
      }
      recognition.onerror = () => {}
      recognition.start()
      recognitionRef.current = recognition
      toast.success('Listening…', { duration: 1500 })
    } else {
      toast('Speech recognition not supported — type your answer below', { icon: 'ℹ️' })
    }
    setIsRecording(true)
  }

  const stopRecording = () => {
    mediaRef.current?.stop()
    recognitionRef.current?.stop()
    recognitionRef.current = null
    setInterimTranscript('')
    setIsRecording(false)
    setPhase('evaluating')
    setTimeout(() => evaluateCurrentAnswer(transcriptRef.current || '[No answer recorded]'), 350)
  }

  const evaluateCurrentAnswer = async (answerText: string) => {
    if (!interview || !currentQuestion) return
    setPhase('evaluating')
    try {
      const { data } = await coursesAPI.submitAnswer(planId!, moduleId!, interview.interview_id, currentQuestion.id, answerText)
      setCurrentEval(data as AnswerResult)
      setPhase('feedback')
      speak(`Score: ${(data as AnswerResult).score} out of 10. ${(data as AnswerResult).feedback}`)
    } catch {
      toast.error('Evaluation failed')
      setPhase('question')
    }
  }

  const handleNext = () => {
    stop()
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
      speak(r.passed
        ? `Congratulations! You scored ${r.final_score.toFixed(1)} out of 10 and passed this module.`
        : `You scored ${r.final_score.toFixed(1)} out of 10. Review the module and try again.`)
    } catch {
      toast.error('Could not finalize interview')
      setPhase('feedback')
    }
  }

  if (phase === 'loading') {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ textAlign: 'center' }}>
          <Icon name="mic" size={28} style={{ color: 'var(--ink-2)', marginBottom: 12, animation: 'pulse-soft 2s ease-in-out infinite' }} />
          <div className="t-sm fg-3">Preparing your interview…</div>
        </div>
      </div>
    )
  }

  if (phase === 'scoring') {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        <div style={{ ...panelStyle, textAlign: 'center' }}>
          <Icon name="sparkle" size={28} style={{ color: 'var(--accent)', marginBottom: 12, animation: 'pulse-soft 2s ease-in-out infinite' }} />
          <h2 className="serif" style={{ fontSize: 22, fontWeight: 400, marginBottom: 8 }}>Scoring Agent Running</h2>
          <p className="t-sm fg-2" style={{ marginBottom: 20 }}>Analyzing your answers and computing the final score…</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {['Analyzing answers', 'Building scoring matrix', 'Computing final score'].map((step, i) => (
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

  if (phase === 'complete' && finalResult) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        <div style={{ ...panelStyle, maxWidth: 520 }}>
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

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '24px 16px', background: 'var(--paper-0)' }}>
      {/* Header */}
      <div style={{ textAlign: 'center', marginBottom: 20 }}>
        {module && <Badge tone="outline" size="xs" style={{ marginBottom: 6 }}>{module.title}</Badge>}
        <h1 className="serif" style={{ fontSize: 26, fontWeight: 400, margin: 0 }}>AI Interview</h1>
        {interview && (
          <div className="t-sm fg-3" style={{ marginTop: 4 }}>{currentQIdx + 1} / {interview.questions.length} questions</div>
        )}
      </div>

      {/* Intro */}
      {phase === 'intro' && (
        <div style={panelStyle}>
          <div style={{ textAlign: 'center', marginBottom: 20 }}>
            <Icon name="mic" size={32} style={{ color: 'var(--ink-2)', marginBottom: 10 }} />
            <h2 className="serif" style={{ fontSize: 20, fontWeight: 400, marginBottom: 8 }}>Ready to be assessed?</h2>
            <p className="t-sm fg-2" style={{ marginBottom: 4 }}>{interview?.questions.length} questions about <strong>{module?.title}</strong></p>
            <p className="t-xs fg-3" style={{ marginBottom: 16 }}>Answer verbally or type your answers. Pass threshold: 6 / 10.</p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, justifyContent: 'center', marginBottom: 20 }}>
              {module?.topics.map((t) => <Badge key={t} tone="outline" size="xs">{t}</Badge>)}
            </div>
            <Button variant="primary" full iconRight="arrow" onClick={() => { setPhase('question'); speakQuestion() }}>Start Interview</Button>
          </div>
        </div>
      )}

      {/* Question + Recording */}
      {(phase === 'question' || phase === 'recording') && currentQuestion && (
        <div style={panelStyle}>
          <div className="t-xs fg-3" style={{ marginBottom: 8 }}>Question {currentQIdx + 1} · {currentQuestion.expected_depth}</div>
          <h2 className="serif" style={{ fontSize: 20, fontWeight: 400, marginBottom: 16, lineHeight: 1.4 }}>{currentQuestion.text}</h2>

          <button
            onClick={speakQuestion}
            disabled={isSpeaking}
            style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'none', border: 0, cursor: 'pointer', padding: 0, marginBottom: 16 }}
          >
            <Icon name={isSpeaking ? 'mic' : 'mic'} size={12} style={{ color: 'var(--ink-3)' }} />
            <span className="t-xs fg-3">{isSpeaking ? 'Speaking…' : 'Listen again'}</span>
          </button>

          <div style={{ position: 'relative', marginBottom: 12 }}>
            <textarea
              value={transcript + (isRecording && interimTranscript ? interimTranscript : '')}
              onChange={(e) => !isRecording && updateTranscript(e.target.value)}
              placeholder={isRecording ? 'Listening… speak your answer' : 'Type your answer, or use the microphone below…'}
              readOnly={isRecording}
              style={{
                width: '100%', background: 'var(--paper-2)', border: '1px solid var(--line-1)',
                borderRadius: 'var(--r-2)', padding: '10px 12px', fontSize: 13,
                color: 'var(--ink-0)', fontFamily: 'inherit', outline: 'none', resize: 'none', height: 120, boxSizing: 'border-box',
              }}
            />
            {isRecording && (
              <div style={{ position: 'absolute', top: 10, right: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--neg)', animation: 'pulse-soft 1s ease-in-out infinite' }} />
                <span className="t-xs" style={{ color: 'var(--neg)' }}>Live</span>
              </div>
            )}
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            {!isRecording ? (
              <Button variant="secondary" icon="mic" full onClick={startRecording}>Record Answer</Button>
            ) : (
              <button
                onClick={stopRecording}
                style={{
                  flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                  padding: '8px 14px', borderRadius: 'var(--r-2)', border: '1px solid var(--neg)',
                  background: 'color-mix(in srgb, var(--neg) 10%, var(--paper-1))', color: 'var(--neg)',
                  fontSize: 13, cursor: 'pointer', fontFamily: 'inherit',
                }}
              >
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--neg)', animation: 'pulse-soft 1s ease-in-out infinite' }} />
                Stop Recording
              </button>
            )}
            {!isRecording && transcript.trim() && (
              <Button variant="primary" full onClick={() => evaluateCurrentAnswer(transcript)}>Submit</Button>
            )}
          </div>
        </div>
      )}

      {/* Evaluating */}
      {phase === 'evaluating' && (
        <div style={{ ...panelStyle, textAlign: 'center' }}>
          <Icon name="sparkle" size={24} style={{ color: 'var(--accent)', marginBottom: 10, animation: 'pulse-soft 2s ease-in-out infinite' }} />
          <p className="t-md fg-1">Evaluating your answer…</p>
          <div style={{ display: 'flex', justifyContent: 'center', gap: 4, marginTop: 10 }}>
            {[0, 1, 2].map((i) => (
              <span key={i} style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--accent)', animation: `blink 1.2s ease-in-out ${i * 0.2}s infinite` }} />
            ))}
          </div>
        </div>
      )}

      {/* Per-question feedback */}
      {phase === 'feedback' && currentEval && (
        <div style={panelStyle}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
            <span className="t-sm fg-2">Q{currentQIdx + 1} result</span>
            <Badge tone={currentEval.score >= 7 ? 'pos' : currentEval.score >= 5 ? 'warn' : 'neg'} size="sm">{currentEval.score}/10</Badge>
          </div>

          <div style={{ background: 'var(--paper-2)', borderRadius: 'var(--r-2)', padding: '10px 14px', marginBottom: 10 }}>
            <div className="t-xs fg-3" style={{ marginBottom: 4 }}>Your answer (transcribed)</div>
            <div className="t-sm fg-2" style={{ fontStyle: 'italic' }}>"{currentEval.answer_text}"</div>
          </div>

          <div style={{ background: 'color-mix(in srgb, var(--accent) 8%, var(--paper-1))', border: '1px solid color-mix(in srgb, var(--accent) 20%, transparent)', borderRadius: 'var(--r-2)', padding: '10px 14px', marginBottom: 14 }}>
            <div className="t-xs" style={{ color: 'var(--accent)', marginBottom: 4 }}>Quick feedback</div>
            <div className="t-sm fg-1">{currentEval.feedback}</div>
            {currentEval.key_points_covered?.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 8 }}>
                {currentEval.key_points_covered.map((kp) => <Badge key={kp} tone="pos" size="xs">{kp}</Badge>)}
              </div>
            )}
          </div>

          <Button variant="primary" full iconRight="arrow" onClick={handleNext}>
            {currentQIdx < (interview?.questions.length ?? 0) - 1 ? 'Next Question' : 'Submit for Final Scoring'}
          </Button>
        </div>
      )}

      {/* Progress dots */}
      {interview && !['intro', 'complete', 'scoring', 'loading'].includes(phase) && (
        <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginTop: 20 }}>
          {interview.questions.map((_, i) => (
            <div key={i} style={{
              width: i === currentQIdx ? 10 : 7,
              height: i === currentQIdx ? 10 : 7,
              borderRadius: '50%',
              background: i < currentQIdx ? 'var(--pos)' : i === currentQIdx ? 'var(--ink-0)' : 'var(--paper-3)',
              transition: 'all var(--dur-base)',
            }} />
          ))}
        </div>
      )}
    </div>
  )
}

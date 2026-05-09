import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { PageWrapper } from '@/components/layout/PageWrapper'
import { coursesAPI, type Interview } from '@/lib/api'

type InterviewPhase =
  | 'loading'
  | 'intro'
  | 'question'
  | 'recording'
  | 'evaluating'
  | 'feedback'
  | 'scoring'
  | 'complete'

interface AnswerResult {
  question_id: number
  score: number
  feedback: string
  answer_text: string
  key_points_covered: string[]
}

interface ScoringMatrixEntry {
  question_id: number
  score: number
  justification: string
  concepts_covered: string[]
  concepts_missed: string[]
}

interface FinalResult {
  final_score: number    // 0-10
  passed: boolean
  scoring_matrix: ScoringMatrixEntry[]
  summary: string
  total_questions: number
}

function ScoreRing({ score, outOf = 10 }: { score: number; outOf?: number }) {
  const pct = Math.round((score / outOf) * 100)
  const r = 54
  const circ = 2 * Math.PI * r
  const color = pct >= 70 ? '#10B981' : pct >= 50 ? '#F59E0B' : '#F43F5E'

  return (
    <div className="relative w-36 h-36 mx-auto">
      <svg className="w-36 h-36" style={{ transform: 'rotate(-90deg)' }} viewBox="0 0 130 130">
        <circle cx="65" cy="65" r={r} fill="none" stroke="#1F2937" strokeWidth="10" />
        <motion.circle
          cx="65" cy="65" r={r} fill="none"
          stroke={color} strokeWidth="10" strokeLinecap="round"
          strokeDasharray={circ}
          initial={{ strokeDashoffset: circ }}
          animate={{ strokeDashoffset: circ - circ * (pct / 100) }}
          transition={{ duration: 1.4, ease: 'easeOut' }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-3xl font-bold text-paper">{score.toFixed(1)}</span>
        <span className="text-xs text-paper/40">/ {outOf}</span>
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
    utt.pitch = 1
    const voices = window.speechSynthesis.getVoices()
    const preferred = voices.find((v) => v.lang.startsWith('en') && v.localService)
    if (preferred) utt.voice = preferred
    window.speechSynthesis.speak(utt)
  }, [])

  const stop = useCallback(() => {
    window.speechSynthesis?.cancel()
  }, [])

  return { speak, stop }
}

export default function ModuleInterviewPage() {
  const { planId, moduleId } = useParams<{ planId: string; moduleId: string }>()
  const navigate = useNavigate()
  const { speak, stop } = useTTS()

  const [interview, setInterview] = useState<Interview | null>(null)
  const [phase, setPhase] = useState<InterviewPhase>('loading')
  const [currentQIdx, setCurrentQIdx] = useState(0)
  const [isRecording, setIsRecording] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [interimTranscript, setInterimTranscript] = useState('')
  const [answers, setAnswers] = useState<AnswerResult[]>([])
  const [currentEval, setCurrentEval] = useState<AnswerResult | null>(null)
  const [finalResult, setFinalResult] = useState<FinalResult | null>(null)
  const [isSpeaking, setIsSpeaking] = useState(false)

  const mediaRef = useRef<MediaRecorder | null>(null)
  const recognitionRef = useRef<any>(null)
  const transcriptRef = useRef('')  // mirrors transcript state for stale-closure-safe reads

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
      .then((r) => {
        setInterview(r.data)
        setPhase('intro')
      })
      .catch(() => {
        toast.error('Could not start interview')
        navigate(`/courses/${planId}`)
      })
  }, [planId, moduleId])

  const currentQuestion = interview?.questions[currentQIdx]

  const speakQuestion = useCallback(() => {
    if (!currentQuestion) return
    setIsSpeaking(true)
    const utt = new SpeechSynthesisUtterance(
      `Question ${currentQIdx + 1}. ${currentQuestion.text}`
    )
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

    // Microphone audio capture
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream)
      recorder.ondataavailable = () => {}
      recorder.onstop = () => stream.getTracks().forEach((t) => t.stop())
      recorder.start()
      mediaRef.current = recorder
    } catch {
      // Proceed without MediaRecorder; STT still works
    }

    // Real-time STT via Web Speech API
    const SpeechRecognitionAPI =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (SpeechRecognitionAPI) {
      const recognition = new SpeechRecognitionAPI()
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

    // Small delay to let final STT result settle into transcriptRef
    setTimeout(() => {
      evaluateCurrentAnswer(transcriptRef.current || '[No answer recorded]')
    }, 350)
  }

  const evaluateCurrentAnswer = async (answerText: string) => {
    if (!interview || !currentQuestion) return
    setPhase('evaluating')
    try {
      const { data } = await coursesAPI.submitAnswer(
        planId!,
        moduleId!,
        interview.interview_id,
        currentQuestion.id,
        answerText,
      )
      const result = data as AnswerResult
      setCurrentEval(result)
      setAnswers((prev) => [...prev, result])
      setPhase('feedback')
      speak(`Score: ${result.score} out of 10. ${result.feedback}`)
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
      const { data } = await coursesAPI.completeInterview(
        planId!,
        moduleId!,
        interview.interview_id,
      )
      const result = data as FinalResult
      setFinalResult(result)
      setPhase('complete')
      speak(
        result.passed
          ? `Congratulations! You scored ${result.final_score.toFixed(1)} out of 10 and passed this module.`
          : `You scored ${result.final_score.toFixed(1)} out of 10. Review the module and try again.`
      )
    } catch {
      toast.error('Could not finalize interview')
      setPhase('feedback')
    }
  }

  // ─── Loading ───────────────────────────────────────────────────────────────

  if (phase === 'loading') {
    return (
      <PageWrapper>
        <div className="min-h-[60vh] flex items-center justify-center">
          <div className="text-center space-y-4">
            <div className="text-4xl animate-pulse">🎙️</div>
            <p className="text-paper/50 text-sm">Preparing your interview…</p>
          </div>
        </div>
      </PageWrapper>
    )
  }

  // ─── Scoring (agent is running) ────────────────────────────────────────────

  if (phase === 'scoring') {
    return (
      <PageWrapper>
        <div className="min-h-[60vh] flex items-center justify-center">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="glass-strong rounded-3xl p-10 max-w-sm w-full text-center"
          >
            <div className="text-4xl mb-4">🧠</div>
            <h2 className="font-display text-xl text-paper mb-3">Scoring Agent Running</h2>
            <p className="text-sm text-paper/50 mb-6">
              Analyzing your answers, cross-checking knowledge, building scoring matrix…
            </p>
            <div className="space-y-2 text-left">
              {['Analyzing answers', 'Building scoring matrix', 'Computing final score'].map((step, i) => (
                <div key={step} className="flex items-center gap-3 text-sm text-paper/60">
                  <span
                    className="w-2 h-2 rounded-full bg-violet shrink-0"
                    style={{ animation: `blink 1.4s ease-in-out ${i * 0.35}s infinite` }}
                  />
                  {step}
                </div>
              ))}
            </div>
          </motion.div>
        </div>
      </PageWrapper>
    )
  }

  // ─── Complete ──────────────────────────────────────────────────────────────

  if (phase === 'complete' && finalResult) {
    return (
      <PageWrapper>
        <div className="min-h-screen flex items-center justify-center px-4 py-12">
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            className="glass-strong rounded-3xl p-8 max-w-lg w-full"
          >
            <h2 className="font-display text-2xl text-paper mb-6 text-center">Interview Complete</h2>

            <ScoreRing score={finalResult.final_score} />

            <div className="mt-5 mb-4 text-center">
              {finalResult.passed ? (
                <Badge variant="emerald" className="text-sm px-4 py-2">Module Passed 🎉</Badge>
              ) : (
                <Badge variant="rose" className="text-sm px-4 py-2">Not Passed — Review & Retry</Badge>
              )}
            </div>

            {/* AI summary */}
            {finalResult.summary && (
              <div className="bg-violet/10 border border-violet/20 rounded-xl p-4 mb-5 text-sm text-paper/80 leading-relaxed">
                <p className="text-xs text-paper/40 mb-1.5">AI Assessment</p>
                {finalResult.summary}
              </div>
            )}

            {/* Scoring matrix */}
            {finalResult.scoring_matrix?.length > 0 && (
              <div className="space-y-3 mb-6">
                <p className="text-xs text-paper/40 uppercase tracking-wider">Scoring Matrix</p>
                {finalResult.scoring_matrix.map((entry, i) => (
                  <div key={i} className="bg-surface-2 rounded-xl p-3">
                    <div className="flex justify-between items-center mb-1.5">
                      <span className="text-xs text-paper/60">Q{entry.question_id}</span>
                      <Badge variant={entry.score >= 7 ? 'emerald' : entry.score >= 5 ? 'amber' : 'rose'}>
                        {entry.score}/10
                      </Badge>
                    </div>
                    <p className="text-xs text-paper/60 mb-2">{entry.justification}</p>
                    {entry.concepts_covered?.length > 0 && (
                      <div className="flex flex-wrap gap-1 mb-1">
                        {entry.concepts_covered.map((c) => (
                          <span key={c} className="text-xs px-1.5 py-0.5 rounded-full bg-emerald/10 border border-emerald/20 text-emerald">{c}</span>
                        ))}
                      </div>
                    )}
                    {entry.concepts_missed?.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {entry.concepts_missed.map((c) => (
                          <span key={c} className="text-xs px-1.5 py-0.5 rounded-full bg-rose/10 border border-rose/20 text-rose">{c}</span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            <div className="flex gap-3">
              <Button variant="secondary" className="flex-1" onClick={() => navigate(`/courses/${planId}`)}>
                Back to Plan
              </Button>
              {!finalResult.passed && (
                <Button className="flex-1" onClick={() => window.location.reload()}>
                  Retry Interview
                </Button>
              )}
            </div>
          </motion.div>
        </div>
      </PageWrapper>
    )
  }

  // ─── Main interview flow ───────────────────────────────────────────────────

  return (
    <PageWrapper>
      <div className="min-h-screen flex flex-col items-center justify-center px-4 py-8">
        <div className="w-full max-w-xl">
          {/* Header */}
          <div className="mb-6 text-center">
            <Badge variant="violet" className="mb-2">{module?.title ?? 'Module'}</Badge>
            <h1 className="font-display text-2xl text-paper">AI Interview</h1>
            {interview && (
              <p className="text-sm text-paper/40 mt-1">
                {currentQIdx + 1} / {interview.questions.length} questions
              </p>
            )}
          </div>

          <AnimatePresence mode="wait">
            {/* Intro */}
            {phase === 'intro' && (
              <motion.div
                key="intro"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                className="glass-strong rounded-3xl p-8 text-center"
              >
                <div className="text-5xl mb-4">🎙️</div>
                <h2 className="font-display text-xl text-paper mb-3">Ready to be assessed?</h2>
                <p className="text-sm text-paper/60 mb-2">
                  {interview?.questions.length} questions about{' '}
                  <strong className="text-paper">{module?.title}</strong>
                </p>
                <p className="text-xs text-paper/40 mb-6">
                  Questions read aloud via TTS. Answer verbally (live transcription) or type your answer.
                  A LangGraph scoring agent evaluates all answers at the end. Pass threshold: 6 / 10.
                </p>
                <div className="flex flex-wrap gap-2 justify-center mb-6">
                  {module?.topics.map((t) => (
                    <span key={t} className="text-xs px-2.5 py-1 rounded-full bg-surface-2 border border-surface-3 text-paper/50">{t}</span>
                  ))}
                </div>
                <Button onClick={() => { setPhase('question'); speakQuestion() }} className="w-full">
                  Start Interview →
                </Button>
              </motion.div>
            )}

            {/* Question + Recording */}
            {(phase === 'question' || phase === 'recording') && currentQuestion && (
              <motion.div
                key={`question-${currentQIdx}`}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                className="glass-strong rounded-3xl p-8"
              >
                <div className="mb-6">
                  <p className="text-xs text-paper/40 uppercase tracking-wider mb-2">
                    Question {currentQIdx + 1} · {currentQuestion.expected_depth}
                  </p>
                  <h2 className="font-display text-xl text-paper leading-relaxed">{currentQuestion.text}</h2>
                </div>

                <button
                  onClick={speakQuestion}
                  disabled={isSpeaking}
                  className="flex items-center gap-2 text-sm text-violet-light hover:text-paper mb-5 transition-colors"
                >
                  <span>{isSpeaking ? '🔊' : '🔈'}</span>
                  {isSpeaking ? 'Speaking…' : 'Listen again'}
                </button>

                {/* Live transcription area */}
                <div className="relative mb-4">
                  <textarea
                    value={transcript + (isRecording && interimTranscript ? interimTranscript : '')}
                    onChange={(e) => !isRecording && updateTranscript(e.target.value)}
                    placeholder={isRecording ? 'Listening… speak your answer' : 'Type your answer, or use the microphone below…'}
                    className="w-full bg-surface-2 border border-surface-3 rounded-xl px-4 py-3 text-sm text-paper placeholder-paper/30 focus:outline-none focus:ring-2 focus:ring-violet/50 resize-none h-32"
                    readOnly={isRecording}
                  />
                  {isRecording && (
                    <div className="absolute top-2.5 right-3 flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-rose animate-ping" />
                      <span className="text-xs text-rose">Live</span>
                    </div>
                  )}
                </div>

                {/* Controls */}
                <div className="flex gap-3">
                  {!isRecording ? (
                    <Button variant="secondary" onClick={startRecording} className="flex-1" leftIcon={<span>🎙️</span>}>
                      Record Answer
                    </Button>
                  ) : (
                    <button
                      onClick={stopRecording}
                      className="flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-rose/20 border border-rose text-rose text-sm font-medium"
                    >
                      <span className="w-2 h-2 rounded-full bg-rose animate-ping" />
                      Stop Recording
                    </button>
                  )}
                  {!isRecording && transcript.trim() && (
                    <Button onClick={() => evaluateCurrentAnswer(transcript)} className="flex-1">
                      Submit →
                    </Button>
                  )}
                </div>
              </motion.div>
            )}

            {/* Evaluating per-question */}
            {phase === 'evaluating' && (
              <motion.div
                key="evaluating"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="glass-strong rounded-3xl p-8 text-center"
              >
                <div className="text-4xl mb-4 animate-bounce">🧠</div>
                <p className="text-paper/70 text-sm">Evaluating your answer…</p>
                <div className="flex justify-center gap-1.5 mt-4">
                  {[0, 1, 2].map((i) => (
                    <span key={i} className="w-2 h-2 rounded-full bg-violet"
                      style={{ animation: `blink 1.2s ease-in-out ${i * 0.2}s infinite` }} />
                  ))}
                </div>
              </motion.div>
            )}

            {/* Per-question feedback */}
            {phase === 'feedback' && currentEval && (
              <motion.div
                key="feedback"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                className="glass-strong rounded-3xl p-8"
              >
                <div className="flex items-center justify-between mb-4">
                  <p className="text-sm text-paper/60">Q{currentQIdx + 1} result</p>
                  <Badge variant={currentEval.score >= 7 ? 'emerald' : currentEval.score >= 5 ? 'amber' : 'rose'}>
                    {currentEval.score}/10
                  </Badge>
                </div>

                <div className="bg-surface-2 rounded-xl p-4 mb-4">
                  <p className="text-xs text-paper/40 mb-1">Your answer (transcribed)</p>
                  <p className="text-sm text-paper/70 italic">"{currentEval.answer_text}"</p>
                </div>

                <div className="bg-violet/10 border border-violet/20 rounded-xl p-4 mb-4">
                  <p className="text-xs text-paper/40 mb-1">Quick feedback</p>
                  <p className="text-sm text-paper">{currentEval.feedback}</p>
                  {currentEval.key_points_covered?.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {currentEval.key_points_covered.map((kp) => (
                        <span key={kp} className="text-xs px-2 py-0.5 rounded-full bg-emerald/10 border border-emerald/20 text-emerald">{kp}</span>
                      ))}
                    </div>
                  )}
                </div>

                <Button onClick={handleNext} className="w-full">
                  {currentQIdx < (interview?.questions.length ?? 0) - 1
                    ? 'Next Question →'
                    : 'Submit for Final Scoring →'}
                </Button>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Progress dots */}
          {interview && !['intro', 'complete', 'scoring', 'loading'].includes(phase) && (
            <div className="flex justify-center gap-2 mt-6">
              {interview.questions.map((_, i) => (
                <div
                  key={i}
                  className={`w-2 h-2 rounded-full transition-all ${
                    i < currentQIdx
                      ? 'bg-emerald'
                      : i === currentQIdx
                      ? 'bg-violet scale-125'
                      : 'bg-surface-3'
                  }`}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </PageWrapper>
  )
}

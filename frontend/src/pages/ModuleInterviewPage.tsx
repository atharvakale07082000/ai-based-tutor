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
  | 'complete'

interface AnswerResult {
  question_id: number
  score: number
  feedback: string
  answer_text: string
  key_points_covered: string[]
}

function ScoreRing({ score }: { score: number }) {
  const pct = score
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
        <span className="text-3xl font-bold text-paper">{pct}%</span>
        <span className="text-xs text-paper/40">Score</span>
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
  const [answers, setAnswers] = useState<AnswerResult[]>([])
  const [currentEval, setCurrentEval] = useState<AnswerResult | null>(null)
  const [finalResult, setFinalResult] = useState<{ final_score: number; passed: boolean } | null>(null)
  const [isSpeaking, setIsSpeaking] = useState(false)

  const mediaRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])

  // Load plan info to show module title
  const { data: plan } = useQuery({
    queryKey: ['course', planId],
    queryFn: () => coursesAPI.get(planId!).then((r) => r.data),
    enabled: !!planId,
  })

  const module = plan?.modules.find((m) => m.id === moduleId)

  // Start interview on mount
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
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream)
      chunksRef.current = []
      recorder.ondataavailable = (e) => chunksRef.current.push(e.data)
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop())
        await processAudio()
      }
      recorder.start()
      mediaRef.current = recorder
      setIsRecording(true)
      setTranscript('')
    } catch {
      toast.error('Microphone access denied')
    }
  }

  const stopRecording = () => {
    mediaRef.current?.stop()
    setIsRecording(false)
    setPhase('evaluating')
  }

  const processAudio = async () => {
    if (!interview || !currentQuestion) return

    // Use Web Speech API for transcription (fallback: typed answer)
    // If browser STT isn't available we skip and use typed text
    await evaluateCurrentAnswer(transcript || '[No answer provided]')
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
    setTranscript('')
    if (currentQIdx < (interview?.questions.length ?? 0) - 1) {
      setCurrentQIdx((i) => i + 1)
      setPhase('question')
    } else {
      handleComplete()
    }
  }

  const handleComplete = async () => {
    if (!interview) return
    setPhase('evaluating')
    try {
      const { data } = await coursesAPI.completeInterview(
        planId!,
        moduleId!,
        interview.interview_id,
      )
      setFinalResult(data as { final_score: number; passed: boolean })
      setPhase('complete')
      const passed = (data as { passed: boolean }).passed
      speak(passed
        ? 'Congratulations! You have passed this module. Well done!'
        : 'You did not pass this time. Review the module and try again.'
      )
    } catch {
      toast.error('Could not finalize interview')
    }
  }

  const handleStartInterview = () => {
    setPhase('question')
    speakQuestion()
  }

  // ─── Render ───────────────────────────────────────────────────────────────

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

  if (phase === 'complete' && finalResult) {
    const scorePercent = Math.round(finalResult.final_score * 100)
    return (
      <PageWrapper>
        <div className="min-h-screen flex items-center justify-center px-4">
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            className="glass-strong rounded-3xl p-8 max-w-md w-full text-center"
          >
            <h2 className="font-display text-2xl text-paper mb-6">Interview Complete</h2>
            <ScoreRing score={scorePercent} />

            <div className="mt-6 mb-6">
              {finalResult.passed ? (
                <Badge variant="emerald" className="text-base px-4 py-2">Module Passed 🎉</Badge>
              ) : (
                <Badge variant="rose" className="text-base px-4 py-2">Not Passed — Review & Retry</Badge>
              )}
            </div>

            <div className="space-y-3 mb-6 text-left">
              <p className="text-xs text-paper/40 uppercase tracking-wider">Per-question breakdown</p>
              {answers.map((a, i) => (
                <div key={i} className="bg-surface-2 rounded-xl p-3">
                  <div className="flex justify-between items-center mb-1">
                    <span className="text-xs text-paper/60">Q{i + 1}</span>
                    <Badge variant={a.score >= 7 ? 'emerald' : a.score >= 5 ? 'amber' : 'rose'}>
                      {a.score}/10
                    </Badge>
                  </div>
                  <p className="text-xs text-paper/50">{a.feedback}</p>
                </div>
              ))}
            </div>

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
                  {interview?.questions.length} questions about <strong className="text-paper">{module?.title}</strong>
                </p>
                <p className="text-xs text-paper/40 mb-6">
                  Questions will be read aloud. Answer verbally using the record button, or type your answer.
                  You need 60% or higher to pass this module.
                </p>
                <div className="flex flex-wrap gap-2 justify-center mb-6">
                  {module?.topics.map((t) => (
                    <span key={t} className="text-xs px-2.5 py-1 rounded-full bg-surface-2 border border-surface-3 text-paper/50">{t}</span>
                  ))}
                </div>
                <Button onClick={handleStartInterview} className="w-full">
                  Start Interview →
                </Button>
              </motion.div>
            )}

            {/* Question */}
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

                {/* Listen button */}
                <button
                  onClick={speakQuestion}
                  disabled={isSpeaking}
                  className="flex items-center gap-2 text-sm text-violet-light hover:text-paper mb-6 transition-colors"
                >
                  <span>{isSpeaking ? '🔊' : '🔈'}</span>
                  {isSpeaking ? 'Speaking…' : 'Listen again'}
                </button>

                {/* Typed answer fallback */}
                <textarea
                  value={transcript}
                  onChange={(e) => setTranscript(e.target.value)}
                  placeholder="Type your answer here, or use the microphone below…"
                  className="w-full bg-surface-2 border border-surface-3 rounded-xl px-4 py-3 text-sm text-paper placeholder-paper/30 focus:outline-none focus:ring-2 focus:ring-violet/50 resize-none h-28 mb-4"
                  disabled={isRecording}
                />

                {/* Record button */}
                <div className="flex gap-3">
                  {!isRecording ? (
                    <Button variant="secondary" onClick={startRecording} className="flex-1" leftIcon={<span>🎙️</span>}>
                      Record Answer
                    </Button>
                  ) : (
                    <button
                      onClick={stopRecording}
                      className="flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-rose/20 border border-rose text-rose text-sm font-medium animate-pulse"
                    >
                      <span className="w-2 h-2 rounded-full bg-rose animate-ping" />
                      Stop Recording
                    </button>
                  )}
                  {!isRecording && transcript.trim() && (
                    <Button onClick={() => evaluateCurrentAnswer(transcript)} className="flex-1">
                      Submit Answer →
                    </Button>
                  )}
                </div>
              </motion.div>
            )}

            {/* Evaluating */}
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

            {/* Feedback */}
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
                  <p className="text-xs text-paper/40 mb-1">Your answer</p>
                  <p className="text-sm text-paper/70">{currentEval.answer_text}</p>
                </div>

                <div className="bg-violet/10 border border-violet/20 rounded-xl p-4 mb-4">
                  <p className="text-xs text-paper/40 mb-1">AI Feedback</p>
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
                    : 'See Final Results →'}
                </Button>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Progress dots */}
          {interview && phase !== 'intro' && phase !== 'complete' && (
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

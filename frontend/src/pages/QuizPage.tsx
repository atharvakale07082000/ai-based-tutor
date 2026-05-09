import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { quizAPI } from '@/lib/api'
import { runTextGeneration, runSentiment } from '@/lib/hf'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Skeleton } from '@/components/ui/Skeleton'
import { useLearnerStore } from '@/stores/learnerStore'
import toast from 'react-hot-toast'

const QUESTION_TIME = 60 // seconds

export default function QuizPage() {
  const { quizId } = useParams<{ quizId: string }>()
  const navigate = useNavigate()
  const [currentIdx, setCurrentIdx] = useState(0)
  const [answers, setAnswers] = useState<number[]>([])
  const [selectedOption, setSelectedOption] = useState<number | null>(null)
  const [revealed, setRevealed] = useState(false)
  const [timeLeft, setTimeLeft] = useState(QUESTION_TIME)
  const [isFlipping, setIsFlipping] = useState(false)
  const [explanation, setExplanation] = useState('')
  const [explanationLoading, setExplanationLoading] = useState(false)
  const [quizDone, setQuizDone] = useState(false)
  const [result, setResult] = useState<{ score: number; weak_topics: string[] } | null>(null)
  const [reflection, setReflection] = useState('')
  const [reflectionMood, setReflectionMood] = useState<string | null>(null)
  const updateProficiency = useLearnerStore((s) => s.updateProficiency)
  const addQuizSession = useLearnerStore((s) => s.addQuizSession)

  const { data: quiz, isLoading } = useQuery({
    queryKey: ['quiz', quizId],
    queryFn: () => quizAPI.get(quizId!).then((r) => r.data),
    enabled: !!quizId && quizId !== 'new',
  })

  const currentQuestion = quiz?.questions[currentIdx]

  // Timer
  useEffect(() => {
    if (quizDone || revealed) return
    const interval = setInterval(() => {
      setTimeLeft((t) => {
        if (t <= 1) {
          clearInterval(interval)
          if (selectedOption === null) handleReveal(-1)
          return 0
        }
        return t - 1
      })
    }, 1000)
    return () => clearInterval(interval)
  }, [currentIdx, quizDone, revealed])

  // Reset timer on question change
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

  const handleNext = () => {
    setIsFlipping(true)
    setTimeout(() => {
      setIsFlipping(false)
      if (quiz && currentIdx < quiz.questions.length - 1) {
        setCurrentIdx((i) => i + 1)
      } else {
        handleFinish()
      }
    }, 300)
  }

  const handleFinish = async () => {
    if (!quiz) return
    try {
      const { data } = await quizAPI.submit(quiz.quiz_id, answers)
      setResult(data)
      setQuizDone(true)
      updateProficiency(quiz.topic, data.elo_update.new_elo)
      addQuizSession({
        id: quiz.quiz_id,
        topic: quiz.topic,
        score: data.score,
        bloom_level: quiz.bloom_level,
        completed_at: new Date().toISOString(),
      })
    } catch {
      toast.error('Could not submit quiz results')
    }
  }

  const handleGetExplanation = async () => {
    if (!currentQuestion) return
    setExplanationLoading(true)
    try {
      const prompt = `Explain why the correct answer to this question is "${currentQuestion.options[currentQuestion.correct_index]}". Question: ${currentQuestion.question}`
      const text = await runTextGeneration('QUIZ_GENERATOR', prompt, { max_new_tokens: 150 })
      setExplanation(text)
    } catch {
      toast.error('Could not generate explanation')
    } finally {
      setExplanationLoading(false)
    }
  }

  const handleReflectionSubmit = async () => {
    if (!reflection.trim()) return
    try {
      const sentiment = await runSentiment(reflection)
      setReflectionMood(sentiment[0]?.label ?? 'NEUTRAL')
      toast.success('Mood saved to Progress Tracker')
    } catch { /* non-critical */ }
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-ink flex items-center justify-center">
        <div className="text-center space-y-4">
          <div className="text-4xl animate-spin">⚙️</div>
          <Skeleton className="h-4 w-48 mx-auto" />
          <Skeleton className="h-4 w-32 mx-auto" />
        </div>
      </div>
    )
  }

  if (!quiz) {
    return (
      <div className="min-h-screen bg-ink flex flex-col items-center justify-center gap-4 text-paper/50">
        <span className="text-4xl">📝</span>
        <p className="text-lg">Quiz not found</p>
        <button
          onClick={() => navigate('/dashboard')}
          className="px-4 py-2 rounded-xl bg-violet/20 text-violet-light text-sm hover:bg-violet/30 transition-colors"
        >
          ← Back to Dashboard
        </button>
      </div>
    )
  }

  // Results screen
  if (quizDone && result) {
    const scorePercent = Math.round(result.score * 100)
    const scoreColor = scorePercent >= 80 ? '#10B981' : scorePercent >= 60 ? '#F59E0B' : '#F43F5E'
    const r = 54
    const circ = 2 * Math.PI * r

    return (
      <div className="min-h-screen bg-ink flex items-center justify-center px-4">
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          className="glass-strong rounded-3xl p-8 max-w-md w-full text-center"
        >
          <h2 className="font-display text-3xl text-paper mb-6">Quiz Complete!</h2>

          {/* Score ring */}
          <div className="flex justify-center mb-6">
            <div className="relative w-36 h-36">
              <svg className="w-36 h-36" style={{ transform: 'rotate(-90deg)', transformOrigin: '50% 50%' }} viewBox="0 0 130 130">
                <circle cx="65" cy="65" r={r} fill="none" stroke="#1F2937" strokeWidth="10" />
                <motion.circle
                  cx="65" cy="65" r={r} fill="none"
                  stroke={scoreColor} strokeWidth="10" strokeLinecap="round"
                  strokeDasharray={circ}
                  initial={{ strokeDashoffset: circ }}
                  animate={{ strokeDashoffset: circ - circ * result.score }}
                  transition={{ duration: 1.2, ease: 'easeOut' }}
                />
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-3xl font-bold text-paper">{scorePercent}%</span>
                <span className="text-xs text-paper/40">Score</span>
              </div>
            </div>
          </div>

          {result.weak_topics.length > 0 && (
            <div className="mb-6 text-left">
              <p className="text-xs text-paper/50 mb-2 uppercase tracking-wider">Topics to revisit</p>
              <div className="flex flex-wrap gap-2">
                {result.weak_topics.map((t) => (
                  <Badge key={t} variant="rose" dot>{t}</Badge>
                ))}
              </div>
            </div>
          )}

          {/* Reflection */}
          <div className="mb-6 text-left">
            <p className="text-xs text-paper/50 mb-2 uppercase tracking-wider">How did you feel?</p>
            <textarea
              value={reflection}
              onChange={(e) => setReflection(e.target.value)}
              placeholder="Describe how the quiz felt…"
              className="w-full bg-surface-2 border border-surface-3 rounded-xl px-4 py-3 text-sm text-paper placeholder-paper/30 focus:outline-none focus:ring-2 focus:ring-violet/50 resize-none h-20"
            />
            {reflectionMood && (
              <Badge variant={reflectionMood === 'POSITIVE' ? 'emerald' : 'rose'} className="mt-2">
                Mood: {reflectionMood.toLowerCase()}
              </Badge>
            )}
            <Button size="sm" variant="ghost" className="mt-2" onClick={handleReflectionSubmit}>
              Save mood
            </Button>
          </div>

          <div className="flex gap-3 justify-center">
            <Button onClick={() => navigate('/doubts', { state: { topic: quiz.topic } })}>
              Ask Doubt-Solver
            </Button>
            <Button variant="secondary" onClick={() => navigate('/progress')}>
              View Progress
            </Button>
          </div>
        </motion.div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-ink/95 flex flex-col items-center justify-center px-4 py-8">
      {/* Header */}
      <div className="w-full max-w-xl mb-6">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Badge variant="violet">{quiz.topic}</Badge>
            <Badge variant="surface">{quiz.bloom_level}</Badge>
          </div>
          <span className="text-sm text-paper/50">
            {currentIdx + 1} / {quiz.questions.length}
          </span>
        </div>

        {/* Timer bar */}
        <div className="h-1.5 bg-surface-2 rounded-full overflow-hidden">
          <motion.div
            className="h-full rounded-full"
            style={{
              background: timeLeft > 20 ? '#10B981' : timeLeft > 10 ? '#F59E0B' : '#F43F5E',
            }}
            animate={{ width: `${(timeLeft / QUESTION_TIME) * 100}%` }}
            transition={{ duration: 1, ease: 'linear' }}
          />
        </div>
        <p className="text-right text-xs text-paper/30 mt-1">{timeLeft}s</p>
      </div>

      {/* Question card with flip */}
      <AnimatePresence mode="wait">
        <motion.div
          key={currentIdx}
          initial={{ rotateY: isFlipping ? 90 : 0, opacity: isFlipping ? 0 : 1 }}
          animate={{ rotateY: 0, opacity: 1 }}
          exit={{ rotateY: -90, opacity: 0 }}
          transition={{ duration: 0.3 }}
          className="w-full max-w-xl"
        >
          <div className="glass-strong rounded-3xl p-8">
            {currentQuestion && (
              <>
                <p className="text-xs text-paper/40 uppercase tracking-wider mb-3">
                  Question {currentIdx + 1}
                </p>
                <h2 className="font-display text-xl text-paper mb-6 leading-relaxed">
                  {currentQuestion.question}
                </h2>

                {/* Options */}
                <div className="space-y-3">
                  {currentQuestion.options.map((option, idx) => {
                    let optStyle = 'bg-surface-2 border-surface-3 text-paper/80 hover:border-violet/50'
                    if (revealed) {
                      if (idx === currentQuestion.correct_index) {
                        optStyle = 'bg-emerald/20 border-emerald text-emerald'
                      } else if (idx === selectedOption && idx !== currentQuestion.correct_index) {
                        optStyle = 'bg-rose/20 border-rose text-rose'
                      } else {
                        optStyle = 'bg-surface-2 border-surface-3 text-paper/40'
                      }
                    } else if (selectedOption === idx) {
                      optStyle = 'bg-violet/20 border-violet text-violet-light'
                    }

                    return (
                      <button
                        key={idx}
                        onClick={() => handleReveal(idx)}
                        disabled={revealed}
                        className={`w-full text-left px-4 py-3.5 rounded-xl border text-sm font-medium transition-all ${optStyle} disabled:cursor-default`}
                      >
                        <span className="text-paper/40 mr-3">{String.fromCharCode(65 + idx)}.</span>
                        {option}
                      </button>
                    )
                  })}
                </div>

                {/* Explanation */}
                {revealed && (
                  <motion.div
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="mt-4 space-y-3"
                  >
                    {currentQuestion.explanation && (
                      <div className="bg-surface-2 border border-surface-3 rounded-xl p-4 text-sm text-paper/70">
                        <p className="text-xs text-paper/40 mb-1">Explanation</p>
                        {currentQuestion.explanation}
                      </div>
                    )}

                    {!explanation && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={handleGetExplanation}
                        isLoading={explanationLoading}
                        leftIcon={<span>✨</span>}
                      >
                        Generate deeper explanation
                      </Button>
                    )}

                    {explanation && (
                      <div className="bg-violet/10 border border-violet/20 rounded-xl p-4 text-sm text-paper/80">
                        <div className="flex items-center gap-2 mb-2">
                            <span className="text-xs text-paper/40">AI explanation</span>
                        </div>
                        {explanation}
                      </div>
                    )}

                    <Button onClick={handleNext} className="w-full">
                      {currentIdx < quiz.questions.length - 1 ? 'Next Question →' : 'See Results →'}
                    </Button>
                  </motion.div>
                )}
              </>
            )}
          </div>
        </motion.div>
      </AnimatePresence>
    </div>
  )
}

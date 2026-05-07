import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import toast from 'react-hot-toast'
import { learnerAPI } from '@/lib/api'
import { useLearnerStore } from '@/stores/learnerStore'
import { runZeroShot } from '@/lib/hf'
import { Button } from '@/components/ui/Button'

const STEPS = ['Welcome', 'Learning Goals', 'Learning Style', 'Weekly Time', 'Your Curriculum']
const GOAL_OPTIONS = [
  'Python Programming', 'Machine Learning', 'Data Science', 'Web Development',
  'Deep Learning', 'NLP', 'Computer Vision', 'Statistics & Math', 'Software Engineering', 'Cloud & DevOps',
]
const STYLE_OPTIONS = [
  { value: 'visual', label: 'Visual', desc: 'Diagrams, videos, and charts', icon: '👁️' },
  { value: 'auditory', label: 'Auditory', desc: 'Lectures and verbal explanations', icon: '🎧' },
  { value: 'reading', label: 'Reading', desc: 'Text, articles, and documentation', icon: '📖' },
  { value: 'kinesthetic', label: 'Hands-on', desc: 'Projects, exercises, and coding', icon: '🛠️' },
] as const

const prefersReducedMotion =
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

const slideVariants = {
  enter: (direction: number) => ({
    x: prefersReducedMotion ? 0 : direction > 0 ? 60 : -60,
    opacity: 0,
  }),
  center: { x: 0, opacity: 1 },
  exit: (direction: number) => ({
    x: prefersReducedMotion ? 0 : direction > 0 ? -60 : 60,
    opacity: 0,
  }),
}

export default function OnboardingPage() {
  const [step, setStep] = useState(0)
  const [direction, setDirection] = useState(1)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [goals, setGoals] = useState<string[]>([])
  const [style, setStyle] = useState<typeof STYLE_OPTIONS[number]['value']>('visual')
  const [hoursPerWeek, setHoursPerWeek] = useState(5)
  const [suggestedTopics, setSuggestedTopics] = useState<string[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const navigate = useNavigate()
  const setLearner = useLearnerStore((s) => s.setLearner)

  const toggleGoal = (g: string) =>
    setGoals((prev) => (prev.includes(g) ? prev.filter((x) => x !== g) : [...prev, g]))

  const next = async () => {
    if (step === 3) {
      // Step 4 → classify goals using BART-MNLI
      setIsLoading(true)
      try {
        if (goals.length > 0) {
          const result = await runZeroShot(goals.join(', '), GOAL_OPTIONS, true)
          setSuggestedTopics(result.labels.slice(0, 4))
        } else {
          setSuggestedTopics(['Python Programming', 'Machine Learning', 'Data Science', 'Web Development'])
        }
      } catch {
        setSuggestedTopics(['Python Programming', 'Machine Learning', 'Data Science', 'Web Development'])
      } finally {
        setIsLoading(false)
      }
    }
    setDirection(1)
    setStep((s) => s + 1)
  }

  const back = () => {
    setDirection(-1)
    setStep((s) => s - 1)
  }

  const handleFinish = async () => {
    setIsLoading(true)
    try {
      const { data } = await learnerAPI.updateProfile({
        name,
        goal_vector: goals,
        learning_style: style,
        session_cadence: { hours_per_week: hoursPerWeek },
      })
      setLearner({
        id: data.id,
        name: data.name,
        goalVector: data.goal_vector,
        learningStyle: data.learning_style,
        topicProficiency: data.topic_proficiency_map,
      })
      toast.success('Learning profile created! Welcome to AI Tutor 🎉')
      navigate('/dashboard')
    } catch {
      toast.error('Could not save profile. Please try again.')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-ink flex flex-col items-center justify-center px-4 py-12">
      {/* Progress bar */}
      <div className="w-full max-w-lg mb-8">
        <div className="flex justify-between mb-2">
          {STEPS.map((s, i) => (
            <span key={s} className={`text-xs ${i <= step ? 'text-violet-light' : 'text-paper/30'}`}>
              {s}
            </span>
          ))}
        </div>
        <div className="h-1.5 bg-surface-2 rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-gradient-to-r from-violet to-indigo-light rounded-full"
            animate={{ width: `${((step + 1) / STEPS.length) * 100}%` }}
            transition={{ duration: 0.4 }}
          />
        </div>
      </div>

      {/* Step card */}
      <div className="w-full max-w-lg relative overflow-hidden">
        <AnimatePresence custom={direction} mode="wait">
          <motion.div
            key={step}
            custom={direction}
            variants={slideVariants}
            initial="enter"
            animate="center"
            exit="exit"
            transition={{ duration: 0.3, ease: 'easeInOut' }}
            className="glass-strong rounded-3xl p-8"
          >
            {/* Step 0: Welcome */}
            {step === 0 && (
              <div className="space-y-6">
                <h2 className="font-display text-3xl text-paper">Let's build your<br/>learning profile</h2>
                <p className="text-paper/60">Tell us a bit about yourself so our AI agents can personalize your experience from day one.</p>
                <div className="space-y-4">
                  <div>
                    <label className="block text-xs text-paper/50 mb-1.5">Full name</label>
                    <input
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="Alex Chen"
                      className="w-full bg-surface-2 border border-surface-3 rounded-xl px-4 py-3 text-sm text-paper placeholder-paper/30 focus:outline-none focus:ring-2 focus:ring-violet/50"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-paper/50 mb-1.5">Email address</label>
                    <input
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="alex@company.com"
                      className="w-full bg-surface-2 border border-surface-3 rounded-xl px-4 py-3 text-sm text-paper placeholder-paper/30 focus:outline-none focus:ring-2 focus:ring-violet/50"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Step 1: Learning goals */}
            {step === 1 && (
              <div className="space-y-6">
                <h2 className="font-display text-3xl text-paper">What do you want<br/>to master?</h2>
                <p className="text-paper/60">Select all that apply. Our Curriculum Planner agent will map your path.</p>
                <div className="flex flex-wrap gap-2">
                  {GOAL_OPTIONS.map((g) => (
                    <button
                      key={g}
                      onClick={() => toggleGoal(g)}
                      className={`px-3 py-2 rounded-xl text-sm font-medium border transition-all ${
                        goals.includes(g)
                          ? 'bg-violet/20 border-violet text-violet-light'
                          : 'bg-surface-2 border-surface-3 text-paper/60 hover:border-violet/50'
                      }`}
                    >
                      {g}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Step 2: Learning style */}
            {step === 2 && (
              <div className="space-y-6">
                <h2 className="font-display text-3xl text-paper">How do you learn<br/>best?</h2>
                <p className="text-paper/60">Our agents adapt content format to your preferred learning style.</p>
                <div className="grid grid-cols-2 gap-3">
                  {STYLE_OPTIONS.map((s) => (
                    <button
                      key={s.value}
                      onClick={() => setStyle(s.value)}
                      className={`p-4 rounded-2xl text-left border transition-all ${
                        style === s.value
                          ? 'bg-violet/20 border-violet'
                          : 'bg-surface-2 border-surface-3 hover:border-violet/50'
                      }`}
                    >
                      <div className="text-2xl mb-2">{s.icon}</div>
                      <div className="text-sm font-medium text-paper">{s.label}</div>
                      <div className="text-xs text-paper/50 mt-0.5">{s.desc}</div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Step 3: Weekly time */}
            {step === 3 && (
              <div className="space-y-6">
                <h2 className="font-display text-3xl text-paper">How much time<br/>can you commit?</h2>
                <p className="text-paper/60">Your Progress Tracker agent will pace your curriculum accordingly.</p>
                <div className="space-y-4">
                  <div className="flex justify-between items-center">
                    <span className="text-4xl font-display text-violet-light">{hoursPerWeek}</span>
                    <span className="text-paper/50">hours / week</span>
                  </div>
                  <input
                    type="range"
                    min={1}
                    max={20}
                    value={hoursPerWeek}
                    onChange={(e) => setHoursPerWeek(Number(e.target.value))}
                    className="w-full accent-violet h-2 rounded-full"
                  />
                  <div className="flex justify-between text-xs text-paper/30">
                    <span>1 hr</span>
                    <span>20 hrs</span>
                  </div>
                </div>
                <div className="bg-violet/10 border border-violet/20 rounded-xl p-4 text-sm text-paper/70">
                  At {hoursPerWeek} hrs/week, you can realistically complete{' '}
                  <strong className="text-violet-light">{Math.floor(hoursPerWeek * 0.8)} modules</strong> per week.
                </div>
              </div>
            )}

            {/* Step 4: Curriculum preview */}
            {step === 4 && (
              <div className="space-y-6">
                <h2 className="font-display text-3xl text-paper">Your personalized<br/>path is ready</h2>
                <p className="text-paper/60">
                  Based on your goals, the Curriculum Planner agent (powered by{' '}
                  <span className="text-orange-400">🤗 BART-MNLI</span>) suggests starting with:
                </p>
                <div className="space-y-2">
                  {isLoading ? (
                    Array.from({ length: 4 }).map((_, i) => (
                      <div key={i} className="h-12 bg-surface-2 rounded-xl animate-pulse" />
                    ))
                  ) : (
                    suggestedTopics.map((topic, i) => (
                      <div key={topic} className="flex items-center gap-3 bg-surface-2 border border-surface-3 rounded-xl px-4 py-3">
                        <span className="w-6 h-6 rounded-full bg-violet/20 text-violet-light text-xs flex items-center justify-center font-bold">
                          {i + 1}
                        </span>
                        <span className="text-sm text-paper">{topic}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}

            {/* Navigation */}
            <div className="flex justify-between mt-8">
              <Button variant="ghost" onClick={back} disabled={step === 0}>
                ← Back
              </Button>
              {step < STEPS.length - 1 ? (
                <Button onClick={next} isLoading={isLoading}>
                  Continue →
                </Button>
              ) : (
                <Button onClick={handleFinish} isLoading={isLoading}>
                  Start Learning 🚀
                </Button>
              )}
            </div>
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  )
}

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { PageWrapper } from '@/components/layout/PageWrapper'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { coursesAPI, type CoursePlan } from '@/lib/api'

const SUGGESTIONS = [
  'Machine Learning from scratch',
  'Full-stack web development with React and Node',
  'Data Science with Python and pandas',
  'Cloud architecture with AWS',
  'iOS development with Swift',
  'Blockchain and Web3 development',
]

function PlanCard({ plan }: { plan: CoursePlan }) {
  const navigate = useNavigate()
  const completed = plan.modules.filter((m) => m.interview_status === 'passed').length
  const pct = Math.round((completed / plan.modules.length) * 100)

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ y: -2 }}
      transition={{ duration: 0.2 }}
    >
      <Card hover className="cursor-pointer" onClick={() => navigate(`/courses/${plan.plan_id}`)}>
        <div className="flex items-start justify-between mb-3">
          <Badge variant="violet">{plan.modules.length} modules</Badge>
          <span className="text-xs text-paper/40">{plan.total_duration_weeks}w</span>
        </div>
        <h3 className="font-display text-lg text-paper mb-1 leading-tight">{plan.title}</h3>
        <p className="text-sm text-paper/50 mb-4 line-clamp-2">{plan.description}</p>

        <div className="space-y-1.5">
          <div className="flex justify-between text-xs text-paper/40">
            <span>{completed} / {plan.modules.length} modules completed</span>
            <span>{pct}%</span>
          </div>
          <div className="h-1.5 bg-surface-3 rounded-full overflow-hidden">
            <motion.div
              className="h-full bg-gradient-to-r from-violet to-indigo-light rounded-full"
              initial={{ width: 0 }}
              animate={{ width: `${pct}%` }}
              transition={{ duration: 0.8, ease: 'easeOut' }}
            />
          </div>
        </div>

        <p className="text-[10px] text-paper/30 mt-3 truncate">Goal: {plan.goal}</p>
      </Card>
    </motion.div>
  )
}

const PLANNING_STEPS = [
  { icon: '🔍', label: 'Searching the web for resources…' },
  { icon: '🧠', label: 'Analyzing learning paths…' },
  { icon: '📐', label: 'Structuring your curriculum…' },
  { icon: '💾', label: 'Saving your plan…' },
]

export default function CoursePlannerPage() {
  const navigate = useNavigate()
  const [goal, setGoal] = useState('')
  const [isPlanning, setIsPlanning] = useState(false)
  const [planStep, setPlanStep] = useState(0)

  const { data: plans, refetch } = useQuery({
    queryKey: ['courses'],
    queryFn: () => coursesAPI.list().then((r) => r.data),
  })

  const handlePlan = async () => {
    if (!goal.trim()) {
      toast.error('Tell me what you want to learn')
      return
    }
    setIsPlanning(true)
    setPlanStep(0)

    // Animate steps while waiting
    const stepInterval = setInterval(() => {
      setPlanStep((s) => Math.min(s + 1, PLANNING_STEPS.length - 1))
    }, 2500)

    try {
      const { data } = await coursesAPI.create(goal.trim())
      clearInterval(stepInterval)
      toast.success('Your learning plan is ready!')
      await refetch()
      navigate(`/courses/${data.plan_id}`)
    } catch {
      clearInterval(stepInterval)
      toast.error('Could not generate plan. Please try again.')
    } finally {
      setIsPlanning(false)
    }
  }

  return (
    <PageWrapper>
      <div className="px-6 py-8 max-w-[1100px] mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="font-display text-3xl text-paper">Course Planner</h1>
          <p className="text-paper/50 mt-1">Tell the AI what you want to master — it researches the web and builds a complete roadmap for you.</p>
        </div>

        {/* Input card */}
        <Card className="mb-10">
          <p className="text-sm font-medium text-paper/70 mb-3">What do you want to learn?</p>
          <div className="flex gap-3">
            <input
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !isPlanning && handlePlan()}
              placeholder="e.g. Machine learning from zero to production…"
              className="flex-1 bg-surface-2 border border-surface-3 rounded-xl px-4 py-3 text-sm text-paper placeholder-paper/30 focus:outline-none focus:ring-2 focus:ring-violet/50"
              disabled={isPlanning}
            />
            <Button onClick={handlePlan} isLoading={isPlanning} disabled={isPlanning}>
              Build Plan
            </Button>
          </div>

          {/* Suggestions */}
          <div className="flex flex-wrap gap-2 mt-3">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => setGoal(s)}
                className="text-xs px-3 py-1.5 rounded-full bg-surface-2 border border-surface-3 text-paper/50 hover:text-paper hover:border-violet/40 transition-all"
              >
                {s}
              </button>
            ))}
          </div>

          {/* Planning animation */}
          <AnimatePresence>
            {isPlanning && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                className="mt-5 overflow-hidden"
              >
                <div className="flex flex-col gap-2">
                  {PLANNING_STEPS.map((step, i) => (
                    <motion.div
                      key={i}
                      initial={{ opacity: 0.3 }}
                      animate={{ opacity: i <= planStep ? 1 : 0.3 }}
                      className={`flex items-center gap-3 text-sm transition-all ${i <= planStep ? 'text-paper' : 'text-paper/30'}`}
                    >
                      <span className="text-lg">{step.icon}</span>
                      <span>{step.label}</span>
                      {i === planStep && (
                        <span className="ml-auto flex gap-1">
                          {[0, 1, 2].map((d) => (
                            <span
                              key={d}
                              className="w-1 h-1 rounded-full bg-violet"
                              style={{ animation: `blink 1.2s ease-in-out ${d * 0.2}s infinite` }}
                            />
                          ))}
                        </span>
                      )}
                      {i < planStep && <span className="ml-auto text-emerald text-xs">✓</span>}
                    </motion.div>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </Card>

        {/* Existing plans */}
        {plans && plans.length > 0 && (
          <>
            <h2 className="text-sm font-medium text-paper/60 uppercase tracking-wider mb-4">Your Learning Plans</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {plans.map((plan) => (
                <PlanCard key={plan.plan_id} plan={plan} />
              ))}
            </div>
          </>
        )}

        {plans?.length === 0 && !isPlanning && (
          <div className="text-center py-16 text-paper/30">
            <span className="text-5xl block mb-3">🗺️</span>
            <p className="text-sm">No plans yet. Create your first learning roadmap above.</p>
          </div>
        )}
      </div>
    </PageWrapper>
  )
}

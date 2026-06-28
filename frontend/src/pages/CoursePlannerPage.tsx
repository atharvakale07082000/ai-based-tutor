import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Input } from '@/components/ui/Input'
import { EmptyState } from '@/components/ui/EmptyState'
import { AgentTimeline } from '@/components/ui/AgentTimeline'
import { useAgentTimeline } from '@/hooks/useAgentTimeline'
import { coursesAPI, streamSSE, type CoursePlan } from '@/lib/api'

const SUGGESTIONS = [
  'Machine Learning from scratch',
  'Data Science with Python',
  'Full-stack web development',
  'Deep Learning and neural nets',
  'SQL and database design',
  'Statistics for data science',
]

function PlanCard({ plan }: { plan: CoursePlan }) {
  const navigate = useNavigate()
  const passed = plan.modules.filter((m) => m.interview_status === 'passed').length
  const pct = plan.modules.length ? Math.round((passed / plan.modules.length) * 100) : 0

  return (
    <Card
      hover
      padding="md"
      style={{ cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: 10 }}
      onClick={() => navigate(`/courses/${plan.plan_id}`)}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <Badge tone="outline" size="xs">{plan.modules.length} modules</Badge>
        <Badge tone="neutral" size="xs">{plan.total_duration_weeks}w</Badge>
        {passed === plan.modules.length && plan.modules.length > 0 && (
          <Badge tone="pos" size="xs">Complete</Badge>
        )}
        <span style={{ flex: 1 }} />
        <span className="t-xs fg-3 mono">{pct}%</span>
      </div>
      <div className="t-lg fg-0" style={{ fontWeight: 500, lineHeight: 1.3 }}>{plan.title}</div>
      <div className="t-sm fg-2" style={{ flex: 1, lineHeight: 1.5 }}>{plan.description}</div>
      <div>
        <div style={{ height: 4, background: 'var(--paper-3)', borderRadius: 'var(--r-pill)', overflow: 'hidden' }}>
          <div style={{ width: `${pct}%`, height: '100%', background: 'var(--ink-0)', borderRadius: 'var(--r-pill)', transition: 'width 0.6s ease' }} />
        </div>
        <div className="t-xs fg-3" style={{ marginTop: 4 }}>{passed} / {plan.modules.length} modules passed</div>
      </div>
    </Card>
  )
}

export default function CoursePlannerPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const prefill = (location.state as { prefill?: string } | null)?.prefill ?? ''
  const [goal, setGoal] = useState(prefill)
  const [isPlanning, setIsPlanning] = useState(false)
  const { steps, applyStep, reset } = useAgentTimeline()

  const { data: plans, refetch, isError: plansError } = useQuery({
    queryKey: ['courses'],
    queryFn: () => coursesAPI.list().then((r) => r.data),
    staleTime: 1000 * 60 * 2,   // course plans: 2 min
    gcTime: 1000 * 60 * 10,
  })

  const handlePlan = async () => {
    if (!goal.trim()) { toast.error('Tell me what you want to learn'); return }
    setIsPlanning(true)
    reset()
    let createdPlanId: string | null = null
    try {
      await streamSSE('/courses/plan/stream', { goal: goal.trim() }, (event) => {
        if (event.type === 'step') {
          applyStep(event as unknown as { id: string; label: string; status: 'active' | 'done' | 'error' })
        } else if (event.type === 'action' && event.kind === 'plan_created') {
          createdPlanId = String((event.payload as { plan_id: string }).plan_id)
        } else if (event.type === 'error') {
          toast.error(String(event.message ?? 'Could not generate plan. Try again.'))
        }
      })
      if (createdPlanId) {
        toast.success('Your learning plan is ready!')
        await refetch()
        navigate(`/courses/${createdPlanId}`)
      } else {
        toast.error('Could not generate plan. Try again.')
      }
    } catch {
      toast.error('Could not generate plan. Try again.')
    } finally {
      setIsPlanning(false)
    }
  }

  return (
    <div style={{ padding: '24px 28px', maxWidth: 1240, margin: '0 auto' }}>
      <div style={{ marginBottom: 20 }}>
        <div className="caps fg-3">Learning Path Builder</div>
        <h1 className="serif" style={{ fontSize: 36, fontWeight: 400, margin: 0, letterSpacing: '-0.02em' }}>Course Planner</h1>
        <p className="t-md fg-2" style={{ marginTop: 6 }}>Describe what you want to master — the agent searches, structures, and builds a complete roadmap.</p>
      </div>

      {/* Goal input */}
      <Card padding="md" style={{ marginBottom: 20 }}>
        <div className="caps fg-2" style={{ marginBottom: 10 }}>What do you want to learn?</div>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <Input
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            onKeyDown={(e: React.KeyboardEvent) => e.key === 'Enter' && !isPlanning && handlePlan()}
            placeholder="e.g. Machine learning from zero to production…"
            disabled={isPlanning}
            inputSize="lg"
            style={{ flex: 1 }}
          />
          <Button variant="primary" icon="sparkle" onClick={handlePlan} loading={isPlanning}>Build Plan</Button>
        </div>

        {/* Suggestion chips */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => setGoal(s)}
              className="t-xs fg-2"
              style={{
                padding: '4px 10px', borderRadius: 'var(--r-pill)', cursor: 'pointer',
                background: 'var(--paper-2)', border: '1px solid var(--line-1)',
                fontFamily: 'inherit', transition: 'background var(--dur-fast)',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--paper-3)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--paper-2)')}
            >{s}</button>
          ))}
        </div>

        {/* Live planning progress (streamed from the agent) */}
        {isPlanning && steps.length > 0 && (
          <div style={{ marginTop: 16, padding: 14, background: 'var(--paper-2)', borderRadius: 'var(--r-2)' }}>
            <AgentTimeline steps={steps} className="fade-in" />
          </div>
        )}
      </Card>

      {/* Existing plans */}
      {plansError && (
        <div style={{ textAlign: 'center', padding: '32px 0' }}>
          <p className="t-sm fg-2" style={{ marginBottom: 8 }}>Could not load your plans.</p>
          <button onClick={() => refetch()} style={{ fontSize: 13, color: 'var(--accent)', background: 'none', border: 0, cursor: 'pointer', fontFamily: 'inherit' }}>Retry →</button>
        </div>
      )}

      {!plansError && plans && plans.length > 0 && (
        <>
          <div className="caps fg-2" style={{ marginBottom: 10 }}>Your learning plans · {plans.length}</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
            {plans.map((plan) => <PlanCard key={plan.plan_id} plan={plan} />)}
          </div>
        </>
      )}

      {plans?.length === 0 && !isPlanning && (
        <Card padding="none">
          <EmptyState
            icon="course"
            title="No paths yet"
            body="Describe a skill or role above and Atelier will research, structure, and build your complete learning roadmap."
          />
        </Card>
      )}
    </div>
  )
}

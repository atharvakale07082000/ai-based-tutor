import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Icon } from '@/components/ui/Icon'
import { EmptyState } from '@/components/ui/EmptyState'
import { coursesAPI, type CoursePlan, type CourseModule } from '@/lib/api'

const STATUS_TONE: Record<CourseModule['interview_status'], 'pos' | 'warn' | 'neutral' | 'outline'> = {
  passed: 'pos',
  in_progress: 'warn',
  failed: 'warn',
  pending: 'outline',
}

const STATUS_LABEL: Record<CourseModule['interview_status'], string> = {
  passed: 'Passed',
  in_progress: 'In progress',
  failed: 'Retry',
  pending: 'Not started',
}

export default function InterviewCoachPage() {
  const navigate = useNavigate()

  const { data: plans, isLoading, isError, refetch } = useQuery({
    queryKey: ['courses'],
    queryFn: () => coursesAPI.list().then((r) => r.data),
    staleTime: 1000 * 60 * 2,
  })

  return (
    <div style={{ padding: '24px 28px', maxWidth: 1100, margin: '0 auto' }}>
      <div style={{ marginBottom: 20 }}>
        <div className="caps fg-3">Workspace</div>
        <h1 className="serif" style={{ fontSize: 36, fontWeight: 400, margin: 0, letterSpacing: '-0.02em' }}>Interview Coach</h1>
        <p className="t-md fg-2" style={{ marginTop: 6 }}>Practice a voice mock interview for any module in your learning paths — the AI asks questions, reviews your answers, and scores you against a rubric.</p>
      </div>

      {isLoading && <p className="t-sm fg-3">Loading your modules…</p>}

      {isError && (
        <div style={{ textAlign: 'center', padding: '32px 0' }}>
          <p className="t-sm fg-2" style={{ marginBottom: 8 }}>Could not load your learning paths.</p>
          <button onClick={() => refetch()} style={{ fontSize: 13, color: 'var(--accent)', background: 'none', border: 0, cursor: 'pointer', fontFamily: 'inherit' }}>Retry →</button>
        </div>
      )}

      {plans && plans.length === 0 && (
        <EmptyState
          icon="interview"
          title="No learning paths yet"
          body="Build a course in Career Paths first — then you can run a mock interview for each module."
          action={{ label: 'Go to Career Paths', onClick: () => navigate('/courses') }}
        />
      )}

      {plans && plans.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          {plans.map((plan: CoursePlan) => (
            <div key={plan.plan_id}>
              <div className="caps fg-2" style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between' }}>
                <span>{plan.title}</span>
                <button onClick={() => navigate(`/courses/${plan.plan_id}`)} style={{ fontSize: 11, color: 'var(--accent)', background: 'none', border: 0, cursor: 'pointer', fontFamily: 'inherit' }}>Open path →</button>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 10 }}>
                {plan.modules.map((m) => (
                  <Card key={m.id} padding="sm" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6, alignItems: 'flex-start' }}>
                      <div className="t-sm fg-0" style={{ fontWeight: 500, lineHeight: 1.3 }}>{m.title}</div>
                      <Badge tone={STATUS_TONE[m.interview_status]} size="xs">{STATUS_LABEL[m.interview_status]}</Badge>
                    </div>
                    <div className="t-xs fg-3" style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                      <Icon name="layers" size={11} /> {m.topics.length} topics
                      {m.interview_score != null && <span> · scored {m.interview_score.toFixed(1)}/10</span>}
                    </div>
                    <Button
                      size="sm"
                      variant={m.interview_status === 'passed' ? 'outline' : 'primary'}
                      icon="mic"
                      onClick={() => navigate(`/courses/${plan.plan_id}/modules/${m.id}/interview`)}
                    >
                      {m.interview_status === 'passed' ? 'Practice again' : 'Start interview'}
                    </Button>
                  </Card>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

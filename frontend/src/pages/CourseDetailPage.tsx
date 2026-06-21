import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import { CardSkeleton } from '@/components/ui/Skeleton'
import { coursesAPI, quizAPI, type CourseModule } from '@/lib/api'
import toast from 'react-hot-toast'

const TYPE_ICON: Record<string, string> = { video: 'play', article: 'book', course: 'sparkle', book: 'book', tool: 'code' }

const STATUS_CONFIG = {
  pending:     { tone: 'neutral' as const, label: 'Not started' },
  in_progress: { tone: 'warn'    as const, label: 'In progress'  },
  passed:      { tone: 'pos'     as const, label: 'Passed'        },
  failed:      { tone: 'neg'     as const, label: 'Retry'         },
}

interface RoadmapProps {
  passed: boolean
  failed: boolean
  quizLoading: boolean
  onStudy: () => void
  onQuiz: () => void
  onInterview: () => void
}

function ModuleRoadmap({ passed, failed, quizLoading, onStudy, onQuiz, onInterview }: RoadmapProps) {
  const interviewLabel = passed ? 'Review' : failed ? 'Retry' : 'AI Interview'
  const interviewDone = passed

  const steps = [
    {
      num: 1,
      label: 'Study',
      icon: 'book' as const,
      done: false,
      onClick: onStudy,
      loading: false,
    },
    {
      num: 2,
      label: 'Quiz',
      icon: 'zap' as const,
      done: false,
      onClick: onQuiz,
      loading: quizLoading,
    },
    {
      num: 3,
      label: interviewLabel,
      icon: 'mic' as const,
      done: interviewDone,
      onClick: onInterview,
      loading: false,
      primary: true,
    },
  ]

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 0, marginTop: 4 }}>
      {steps.map((step, i) => (
        <div key={step.num} style={{ display: 'flex', alignItems: 'center', flex: i < steps.length - 1 ? 'none' : 1 }}>
          {/* Step button */}
          <button
            onClick={step.loading ? undefined : step.onClick}
            disabled={step.loading}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 12px',
              borderRadius: 'var(--r-pill)',
              border: step.primary && !step.done
                ? '1.5px solid var(--ink-0)'
                : '1.5px solid var(--line-2)',
              background: step.primary && !step.done
                ? 'var(--ink-0)'
                : step.done
                  ? 'color-mix(in srgb, var(--pos) 12%, var(--paper-1))'
                  : 'var(--paper-1)',
              color: step.primary && !step.done
                ? 'var(--paper-0)'
                : step.done
                  ? 'var(--pos)'
                  : 'var(--ink-1)',
              cursor: step.loading ? 'default' : 'pointer',
              fontSize: 12,
              fontWeight: 500,
              fontFamily: 'inherit',
              opacity: step.loading ? 0.6 : 1,
              transition: 'all 0.15s ease',
              whiteSpace: 'nowrap',
              flexShrink: 0,
            }}
          >
            {step.done
              ? <Icon name="check" size={11} />
              : step.loading
                ? <Icon name="refresh" size={11} style={{ animation: 'spin 1s linear infinite' }} />
                : <Icon name={step.icon} size={11} />
            }
            {step.label}
          </button>

          {/* Connector arrow between steps */}
          {i < steps.length - 1 && (
            <div style={{
              width: 20,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              color: 'var(--ink-4)',
            }}>
              <svg width="12" height="8" viewBox="0 0 12 8" fill="none">
                <path d="M1 4h9M7 1l3 3-3 3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function ModuleRow({ module, index, planId, isUnlocked }: { module: CourseModule; index: number; planId: string; isUnlocked: boolean }) {
  const navigate = useNavigate()
  const [quizLoading, setQuizLoading] = useState(false)
  const cfg = STATUS_CONFIG[module.interview_status]
  const score = module.interview_score != null ? (module.interview_score * 10).toFixed(1) : null
  const passed = module.interview_status === 'passed'
  const failed = module.interview_status === 'failed'
  const primaryTopic = module.topics[0] || module.title

  const handleTakeQuiz = async () => {
    setQuizLoading(true)
    try {
      const { data } = await quizAPI.generate(primaryTopic)
      navigate(`/quiz/${data.quiz_id}`)
    } catch {
      toast.error('Could not generate quiz')
    } finally {
      setQuizLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', gap: 16, paddingBottom: 16, opacity: isUnlocked ? 1 : 0.45 }}>
      {/* Timeline */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0 }}>
        <div style={{
          width: 28, height: 28, borderRadius: '50%', display: 'grid', placeItems: 'center',
          fontSize: 11, fontWeight: 600, flexShrink: 0,
          background: passed ? 'var(--pos)' : failed ? 'var(--neg)' : isUnlocked ? 'var(--ink-0)' : 'var(--paper-3)',
          color: passed || failed || isUnlocked ? 'var(--paper-0)' : 'var(--ink-3)',
        }}>
          {passed ? <Icon name="check" size={12} /> : failed ? '✕' : index + 1}
        </div>
        <div style={{ width: 1, flex: 1, background: 'var(--line-1)', marginTop: 4, minHeight: 12 }} />
      </div>

      {/* Content */}
      <Card padding="md" style={{ flex: 1, marginBottom: 0 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 8 }}>
          <div>
            <div className="t-xs fg-3" style={{ marginBottom: 2 }}>Module {index + 1} · {module.duration_days}d</div>
            <div className="t-lg fg-0" style={{ fontWeight: 500 }}>{module.title}</div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
            <Badge tone={cfg.tone} size="xs">{cfg.label}</Badge>
            {score && <span className="t-sm fg-0 mono" style={{ fontWeight: 600 }}>{score}<span className="fg-3">/10</span></span>}
          </div>
        </div>

        <div className="t-sm fg-2" style={{ marginBottom: 10, lineHeight: 1.5 }}>{module.description}</div>

        {/* Topics */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 10 }}>
          {module.topics.map((t) => (
            <Badge key={t} tone="outline" size="xs">{t}</Badge>
          ))}
        </div>

        {/* Resources */}
        {module.resources.length > 0 && (
          <div style={{ marginBottom: 10, display: 'flex', flexDirection: 'column', gap: 4 }}>
            {module.resources.map((r, i) => (
              <a
                key={i}
                href={r.url}
                target="_blank"
                rel="noopener noreferrer"
                style={{ display: 'flex', alignItems: 'center', gap: 6, textDecoration: 'none' }}
              >
                <Icon name={TYPE_ICON[r.type] as any ?? 'book'} size={11} style={{ color: 'var(--ink-3)' }} />
                <span className="t-xs fg-2" style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.title}</span>
                <span className="t-xs fg-3">{r.type}</span>
              </a>
            ))}
          </div>
        )}

        {isUnlocked && (
          <ModuleRoadmap
            passed={passed}
            failed={failed}
            quizLoading={quizLoading}
            onStudy={() => navigate(`/learn?topic=${encodeURIComponent(primaryTopic)}`)}
            onQuiz={handleTakeQuiz}
            onInterview={() => navigate(`/courses/${planId}/modules/${module.id}/interview`)}
          />
        )}
        {!isUnlocked && (
          <div className="t-xs fg-3" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <Icon name="lock" size={11} />
            Pass the previous module's interview to unlock
          </div>
        )}
      </Card>
    </div>
  )
}

export default function CourseDetailPage() {
  const { planId } = useParams<{ planId: string }>()
  const navigate = useNavigate()

  const { data: plan, isLoading } = useQuery({
    queryKey: ['course', planId],
    queryFn: () => coursesAPI.get(planId!).then((r) => r.data),
    enabled: !!planId,
    staleTime: 1000 * 60 * 5,
    gcTime: 1000 * 60 * 15,
    refetchInterval: (q) => {
      const p = q.state.data as { modules?: unknown[] } | undefined
      return p?.modules?.length ? false : 3000  // poll until modules arrive, then stop
    },
  })

  if (isLoading) {
    return (
      <div style={{ padding: '24px 28px', maxWidth: 760, margin: '0 auto' }}>
        <div className="skel" style={{ height: 32, width: 200, borderRadius: 6, marginBottom: 8 }} />
        <div className="skel" style={{ height: 16, width: 320, borderRadius: 4, marginBottom: 24 }} />
        {[0, 1, 2, 3].map((i) => <CardSkeleton key={i} />)}
      </div>
    )
  }

  if (!plan) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '50vh', gap: 12 }}>
        <Icon name="book" size={32} style={{ color: 'var(--ink-3)' }} />
        <div className="t-md fg-2">Plan not found</div>
        <Button variant="secondary" onClick={() => navigate('/courses')}>Back to Plans</Button>
      </div>
    )
  }

  const passedCount = plan.modules.filter((m) => m.interview_status === 'passed').length
  const progressPct = plan.modules.length ? Math.round((passedCount / plan.modules.length) * 100) : 0

  return (
    <div style={{ padding: '24px 28px', maxWidth: 760, margin: '0 auto' }}>
      <button
        onClick={() => navigate('/courses')}
        style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 16, background: 'none', border: 0, cursor: 'pointer', padding: 0 }}
      >
        <Icon name="chevL" size={12} style={{ color: 'var(--ink-3)' }} />
        <span className="t-sm fg-3">All plans</span>
      </button>

      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
          <Badge tone="outline" size="xs">{plan.modules.length} modules</Badge>
          <Badge tone="neutral" size="xs">{plan.total_duration_weeks}w</Badge>
          {passedCount === plan.modules.length && plan.modules.length > 0 && (
            <Badge tone="pos" size="xs">Completed</Badge>
          )}
        </div>
        <h1 className="serif" style={{ fontSize: 32, fontWeight: 400, margin: 0, letterSpacing: '-0.02em' }}>{plan.title}</h1>
        <p className="t-md fg-2" style={{ marginTop: 6 }}>{plan.description}</p>

        {/* Progress bar */}
        <div style={{ marginTop: 14 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span className="t-xs fg-3">{passedCount} of {plan.modules.length} modules passed</span>
            <span className="t-xs fg-3 mono">{progressPct}%</span>
          </div>
          <div style={{ height: 6, background: 'var(--paper-3)', borderRadius: 'var(--r-pill)', overflow: 'hidden' }}>
            <div style={{ width: `${progressPct}%`, height: '100%', background: 'var(--ink-0)', borderRadius: 'var(--r-pill)', transition: 'width 0.8s ease' }} />
          </div>
        </div>
      </div>

      {/* Timeline */}
      <div>
        {plan.modules.map((module, i) => {
          const prevAttempted = i === 0 || plan.modules[i - 1].interview_status !== 'pending'
          return (
            <ModuleRow key={module.id} module={module} index={i} planId={plan.plan_id} isUnlocked={prevAttempted} />
          )
        })}
        {/* End marker */}
        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          <div style={{ width: 28, display: 'flex', justifyContent: 'center' }}>
            <div style={{
              width: 12, height: 12, borderRadius: '50%',
              background: passedCount === plan.modules.length ? 'var(--pos)' : 'var(--paper-3)',
              border: '2px solid',
              borderColor: passedCount === plan.modules.length ? 'var(--pos)' : 'var(--line-2)',
            }} />
          </div>
          <span className="t-sm" style={{ color: passedCount === plan.modules.length ? 'var(--pos)' : 'var(--ink-3)' }}>
            {passedCount === plan.modules.length ? 'Course Complete!' : 'Finish all modules to complete the course'}
          </span>
        </div>
      </div>
    </div>
  )
}

import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { PageWrapper } from '@/components/layout/PageWrapper'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Skeleton } from '@/components/ui/Skeleton'
import { coursesAPI, type CourseModule } from '@/lib/api'

const TYPE_ICON: Record<string, string> = {
  video: '▶️',
  article: '📄',
  course: '🎓',
  book: '📚',
  tool: '🛠️',
}

const STATUS_CONFIG = {
  pending: { variant: 'surface' as const, label: 'Not started', icon: '○' },
  in_progress: { variant: 'amber' as const, label: 'In progress', icon: '◑' },
  passed: { variant: 'emerald' as const, label: 'Passed', icon: '✓' },
  failed: { variant: 'rose' as const, label: 'Failed — retry', icon: '✕' },
}

function ModuleCard({
  module,
  index,
  planId,
  isUnlocked,
}: {
  module: CourseModule
  index: number
  planId: string
  isUnlocked: boolean
}) {
  const navigate = useNavigate()
  const cfg = STATUS_CONFIG[module.interview_status]
  const scorePercent = module.interview_score != null ? Math.round(module.interview_score * 100) : null

  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.06 }}
      className="relative flex gap-4"
    >
      {/* Timeline spine */}
      <div className="flex flex-col items-center">
        <div
          className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold shrink-0 border-2 transition-all ${
            module.interview_status === 'passed'
              ? 'bg-emerald/20 border-emerald text-emerald'
              : module.interview_status === 'failed'
              ? 'bg-rose/20 border-rose text-rose'
              : isUnlocked
              ? 'bg-violet/20 border-violet text-violet-light'
              : 'bg-surface-2 border-surface-3 text-paper/30'
          }`}
        >
          {module.interview_status === 'passed' ? '✓' : module.interview_status === 'failed' ? '✕' : index + 1}
        </div>
        {/* Connector line */}
        <div className="w-px flex-1 bg-surface-3 mt-2 min-h-[16px]" />
      </div>

      {/* Content */}
      <div className="flex-1 pb-6">
        <div
          className={`glass-strong rounded-2xl p-5 transition-all ${
            !isUnlocked ? 'opacity-50' : 'hover:border-violet/30'
          } border border-surface-2/50`}
        >
          <div className="flex items-start justify-between mb-3">
            <div>
              <p className="text-xs text-paper/40 mb-1">Module {index + 1} · {module.duration_days} days</p>
              <h3 className="font-display text-lg text-paper leading-tight">{module.title}</h3>
            </div>
            <div className="flex flex-col items-end gap-1 shrink-0 ml-4">
              <Badge variant={cfg.variant}>{cfg.label}</Badge>
              {scorePercent != null && (
                <span className="text-xs text-paper/40">{scorePercent}% score</span>
              )}
            </div>
          </div>

          <p className="text-sm text-paper/60 mb-4">{module.description}</p>

          {/* Topics */}
          <div className="flex flex-wrap gap-1.5 mb-4">
            {module.topics.map((t) => (
              <span key={t} className="text-xs px-2 py-0.5 rounded-full bg-surface-2 border border-surface-3 text-paper/50">
                {t}
              </span>
            ))}
          </div>

          {/* Resources */}
          {module.resources.length > 0 && (
            <div className="space-y-1.5 mb-4">
              {module.resources.map((r, i) => (
                <a
                  key={i}
                  href={r.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 text-xs text-paper/50 hover:text-paper/80 transition-colors group"
                >
                  <span>{TYPE_ICON[r.type] ?? '🔗'}</span>
                  <span className="group-hover:underline truncate">{r.title}</span>
                  <span className="ml-auto text-paper/30 shrink-0">{r.type}</span>
                </a>
              ))}
            </div>
          )}

          {/* Interview button */}
          {isUnlocked && (
            <Button
              size="sm"
              variant={module.interview_status === 'passed' ? 'secondary' : 'primary'}
              onClick={() => navigate(`/courses/${planId}/modules/${module.id}/interview`)}
            >
              {module.interview_status === 'passed'
                ? 'Review interview'
                : module.interview_status === 'failed'
                ? 'Retry interview →'
                : 'Start AI Interview →'}
            </Button>
          )}

          {!isUnlocked && (
            <p className="text-xs text-paper/30 flex items-center gap-1.5">
              🔒 Complete the previous module's interview to unlock
            </p>
          )}
        </div>
      </div>
    </motion.div>
  )
}

export default function CourseDetailPage() {
  const { planId } = useParams<{ planId: string }>()
  const navigate = useNavigate()

  const { data: plan, isLoading } = useQuery({
    queryKey: ['course', planId],
    queryFn: () => coursesAPI.get(planId!).then((r) => r.data),
    enabled: !!planId,
    refetchInterval: 5000,
  })

  if (isLoading) {
    return (
      <PageWrapper>
        <div className="px-6 py-8 max-w-3xl mx-auto space-y-4">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-4 w-48" />
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-48 w-full rounded-2xl" />
          ))}
        </div>
      </PageWrapper>
    )
  }

  if (!plan) {
    return (
      <PageWrapper>
        <div className="flex flex-col items-center justify-center min-h-[50vh] gap-4 text-paper/50">
          <span className="text-4xl">🗺️</span>
          <p>Plan not found</p>
          <Button variant="secondary" onClick={() => navigate('/courses')}>← Back to Plans</Button>
        </div>
      </PageWrapper>
    )
  }

  const passedCount = plan.modules.filter((m) => m.interview_status === 'passed').length
  const totalWeeks = plan.total_duration_weeks
  const progressPct = Math.round((passedCount / plan.modules.length) * 100)

  return (
    <PageWrapper>
      <div className="px-6 py-8 max-w-3xl mx-auto">
        {/* Back */}
        <button
          onClick={() => navigate('/courses')}
          className="flex items-center gap-1.5 text-sm text-paper/40 hover:text-paper/70 mb-6 transition-colors"
        >
          ← All Plans
        </button>

        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <Badge variant="violet">{plan.modules.length} modules</Badge>
            <Badge variant="surface">{totalWeeks} weeks</Badge>
            {passedCount === plan.modules.length && (
              <Badge variant="emerald">Completed 🎉</Badge>
            )}
          </div>
          <h1 className="font-display text-3xl text-paper mb-2">{plan.title}</h1>
          <p className="text-paper/50 text-sm">{plan.description}</p>

          {/* Overall progress */}
          <div className="mt-5">
            <div className="flex justify-between text-xs text-paper/40 mb-1.5">
              <span>{passedCount} of {plan.modules.length} modules passed</span>
              <span>{progressPct}%</span>
            </div>
            <div className="h-2 bg-surface-2 rounded-full overflow-hidden">
              <motion.div
                className="h-full bg-gradient-to-r from-violet to-emerald rounded-full"
                initial={{ width: 0 }}
                animate={{ width: `${progressPct}%` }}
                transition={{ duration: 1, ease: 'easeOut' }}
              />
            </div>
          </div>
        </div>

        {/* Timeline */}
        <div>
          {plan.modules.map((module, i) => {
            const prevPassed = i === 0 || plan.modules[i - 1].interview_status === 'passed'
            return (
              <ModuleCard
                key={module.id}
                module={module}
                index={i}
                planId={plan.plan_id}
                isUnlocked={prevPassed}
              />
            )
          })}
          {/* End marker */}
          <div className="flex gap-4 items-center pl-0">
            <div className="w-9 flex justify-center">
              <div className={`w-4 h-4 rounded-full border-2 ${passedCount === plan.modules.length ? 'bg-emerald border-emerald' : 'bg-surface-2 border-surface-3'}`} />
            </div>
            <p className={`text-sm ${passedCount === plan.modules.length ? 'text-emerald font-medium' : 'text-paper/30'}`}>
              {passedCount === plan.modules.length ? '🎓 Course Complete!' : 'Finish all modules to complete the course'}
            </p>
          </div>
        </div>
      </div>
    </PageWrapper>
  )
}

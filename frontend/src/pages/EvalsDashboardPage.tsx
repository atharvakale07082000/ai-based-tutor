import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { EmptyState } from '@/components/ui/EmptyState'
import { evalsAPI, type EvalRecentItem } from '@/lib/api'
import { useLearnerStore } from '@/stores/learnerStore'

const METRIC_LABELS: Record<string, string> = {
  faithfulness: 'Faithfulness',
  answer_correctness: 'Correctness',
  answer_accuracy: 'Accuracy',
  conversation_consistency: 'Consistency',
  conversation_knowledge_retention: 'Knowledge Retention',
  conversation_role_adherence: 'Role Adherence',
  doubt_accuracy: 'Doubt Accuracy',
  quiz_bloom_alignment: 'Quiz Bloom Fit',
  curriculum_coherence: 'Curriculum Coherence',
  chat_session: 'Chat Session',
}
const labelFor = (k: string) => METRIC_LABELS[k] ?? k.replace(/_/g, ' ')

function scoreColor(s: number): string {
  return s >= 0.7 ? 'var(--pos)' : s >= 0.5 ? 'var(--warn)' : 'var(--neg)'
}

function pct(n: number) { return `${Math.round(n * 100)}%` }

function timeAgo(iso: string): string {
  const sec = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (sec < 60) return 'just now'
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`
  return `${Math.floor(sec / 86400)}d ago`
}

function StatCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <Card padding="md" style={{ flex: 1, minWidth: 150 }}>
      <div className="caps fg-3" style={{ marginBottom: 6 }}>{label}</div>
      <div className="serif" style={{ fontSize: 30, fontWeight: 400, color: color ?? 'var(--ink-0)', lineHeight: 1 }}>{value}</div>
      {sub && <div className="t-xs fg-3" style={{ marginTop: 4 }}>{sub}</div>}
    </Card>
  )
}

function ScoreBar({ score }: { score: number }) {
  return (
    <div style={{ height: 5, background: 'var(--paper-3)', borderRadius: 'var(--r-pill)', overflow: 'hidden' }}>
      <div style={{ width: `${score * 100}%`, height: '100%', background: scoreColor(score), borderRadius: 'var(--r-pill)', transition: 'width 0.5s ease' }} />
    </div>
  )
}

export default function EvalsDashboardPage() {
  const navigate = useNavigate()
  const role = useLearnerStore((s) => s.role)

  const { data, isLoading, isError, dataUpdatedAt } = useQuery({
    queryKey: ['evals-dashboard'],
    queryFn: () => evalsAPI.dashboard().then((r) => r.data),
    refetchInterval: 15000,        // live dashboard — refetch every 15s
    refetchOnWindowFocus: true,
    enabled: role === 'superuser',
    retry: false,
  })

  if (role !== 'superuser') {
    return (
      <div style={{ padding: '48px 28px', maxWidth: 600, margin: '0 auto' }}>
        <EmptyState
          icon="lock"
          title="Restricted"
          body="The evaluations dashboard is available to the superuser account only."
          action={{ label: 'Back to dashboard', onClick: () => navigate('/dashboard') }}
        />
      </div>
    )
  }

  return (
    <div style={{ padding: '24px 28px', maxWidth: 1240, margin: '0 auto' }}>
      <div style={{ marginBottom: 20, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 8 }}>
        <div>
          <div className="caps fg-3">Superuser</div>
          <h1 className="serif" style={{ fontSize: 36, fontWeight: 400, margin: 0, letterSpacing: '-0.02em' }}>Agent Evals</h1>
          <p className="t-md fg-2" style={{ marginTop: 6 }}>Live DeepEval quality scores — faithfulness, correctness, accuracy & multi-turn consistency — sampled from real requests.</p>
        </div>
        <span className="t-xs fg-3" style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <span className="pulse-dot" style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--pos)' }} />
          Live{dataUpdatedAt ? ` · updated ${timeAgo(new Date(dataUpdatedAt).toISOString())}` : ''}
        </span>
      </div>

      {isLoading && <p className="t-sm fg-3">Loading eval metrics…</p>}
      {isError && <p className="t-sm" style={{ color: 'var(--neg)' }}>Could not load evals.</p>}

      {data && data.overall.total === 0 && (
        <EmptyState icon="target" title="No evals yet" body="Evals are sampled randomly from live requests. Use the assistant a few times and they'll appear here." />
      )}

      {data && data.overall.total > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          {/* Overall */}
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <StatCard label="Total evals" value={data.overall.total.toLocaleString()} />
            <StatCard label="Pass rate" value={pct(data.overall.pass_rate)} color={scoreColor(data.overall.pass_rate)} />
            <StatCard label="Avg score" value={pct(data.overall.avg_score)} color={scoreColor(data.overall.avg_score)} />
            <StatCard label="Metrics tracked" value={String(data.by_metric.length)} />
          </div>

          {/* By metric */}
          <div>
            <div className="caps fg-2" style={{ marginBottom: 10 }}>By metric</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 12 }}>
              {data.by_metric.map((m) => (
                <Card key={m.eval_type} padding="md" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                    <span className="t-sm fg-0" style={{ fontWeight: 500 }}>{labelFor(m.eval_type)}</span>
                    <span className="mono t-sm" style={{ color: scoreColor(m.avg_score) }}>{pct(m.avg_score)}</span>
                  </div>
                  <ScoreBar score={m.avg_score} />
                  <div className="t-xs fg-3" style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span>{m.total} runs</span>
                    <span>{pct(m.pass_rate)} pass</span>
                  </div>
                </Card>
              ))}
            </div>
          </div>

          {/* By agent + Trend */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <Card padding="md">
              <div className="caps fg-2" style={{ marginBottom: 10 }}>By agent</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {data.by_agent.map((a) => (
                  <div key={a.agent} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span className="t-sm fg-1" style={{ width: 110, textTransform: 'capitalize' }}>{a.agent || '—'}</span>
                    <div style={{ flex: 1 }}><ScoreBar score={a.avg_score} /></div>
                    <span className="mono t-xs fg-3" style={{ width: 70, textAlign: 'right' }}>{pct(a.avg_score)} · {a.total}</span>
                  </div>
                ))}
              </div>
            </Card>

            <Card padding="md">
              <div className="caps fg-2" style={{ marginBottom: 10 }}>14-day score trend</div>
              {data.trend.length === 0 ? (
                <p className="t-xs fg-3">Not enough data yet.</p>
              ) : (
                <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 120 }}>
                  {data.trend.map((d) => (
                    <div key={d.day} title={`${d.day}: ${pct(d.avg_score)} (${d.count})`} style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', height: '100%' }}>
                      <div style={{ height: `${Math.max(4, d.avg_score * 100)}%`, background: scoreColor(d.avg_score), borderRadius: '3px 3px 0 0' }} />
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>

          {/* Recent */}
          <Card padding="md">
            <div className="caps fg-2" style={{ marginBottom: 6 }}>Recent evaluations</div>
            <div style={{ maxHeight: 420, overflowY: 'auto' }}>
              {data.recent.map((r: EvalRecentItem, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 0', borderTop: '1px solid var(--line-1)' }}>
                  <Badge size="xs" tone={r.passed ? 'pos' : 'neg'}>{r.passed ? 'pass' : 'fail'}</Badge>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="t-sm fg-0" style={{ fontWeight: 500 }}>
                      {labelFor(r.eval_type)} <span className="fg-3" style={{ fontWeight: 400 }}>· {r.agent}</span>
                    </div>
                    {r.details?.reason && (
                      <div className="t-xs fg-3" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.details.reason}</div>
                    )}
                  </div>
                  <span className="mono t-xs" style={{ color: scoreColor(r.score), flexShrink: 0 }}>{pct(r.score)}</span>
                  <span className="t-xs fg-3" style={{ flexShrink: 0, width: 64, textAlign: 'right' }}>{timeAgo(r.timestamp)}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}
    </div>
  )
}

import { useEffect, useState } from 'react'
import { Routes, Route, Link, Navigate, useNavigate } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { Icon } from '@/components/ui/Icon'
import { adminAPI, hfAPI, type HFModelStatusAPI } from '@/lib/api'
import { useAgentStore, type HFModelStatus } from '@/stores/agentStore'
import { useLearnerStore } from '@/stores/learnerStore'
import { HF_MODELS } from '@/lib/hf'
import toast from 'react-hot-toast'

const MOOD_EMOJI: Record<string, string> = { POSITIVE: '😊', NEGATIVE: '😟', NEUTRAL: '😐' }

function AdminOverview() {
  const [search, setSearch] = useState('')
  // Only settings an agent actually reads live here. "Quiz Frequency" and
  // "Escalation Threshold" were retired: they named systems this platform does not
  // have, and the whole panel wrote to an in-memory dict nothing read.
  const [ceiling, setCeiling] = useState(100)

  const { data: learners, isLoading } = useQuery({
    queryKey: ['admin', 'learners', search],
    queryFn: () => adminAPI.getLearners(search, 1).then((r) => r.data),
    staleTime: 1000 * 60,       // learner list: 1 min
    gcTime: 1000 * 60 * 5,
  })

  // Real org-wide gaps, aggregated server-side. This panel used to render eight
  // hardcoded percentages as if they were live analytics.
  const { data: gaps, isLoading: gapsLoading } = useQuery({
    queryKey: ['admin', 'skillGaps'],
    queryFn: () => adminAPI.getSkillGaps().then((r) => r.data),
    staleTime: 1000 * 60 * 5,
  })

  // Seed the slider from the stored value so it shows what is actually in force.
  const { data: storedConfig } = useQuery({
    queryKey: ['adminConfig'],
    queryFn: () => adminAPI.getConfig().then((r) => r.data),
    staleTime: 1000 * 60,
  })
  useEffect(() => {
    if (typeof storedConfig?.difficulty_ceiling === 'number') {
      setCeiling(Math.round(storedConfig.difficulty_ceiling * 100))
    }
  }, [storedConfig])

  const configMutation = useMutation({
    mutationFn: () => adminAPI.updateConfig({ difficulty_ceiling: ceiling / 100 }),
    onSuccess: () => toast.success('Agent settings saved'),
    onError: () => toast.error('Could not save agent settings — try again'),
  })

  return (
    <div style={{ padding: '24px 28px', maxWidth: 1240, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <div>
          <div className="eyebrow">Admin</div>
          <h1 className="display" style={{ fontSize: 38, fontWeight: 600, margin: 0, letterSpacing: '-0.03em' }}>Dashboard</h1>
        </div>
        <Link to="models" style={{ textDecoration: 'none' }}>
          <Button variant="secondary" size="sm" icon="sparkle">AI Model Status</Button>
        </Link>
      </div>

      {/* Skill gap heatmap (simplified bar chart — no recharts dependency) */}
      <Card padding="md">
        <div className="caps fg-2" style={{ marginBottom: 4 }}>Org Skill Gap · share of learners below mastery</div>
        <div className="t-xs fg-3" style={{ marginBottom: 12 }}>
          Topics tracked by 2+ learners, ranked by how many are still under {gaps?.mastery_elo ?? 700} Elo.
        </div>

        {gapsLoading && <span className="t-sm fg-3">Aggregating proficiency…</span>}

        {!gapsLoading && (!gaps || gaps.items.length === 0) && (
          <span className="t-sm fg-3">
            Not enough data yet — gaps appear once at least two learners share a topic.
          </span>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {gaps?.items.map((t) => (
            <div key={t.name} style={{ display: 'grid', gridTemplateColumns: '140px 1fr 96px', gap: 10, alignItems: 'center' }}>
              <span className="t-sm fg-1" style={{ fontWeight: 500 }}>{t.name}</span>
              <div style={{ height: 8, background: 'var(--paper-3)', borderRadius: 'var(--r-pill)', overflow: 'hidden' }}>
                <div style={{ width: `${t.pct * 100}%`, height: '100%', background: 'var(--ink-0)', borderRadius: 'var(--r-pill)' }} />
              </div>
              {/* The raw counts matter: 100% of 2 learners is a very different signal from 100% of 40. */}
              <span className="t-xs fg-3 mono" style={{ textAlign: 'right' }}>
                {Math.round(t.pct * 100)}% · {t.below_mastery}/{t.learners}
              </span>
            </div>
          ))}
        </div>
      </Card>

      {/* Learner table */}
      <Card padding="md">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <span className="caps fg-2">Learner Overview</span>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search learners…"
            style={{
              background: 'var(--paper-2)', border: '1px solid var(--line-1)',
              borderRadius: 'var(--r-2)', padding: '5px 10px', fontSize: 13,
              color: 'var(--ink-0)', fontFamily: 'inherit', outline: 'none', width: 200,
            }}
          />
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr>
                {['Name', 'Email', 'Avg. Proficiency', 'Last Active', 'Mood'].map((h) => (
                  <th key={h} style={{ textAlign: 'left', paddingBottom: 10, paddingRight: 16, borderBottom: '1px solid var(--line-1)', color: 'var(--ink-3)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 500 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i}>
                    {Array.from({ length: 5 }).map((_, j) => (
                      <td key={j} style={{ padding: '10px 16px 10px 0' }}>
                        <div className="skel" style={{ height: 14, width: 80, borderRadius: 4 }} />
                      </td>
                    ))}
                  </tr>
                ))
              ) : (
                (learners?.items ?? []).map((learner) => (
                  <tr key={learner.id} style={{ borderTop: '1px solid var(--line-1)' }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--paper-2)')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    <td style={{ padding: '10px 16px 10px 0', fontWeight: 500, color: 'var(--ink-0)' }}>{learner.name}</td>
                    <td style={{ padding: '10px 16px 10px 0', color: 'var(--ink-3)' }}>{learner.email}</td>
                    <td style={{ padding: '10px 16px 10px 0' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <div style={{ width: 64, height: 4, background: 'var(--paper-3)', borderRadius: 'var(--r-pill)', overflow: 'hidden' }}>
                          <div style={{ width: `${(learner.avg_proficiency / 1000) * 100}%`, height: '100%', background: 'var(--ink-0)', borderRadius: 'var(--r-pill)' }} />
                        </div>
                        <span className="t-xs fg-3 mono">{Math.round((learner.avg_proficiency / 1000) * 100)}%</span>
                      </div>
                    </td>
                    <td style={{ padding: '10px 16px 10px 0', color: 'var(--ink-3)' }}>{new Date(learner.last_active).toLocaleDateString()}</td>
                    <td style={{ padding: '10px 0' }}>{MOOD_EMOJI[learner.mood?.toUpperCase() ?? ''] ?? '—'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
          {!isLoading && (learners?.items ?? []).length === 0 && (
            <div className="t-sm fg-3" style={{ textAlign: 'center', padding: '24px 0' }}>No learners found.</div>
          )}
        </div>
      </Card>

      {/* Agent settings */}
      <Card padding="md">
        <div className="caps fg-2" style={{ marginBottom: 6 }}>Agent Settings</div>
        <div className="t-xs fg-3" style={{ marginBottom: 16, maxWidth: 460, lineHeight: 1.5 }}>
          Applies to every learner who has not set their own. Quiz difficulty is chosen from
          each learner's proficiency; this caps how demanding it may get.
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
              <span className="t-sm fg-1">Difficulty ceiling</span>
              <span className="t-sm fg-0 mono" style={{ fontWeight: 600 }}>{ceiling}%</span>
            </div>
            <input
              type="range" min={20} max={100}
              value={ceiling}
              aria-label="Difficulty ceiling, percent"
              onChange={(e) => setCeiling(Number(e.target.value))}
              style={{ width: '100%', accentColor: 'var(--ink-0)', height: 4 }}
            />
          </div>
          <div style={{ paddingTop: 4 }}>
            <Button variant="primary" onClick={() => configMutation.mutate()} loading={configMutation.isPending}>Save agent settings</Button>
          </div>
        </div>
      </Card>
    </div>
  )
}

/*
 * The model panel merges two differently-shaped sources: the live `/hf/status`
 * response (`HFModelStatusAPI` — snake_case, ISO timestamp) and the agent
 * store's cached view (`HFModelStatus` — camelCase, epoch ms). Normalising to
 * one shape is what removes the `(status as any).last_used` casts, and it also
 * fixes a latent bug those casts hid: reading the API key off a store value
 * always yielded `undefined`, so the store's own timings rendered as "—".
 */
interface ModelStatusView {
  status: HFModelStatus['status'] | null
  lastUsed: string | number | null
  latencyMs: number | null
}

function toStatusView(live?: HFModelStatusAPI, stored?: HFModelStatus): ModelStatusView {
  if (live) {
    return { status: live.status, lastUsed: live.last_used ?? null, latencyMs: live.latency_ms ?? null }
  }
  if (stored) {
    return { status: stored.status, lastUsed: stored.lastUsed, latencyMs: stored.latencyMs }
  }
  return { status: null, lastUsed: null, latencyMs: null }
}

function HFModelsPanel() {
  const { hfModels, tokenUsage } = useAgentStore()
  const [testResults, setTestResults] = useState<Record<string, unknown>>({})
  const [testing, setTesting] = useState<string | null>(null)

  const { data: liveStatus } = useQuery({
    queryKey: ['hf', 'status'],
    queryFn: () => hfAPI.status().then((r) => r.data),
    refetchInterval: 30000,
  })

  const handleTest = async (modelKey: string) => {
    setTesting(modelKey)
    try {
      const { data } = await hfAPI.test(modelKey)
      setTestResults((prev) => ({ ...prev, [modelKey]: data }))
      toast.success(`${modelKey} test successful`)
    } catch (err) {
      toast.error(`Could not reach ${modelKey} — try again`)
      setTestResults((prev) => ({ ...prev, [modelKey]: { error: String(err) } }))
    } finally {
      setTesting(null) }
  }

  return (
    <div style={{ padding: '24px 28px', maxWidth: 1240, margin: '0 auto' }}>
      <div style={{ marginBottom: 20 }}>
        <Link to=".." relative="path" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, textDecoration: 'none', marginBottom: 12 }}>
          <Icon name="chevL" size={12} style={{ color: 'var(--ink-3)' }} />
          <span className="t-sm fg-3">Back to Admin</span>
        </Link>
        <div className="caps fg-3">HuggingFace Inference</div>
        <h1 className="display" style={{ fontSize: 38, fontWeight: 600, margin: 0, letterSpacing: '-0.03em' }}>AI Model Status</h1>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
        {Object.entries(HF_MODELS).map(([key, modelId]) => {
          const status = toStatusView(liveStatus?.[key], hfModels[key])
          const tokens = tokenUsage[key] ?? 0
          const tone = status.status === 'ok' ? 'pos' : status.status === 'loading' ? 'warn' : 'neg'

          return (
            <Card key={key} padding="md">
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 10 }}>
                <div>
                  <div className="caps fg-3" style={{ marginBottom: 2 }}>{key.replace(/_/g, ' ')}</div>
                  <div className="t-sm fg-1 mono">{modelId}</div>
                </div>
                <Badge tone={tone} size="xs" dot>{status.status ?? 'unknown'}</Badge>
              </div>

              <div style={{ display: 'flex', gap: 16, marginBottom: 12 }}>
                <div>
                  <div className="t-xs fg-3">Last used</div>
                  <div className="t-xs fg-1 mono">
                    {status.lastUsed != null ? new Date(status.lastUsed).toLocaleTimeString() : '—'}
                  </div>
                </div>
                <div>
                  <div className="t-xs fg-3">Latency</div>
                  <div className="t-xs fg-1 mono">
                    {status.latencyMs != null ? `${status.latencyMs}ms` : '—'}
                  </div>
                </div>
                <div>
                  <div className="t-xs fg-3">Tokens</div>
                  <div className="t-xs fg-1 mono">{tokens.toLocaleString()}</div>
                </div>
              </div>

              <Button size="sm" variant="outline" onClick={() => handleTest(key)} loading={testing === key}>Test model</Button>

              {!!testResults[key] && (
                <pre style={{ marginTop: 10, fontSize: 10, background: 'var(--paper-2)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-2)', padding: 10, overflowX: 'auto', color: 'var(--pos)', maxHeight: 120 }}>
                  {JSON.stringify(testResults[key], null, 2)}
                </pre>
              )}
            </Card>
          )
        })}
      </div>
    </div>
  )
}

export default function AdminPage() {
  const navigate = useNavigate()
  const role = useLearnerStore((s) => s.role)

  // The /admin API is superuser-only (it exposes every learner's PII). Guard here too so
  // learners get a clean message instead of a wall of 403s. Same pattern as /evals.
  if (role !== 'superuser') {
    return (
      <div style={{ padding: '48px 28px', maxWidth: 600, margin: '0 auto' }}>
        <EmptyState
          icon="lock"
          title="Admins only"
          body="The admin dashboard shows every learner's progress and profile. It is open to admin accounts only."
          action={{ label: 'Back to dashboard', onClick: () => navigate('/dashboard') }}
        />
      </div>
    )
  }

  return (
    <Routes>
      <Route index element={<AdminOverview />} />
      <Route path="models" element={<HFModelsPanel />} />
      <Route path="*" element={<Navigate to="/admin" replace />} />
    </Routes>
  )
}

import { useState } from 'react'
import { Routes, Route, Link, Navigate } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import { adminAPI, hfAPI } from '@/lib/api'
import { useAgentStore } from '@/stores/agentStore'
import { HF_MODELS } from '@/lib/hf'
import toast from 'react-hot-toast'

const MOOD_EMOJI: Record<string, string> = { POSITIVE: '😊', NEGATIVE: '😟', NEUTRAL: '😐' }

const TOPIC_GAPS = [
  { name: 'Python',          pct: 0.42 },
  { name: 'Machine Learning',pct: 0.35 },
  { name: 'Statistics',      pct: 0.28 },
  { name: 'Deep Learning',   pct: 0.22 },
  { name: 'NLP',             pct: 0.18 },
  { name: 'Data Viz',        pct: 0.15 },
  { name: 'SQL',             pct: 0.12 },
  { name: 'Cloud',           pct: 0.09 },
]

function AdminOverview() {
  const [search, setSearch] = useState('')
  const [config, setConfig] = useState({ quiz_frequency: 3, difficulty_ceiling: 80, escalation_threshold: 3 })

  const { data: learners, isLoading } = useQuery({
    queryKey: ['admin', 'learners', search],
    queryFn: () => adminAPI.getLearners(search, 1).then((r) => r.data),
  })

  const configMutation = useMutation({
    mutationFn: adminAPI.updateConfig,
    onSuccess: () => toast.success('Agent config updated'),
    onError: () => toast.error('Could not update config'),
  })

  return (
    <div style={{ padding: '24px 28px', maxWidth: 1240, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <div>
          <div className="caps fg-3">Admin</div>
          <h1 className="serif" style={{ fontSize: 36, fontWeight: 400, margin: 0, letterSpacing: '-0.02em' }}>Dashboard</h1>
        </div>
        <Link to="models" style={{ textDecoration: 'none' }}>
          <Button variant="secondary" size="sm" icon="sparkle">AI Model Status</Button>
        </Link>
      </div>

      {/* Skill gap heatmap (simplified bar chart — no recharts dependency) */}
      <Card padding="md">
        <div className="caps fg-2" style={{ marginBottom: 12 }}>Org Skill Gap Heatmap · learner count with gaps</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {TOPIC_GAPS.map((t) => (
            <div key={t.name} style={{ display: 'grid', gridTemplateColumns: '140px 1fr 48px', gap: 10, alignItems: 'center' }}>
              <span className="t-sm fg-1" style={{ fontWeight: 500 }}>{t.name}</span>
              <div style={{ height: 8, background: 'var(--paper-3)', borderRadius: 'var(--r-pill)', overflow: 'hidden' }}>
                <div style={{ width: `${t.pct * 100}%`, height: '100%', background: 'var(--ink-0)', borderRadius: 'var(--r-pill)' }} />
              </div>
              <span className="t-xs fg-3 mono" style={{ textAlign: 'right' }}>{Math.round(t.pct * 100)}%</span>
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

      {/* Agent config */}
      <Card padding="md">
        <div className="caps fg-2" style={{ marginBottom: 16 }}>Agent Configuration</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          {([
            { key: 'quiz_frequency' as const,       label: 'Quiz Frequency',        unit: 'per week',      min: 1, max: 14  },
            { key: 'difficulty_ceiling' as const,    label: 'Difficulty Ceiling',    unit: '%',             min: 20, max: 100 },
            { key: 'escalation_threshold' as const,  label: 'Escalation Threshold',  unit: 'failed attempts', min: 1, max: 10  },
          ]).map(({ key, label, unit, min, max }) => (
            <div key={key}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                <span className="t-sm fg-1">{label}</span>
                <span className="t-sm fg-0 mono" style={{ fontWeight: 600 }}>{config[key]} {unit}</span>
              </div>
              <input
                type="range" min={min} max={max}
                value={config[key]}
                onChange={(e) => setConfig((c) => ({ ...c, [key]: Number(e.target.value) }))}
                style={{ width: '100%', accentColor: 'var(--ink-0)', height: 4 }}
              />
            </div>
          ))}
          <div style={{ paddingTop: 4 }}>
            <Button variant="primary" onClick={() => configMutation.mutate(config)} loading={configMutation.isPending}>Save Agent Config</Button>
          </div>
        </div>
      </Card>
    </div>
  )
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
      toast.error(`${modelKey} test failed`)
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
        <h1 className="serif" style={{ fontSize: 36, fontWeight: 400, margin: 0, letterSpacing: '-0.02em' }}>AI Model Status</h1>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
        {Object.entries(HF_MODELS).map(([key, modelId]) => {
          const status = liveStatus?.[key] ?? hfModels[key]
          const tokens = tokenUsage[key] ?? 0
          const tone = status?.status === 'ok' ? 'pos' : status?.status === 'loading' ? 'warn' : 'neg'

          return (
            <Card key={key} padding="md">
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 10 }}>
                <div>
                  <div className="caps fg-3" style={{ marginBottom: 2 }}>{key.replace(/_/g, ' ')}</div>
                  <div className="t-sm fg-1 mono">{modelId}</div>
                </div>
                <Badge tone={tone} size="xs" dot>{status?.status ?? 'unknown'}</Badge>
              </div>

              <div style={{ display: 'flex', gap: 16, marginBottom: 12 }}>
                <div>
                  <div className="t-xs fg-3">Last used</div>
                  <div className="t-xs fg-1 mono">
                    {(status as any)?.last_used ? new Date((status as any).last_used).toLocaleTimeString() : '—'}
                  </div>
                </div>
                <div>
                  <div className="t-xs fg-3">Latency</div>
                  <div className="t-xs fg-1 mono">
                    {(status as any)?.latency_ms != null ? `${(status as any).latency_ms}ms` : '—'}
                  </div>
                </div>
                <div>
                  <div className="t-xs fg-3">Tokens</div>
                  <div className="t-xs fg-1 mono">{tokens.toLocaleString()}</div>
                </div>
              </div>

              <Button size="sm" variant="outline" onClick={() => handleTest(key)} loading={testing === key}>Test Model</Button>

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
  return (
    <Routes>
      <Route index element={<AdminOverview />} />
      <Route path="models" element={<HFModelsPanel />} />
      <Route path="*" element={<Navigate to="/admin" replace />} />
    </Routes>
  )
}

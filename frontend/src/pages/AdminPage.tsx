import { useState } from 'react'
import { Routes, Route, Link, useLocation, Navigate } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Treemap, ResponsiveContainer, Tooltip } from 'recharts'
import { PageWrapper } from '@/components/layout/PageWrapper'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Skeleton } from '@/components/ui/Skeleton'
import { Button } from '@/components/ui/Button'
import { adminAPI, hfAPI } from '@/lib/api'
import { useAgentStore } from '@/stores/agentStore'
import { HF_MODELS } from '@/lib/hf'
import toast from 'react-hot-toast'

function AdminOverview() {
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [config, setConfig] = useState({
    quiz_frequency: 3,
    difficulty_ceiling: 80,
    escalation_threshold: 3,
  })

  const { data: learners, isLoading } = useQuery({
    queryKey: ['admin', 'learners', search, page],
    queryFn: () => adminAPI.getLearners(search, page).then((r) => r.data),
  })

  const configMutation = useMutation({
    mutationFn: adminAPI.updateConfig,
    onSuccess: () => toast.success('Agent config updated'),
    onError: () => toast.error('Could not update config'),
  })

  // Build treemap data from learners
  const topicGapData = [
    { name: 'Python', size: 42, fill: '#7C3AED' },
    { name: 'Machine Learning', size: 35, fill: '#4338CA' },
    { name: 'Statistics', size: 28, fill: '#6366F1' },
    { name: 'Deep Learning', size: 22, fill: '#8B5CF6' },
    { name: 'NLP', size: 18, fill: '#A78BFA' },
    { name: 'Data Viz', size: 15, fill: '#7C3AED' },
    { name: 'SQL', size: 12, fill: '#4338CA' },
    { name: 'Cloud', size: 9, fill: '#6366F1' },
  ]

  const MOOD_EMOJI: Record<string, string> = { POSITIVE: '😊', NEGATIVE: '😟', NEUTRAL: '😐' }

  return (
    <div className="px-6 py-8 max-w-[1400px] mx-auto space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="font-display text-3xl text-paper">Admin Dashboard</h1>
        <div className="flex gap-3">
          <Link to="/admin/models">
            <Button variant="secondary" size="sm">AI Model Status</Button>
          </Link>
        </div>
      </div>

      {/* Skill gap heatmap */}
      <Card>
        <h2 className="text-sm font-medium text-paper/70 uppercase tracking-wider mb-4">Org Skill Gap Heatmap</h2>
        <p className="text-xs text-paper/30 mb-4">Topics by learner count with skill gaps</p>
        <ResponsiveContainer width="100%" height={240}>
          <Treemap
            data={topicGapData}
            dataKey="size"
            aspectRatio={4 / 3}
            stroke="#0A0F1E"
            fill="#7C3AED"
          >
            <Tooltip
              contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8 }}
              formatter={(v) => [v, 'Learners with gaps']}
            />
          </Treemap>
        </ResponsiveContainer>
      </Card>

      {/* Learner table */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-medium text-paper/70 uppercase tracking-wider">Learner Overview</h2>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search learners…"
            className="bg-surface-2 border border-surface-3 rounded-xl px-3 py-2 text-sm text-paper placeholder-paper/30 focus:outline-none focus:ring-2 focus:ring-violet/50 w-56"
          />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-paper/40 uppercase tracking-wider border-b border-surface-2">
                <th className="pb-3 pr-4">Name</th>
                <th className="pb-3 pr-4">Email</th>
                <th className="pb-3 pr-4">Avg. Proficiency</th>
                <th className="pb-3 pr-4">Last Active</th>
                <th className="pb-3">Mood</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-2/50">
              {isLoading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i}>
                    {Array.from({ length: 5 }).map((_, j) => (
                      <td key={j} className="py-3 pr-4"><Skeleton className="h-4 w-24" /></td>
                    ))}
                  </tr>
                ))
              ) : (
                (learners?.items ?? []).map((learner) => (
                  <tr key={learner.id} className="hover:bg-surface-2/30 transition-colors">
                    <td className="py-3 pr-4 font-medium text-paper">{learner.name}</td>
                    <td className="py-3 pr-4 text-paper/60 text-xs">{learner.email}</td>
                    <td className="py-3 pr-4">
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1.5 bg-surface-3 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-violet rounded-full"
                            style={{ width: `${(learner.avg_proficiency / 1000) * 100}%` }}
                          />
                        </div>
                        <span className="text-xs text-paper/60">{Math.round((learner.avg_proficiency / 1000) * 100)}%</span>
                      </div>
                    </td>
                    <td className="py-3 pr-4 text-xs text-paper/40">
                      {new Date(learner.last_active).toLocaleDateString()}
                    </td>
                    <td className="py-3">
                      <span>{MOOD_EMOJI[learner.mood?.toUpperCase() ?? ''] ?? '—'}</span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Agent config */}
      <Card variant="bordered">
        <h2 className="text-sm font-medium text-paper/70 uppercase tracking-wider mb-6">Agent Configuration</h2>
        <div className="space-y-6">
          {[
            { key: 'quiz_frequency' as const, label: 'Quiz Frequency', unit: 'per week', min: 1, max: 14 },
            { key: 'difficulty_ceiling' as const, label: 'Difficulty Ceiling', unit: '%', min: 20, max: 100 },
            { key: 'escalation_threshold' as const, label: 'Escalation Threshold', unit: 'failed attempts', min: 1, max: 10 },
          ].map(({ key, label, unit, min, max }) => (
            <div key={key}>
              <div className="flex justify-between text-sm mb-2">
                <span className="text-paper/70">{label}</span>
                <span className="text-violet-light font-medium">{config[key]} {unit}</span>
              </div>
              <input
                type="range" min={min} max={max}
                value={config[key]}
                onChange={(e) => setConfig((c) => ({ ...c, [key]: Number(e.target.value) }))}
                className="w-full accent-violet h-2 rounded-full"
              />
            </div>
          ))}
          <Button
            onClick={() => configMutation.mutate(config)}
            isLoading={configMutation.isPending}
          >
            Save Agent Config
          </Button>
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
      setTesting(null)
    }
  }

  return (
    <div className="px-6 py-8 max-w-[1400px] mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-3xl text-paper">AI Model Status</h1>
          <p className="text-paper/50 text-sm mt-1">Live status of all inference models</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {Object.entries(HF_MODELS).map(([key, modelId]) => {
          const status = liveStatus?.[key] ?? hfModels[key]
          const tokens = tokenUsage[key] ?? 0
          const statusBadgeVariant =
            status?.status === 'ok' ? 'emerald' :
            status?.status === 'loading' ? 'amber' : 'rose'

          return (
            <motion.div
              key={key}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Object.keys(HF_MODELS).indexOf(key) * 0.05 }}
            >
              <Card>
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <p className="text-xs text-paper/40 uppercase tracking-wider mb-1">{key.replace(/_/g, ' ')}</p>
                    <a
                      href={`#`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-violet-light hover:underline font-mono"
                    >
                      {modelId}
                    </a>
                  </div>
                  <Badge variant={statusBadgeVariant} dot glow={status?.status === 'ok'}>
                    {status?.status ?? 'unknown'}
                  </Badge>
                </div>

                <div className="flex items-center gap-4 text-xs text-paper/40 mb-4">
                  <span>
                    Last used:{' '}
                    {status?.lastUsed
                      ? new Date(status.lastUsed).toLocaleTimeString()
                      : '—'}
                  </span>
                  <span>
                    Latency: {status?.latencyMs != null ? `${status.latencyMs}ms` : '—'}
                  </span>
                  <span>Tokens: {tokens.toLocaleString()}</span>
                </div>

                <Button
                  size="sm"
                  variant="outline"
                  isLoading={testing === key}
                  onClick={() => handleTest(key)}
                >
                  Test Model
                </Button>

                {testResults[key] && (
                  <pre className="mt-3 text-[10px] bg-surface-1 border border-surface-2 rounded-xl p-3 overflow-x-auto text-emerald max-h-32">
                    {JSON.stringify(testResults[key], null, 2)}
                  </pre>
                )}
              </Card>
            </motion.div>
          )
        })}
      </div>
    </div>
  )
}

export default function AdminPage() {
  return (
    <PageWrapper>
      <Routes>
        <Route index element={<AdminOverview />} />
        <Route path="models" element={<HFModelsPanel />} />
        <Route path="*" element={<Navigate to="/admin" replace />} />
      </Routes>
    </PageWrapper>
  )
}

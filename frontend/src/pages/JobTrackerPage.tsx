import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import { AgentTimeline } from '@/components/ui/AgentTimeline'
import { useAgentTimeline } from '@/hooks/useAgentTimeline'
import {
  jobsAPI, quizAPI, streamSSE,
  type JobApplication, type JobStage, type JDAnalysis, type JobRecommendation,
} from '@/lib/api'

const STAGES: { id: JobStage; label: string }[] = [
  { id: 'saved', label: 'Saved' },
  { id: 'applied', label: 'Applied' },
  { id: 'interview', label: 'Interview' },
  { id: 'offer', label: 'Offer' },
  { id: 'rejected', label: 'Rejected' },
]

function readinessColor(score: number): string {
  return score >= 70 ? 'var(--pos)' : score >= 40 ? 'var(--warn)' : 'var(--neg)'
}

function ReadinessBar({ score }: { score: number }) {
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
        <span className="t-xs fg-3">Readiness</span>
        <span className="t-xs mono" style={{ color: readinessColor(score) }}>{Math.round(score)}%</span>
      </div>
      <div style={{ height: 4, background: 'var(--paper-3)', borderRadius: 'var(--r-pill)', overflow: 'hidden' }}>
        <div style={{ width: `${score}%`, height: '100%', background: readinessColor(score), borderRadius: 'var(--r-pill)', transition: 'width 0.6s ease' }} />
      </div>
    </div>
  )
}

export default function JobTrackerPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [adding, setAdding] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => jobsAPI.list().then((r) => r.data.jobs),
    staleTime: 1000 * 30,
  })
  const jobs = data ?? []
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['jobs'] })

  const moveStage = async (job: JobApplication, stage: JobStage) => {
    try {
      await jobsAPI.update(job.id, { stage })
      refresh()
    } catch { toast.error('Could not move the application') }
  }

  const removeJob = async (job: JobApplication) => {
    try { await jobsAPI.remove(job.id); refresh() }
    catch { toast.error('Could not delete the application') }
  }

  const openRecommendation = async (rec: JobRecommendation) => {
    if (rec.type === 'course') {
      navigate('/courses', { state: { prefill: rec.skill } })
      return
    }
    // quiz: generate one on the skill, then open it
    try {
      const { data: quiz } = await quizAPI.generate(rec.skill)
      navigate(`/quiz/${quiz.quiz_id}`)
    } catch { toast.error(`Could not start a quiz on ${rec.skill}`) }
  }

  return (
    <div style={{ padding: '24px 28px', maxWidth: 1400, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: 20, gap: 12, flexWrap: 'wrap' }}>
        <div>
          <div className="caps fg-3">Career Tools</div>
          <h1 className="serif" style={{ fontSize: 36, fontWeight: 400, margin: 0, letterSpacing: '-0.02em' }}>Job Tracker</h1>
          <p className="t-md fg-2" style={{ marginTop: 6 }}>Track applications and see how ready you are for each role — paste a job and the agent maps it to your skills.</p>
        </div>
        {!adding && (
          <Button variant="primary" icon="plus" onClick={() => setAdding(true)}>Add a job</Button>
        )}
      </div>

      {adding && <AddJobPanel onClose={() => setAdding(false)} onSaved={() => { setAdding(false); refresh() }} />}

      {isLoading ? (
        <p className="t-sm fg-3">Loading your applications…</p>
      ) : jobs.length === 0 && !adding ? (
        <Card padding="lg" style={{ textAlign: 'center' }}>
          <Icon name="course" size={26} style={{ color: 'var(--ink-3)', marginBottom: 8 }} />
          <div className="t-lg fg-1" style={{ marginBottom: 4 }}>No applications yet</div>
          <div className="t-sm fg-3" style={{ marginBottom: 14 }}>Paste a job description to see your readiness and skill gaps.</div>
          <Button variant="primary" icon="plus" onClick={() => setAdding(true)}>Add your first job</Button>
        </Card>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: `repeat(${STAGES.length}, minmax(0, 1fr))`, gap: 12, alignItems: 'start' }}>
          {STAGES.map((col) => {
            const colJobs = jobs.filter((j) => j.stage === col.id)
            return (
              <div key={col.id}>
                <div className="caps fg-2" style={{ padding: '0 4px 8px', display: 'flex', justifyContent: 'space-between' }}>
                  <span>{col.label}</span>
                  <span className="fg-3">{colJobs.length}</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {colJobs.map((job) => (
                    <JobCard
                      key={job.id}
                      job={job}
                      onMove={(s) => moveStage(job, s)}
                      onDelete={() => removeJob(job)}
                      onRecommendation={openRecommendation}
                    />
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function JobCard({
  job, onMove, onDelete, onRecommendation,
}: {
  job: JobApplication
  onMove: (stage: JobStage) => void
  onDelete: () => void
  onRecommendation: (rec: JobRecommendation) => void
}) {
  const [open, setOpen] = useState(false)
  const topGaps = job.skill_gaps.filter((g) => g.status !== 'have').slice(0, 3)

  return (
    <Card padding="sm" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
        <div style={{ minWidth: 0 }}>
          <div className="t-sm fg-0" style={{ fontWeight: 500, lineHeight: 1.3 }}>{job.role || 'Untitled role'}</div>
          {job.company && <div className="t-xs fg-3">{job.company}{job.seniority ? ` · ${job.seniority}` : ''}</div>}
        </div>
        <button onClick={onDelete} title="Delete" aria-label="Delete application" style={{ background: 'none', border: 0, color: 'var(--ink-3)', cursor: 'pointer', padding: 2, height: 'fit-content' }}>
          <Icon name="trash" size={13} />
        </button>
      </div>

      <ReadinessBar score={job.readiness_score} />

      {topGaps.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {topGaps.map((g) => (
            <span key={g.skill} className="t-xs" style={{ padding: '1px 6px', borderRadius: 'var(--r-pill)', background: 'var(--paper-2)', border: '1px solid var(--line-1)', color: g.status === 'missing' ? 'var(--neg)' : 'var(--warn)' }}>
              {g.skill}
            </span>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
        <select
          value={job.stage}
          onChange={(e) => onMove(e.target.value as JobStage)}
          aria-label="Move stage"
          style={{ flex: 1, fontSize: 12, padding: '3px 6px', borderRadius: 'var(--r-1)', background: 'var(--paper-2)', border: '1px solid var(--line-1)', color: 'var(--ink-1)', fontFamily: 'inherit' }}
        >
          {STAGES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
        </select>
        {(job.recommendations.length > 0 || job.skill_gaps.length > 0) && (
          <Button size="xs" variant="ghost" onClick={() => setOpen((o) => !o)}>{open ? 'Hide' : 'Gaps'}</Button>
        )}
      </div>

      {open && (
        <div style={{ borderTop: '1px solid var(--line-1)', paddingTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {job.recommendations.length === 0 && <span className="t-xs fg-3">You're matched on all detected skills 🎉</span>}
          {job.recommendations.map((rec, i) => (
            <button
              key={i}
              onClick={() => onRecommendation(rec)}
              className="t-xs"
              style={{ display: 'flex', alignItems: 'center', gap: 6, textAlign: 'left', background: 'none', border: 0, color: 'var(--accent)', cursor: 'pointer', fontFamily: 'inherit', padding: 0 }}
            >
              <Icon name={rec.type === 'quiz' ? 'quiz' : 'course'} size={11} />
              {rec.label}
            </button>
          ))}
        </div>
      )}
    </Card>
  )
}

function AddJobPanel({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [jd, setJd] = useState('')
  const [analyzing, setAnalyzing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [analysis, setAnalysis] = useState<JDAnalysis | null>(null)
  const { steps, applyStep, reset } = useAgentTimeline()

  const analyze = async () => {
    if (jd.trim().length < 20) { toast.error('Paste a fuller job description (at least a sentence or two).'); return }
    setAnalyzing(true)
    setAnalysis(null)
    reset()
    let result: JDAnalysis | null = null
    try {
      await streamSSE('/jobs/analyze/stream', { jd_text: jd.trim() }, (event) => {
        if (event.type === 'step') {
          applyStep(event as unknown as { id: string; label: string; status: 'active' | 'done' | 'error' })
        } else if (event.type === 'action' && event.kind === 'jd_analyzed') {
          result = event.payload as JDAnalysis
        } else if (event.type === 'error') {
          toast.error(String(event.message ?? 'Could not analyze the job'))
        }
      })
      const r = result as JDAnalysis | null
      if (r) setAnalysis(r)
      else toast.error('Could not analyze the job. Try again.')
    } catch { toast.error('Could not analyze the job. Try again.') }
    finally { setAnalyzing(false) }
  }

  const save = async () => {
    if (!analysis) return
    setSaving(true)
    try {
      await jobsAPI.create({
        company: analysis.company,
        role: analysis.role,
        seniority: analysis.seniority,
        required_skills: analysis.required_skills,
        readiness_score: analysis.readiness_score,
        skill_gaps: analysis.skill_gaps,
        recommendations: analysis.recommendations,
        source_jd: analysis.source_jd,
        stage: 'saved',
      })
      toast.success('Added to your board')
      onSaved()
    } catch { toast.error('Could not save the application') }
    finally { setSaving(false) }
  }

  return (
    <Card padding="md" style={{ marginBottom: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <div className="caps fg-2">Paste a job description</div>
        <button onClick={onClose} aria-label="Close" style={{ background: 'none', border: 0, color: 'var(--ink-3)', cursor: 'pointer' }}><Icon name="x" size={14} /></button>
      </div>

      <textarea
        value={jd}
        onChange={(e) => setJd(e.target.value)}
        disabled={analyzing}
        placeholder="Paste the full job description here…"
        rows={6}
        style={{ width: '100%', resize: 'vertical', padding: 10, borderRadius: 'var(--r-2)', background: 'var(--paper-0)', border: '1px solid var(--line-1)', color: 'var(--ink-0)', fontFamily: 'inherit', fontSize: 13, lineHeight: 1.5 }}
      />

      <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
        <Button variant="primary" icon="sparkle" onClick={analyze} loading={analyzing} disabled={analyzing}>Analyze fit</Button>
        {analysis && <Button variant="outline" icon="check" onClick={save} loading={saving}>Save to board</Button>}
      </div>

      {analyzing && steps.length > 0 && (
        <div style={{ marginTop: 14, padding: 14, background: 'var(--paper-2)', borderRadius: 'var(--r-2)' }}>
          <AgentTimeline steps={steps} className="fade-in" />
        </div>
      )}

      {analysis && (
        <div className="fade-in" style={{ marginTop: 14, padding: 14, background: 'var(--paper-2)', borderRadius: 'var(--r-2)', display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div>
            <div className="t-md fg-0" style={{ fontWeight: 500 }}>{analysis.role || 'Role'}{analysis.company ? ` · ${analysis.company}` : ''}</div>
            {analysis.seniority && <div className="t-xs fg-3">{analysis.seniority}</div>}
          </div>
          <ReadinessBar score={analysis.readiness_score} />
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {analysis.skill_gaps.map((g) => (
              <span key={g.skill} className="t-xs" style={{ padding: '1px 6px', borderRadius: 'var(--r-pill)', background: 'var(--paper-1)', border: '1px solid var(--line-1)', color: g.status === 'have' ? 'var(--pos)' : g.status === 'partial' ? 'var(--warn)' : 'var(--neg)' }}>
                {g.skill}
              </span>
            ))}
          </div>
        </div>
      )}
    </Card>
  )
}

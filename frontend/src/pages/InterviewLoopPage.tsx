import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Icon } from '@/components/ui/Icon'
import { ReasoningStream } from '@/components/agents/ReasoningStream'
import { useAgentTimeline } from '@/hooks/useAgentTimeline'
import { loopsAPI, streamSSE, type InterviewRound, type RoundStatus } from '@/lib/api'

const STATUS_TONE: Record<RoundStatus, 'pos' | 'warn' | 'neutral' | 'outline'> = {
  passed: 'pos',
  failed: 'warn',
  in_progress: 'warn',
  available: 'neutral',
  locked: 'outline',
}

const STATUS_LABEL: Record<RoundStatus, string> = {
  passed: 'Cleared',
  failed: 'Below bar',
  in_progress: 'In progress',
  available: 'Ready',
  locked: 'Locked',
}

const KIND_ICON: Record<string, string> = {
  screen: 'user',
  coding: 'code',
  system_design: 'layers',
  behavioral: 'message',
}

export default function InterviewLoopPage() {
  const { loopId } = useParams<{ loopId: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [debriefing, setDebriefing] = useState(false)
  const { steps, applyStep, reset: resetSteps } = useAgentTimeline()

  const { data: loop, isLoading, isError, refetch } = useQuery({
    queryKey: ['loop', loopId],
    queryFn: () => loopsAPI.get(loopId!).then((r) => r.data),
    enabled: !!loopId,
    staleTime: 1000 * 30,
  })

  const retry = useMutation({
    mutationFn: (roundKey: string) => loopsAPI.retryRound(loopId!, roundKey),
    onSuccess: () => {
      toast.success('Round reset — the next attempt will ask different questions')
      qc.invalidateQueries({ queryKey: ['loop', loopId] })
    },
    onError: () => toast.error('Could not reset that round'),
  })

  const runDebrief = async () => {
    if (!loopId) return
    setDebriefing(true)
    resetSteps()
    try {
      await streamSSE(`/loops/${loopId}/debrief/stream`, {}, (event) => {
        if (event.type === 'step') {
          applyStep(event as unknown as { id: string; label: string; status: 'active' | 'done' | 'error' })
        } else if (event.type === 'error') {
          toast.error(String(event.message ?? 'Debrief failed'))
        }
      })
      await qc.invalidateQueries({ queryKey: ['loop', loopId] })
    } catch {
      toast.error('Could not write your debrief')
    } finally {
      setDebriefing(false)
    }
  }

  if (isLoading) return <p className="t-sm fg-3" style={{ padding: 28 }}>Loading your interview loop…</p>

  if (isError || !loop) {
    return (
      <div style={{ textAlign: 'center', padding: '48px 0' }}>
        <p className="t-sm fg-2" style={{ marginBottom: 8 }}>Could not load this interview loop.</p>
        <button onClick={() => refetch()} style={{ fontSize: 13, color: 'var(--accent)', background: 'none', border: 0, cursor: 'pointer', fontFamily: 'inherit' }}>Retry →</button>
      </div>
    )
  }

  const resolved = loop.rounds.every((r) => r.status === 'passed' || r.status === 'failed')
  const cleared = loop.rounds.filter((r) => r.status === 'passed').length

  return (
    <div style={{ padding: '24px 28px', maxWidth: 900, margin: '0 auto' }}>
      {/* ── Header ── */}
      <button
        onClick={() => navigate('/tracker')}
        style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--ink-2)', background: 'none', border: 0, cursor: 'pointer', fontSize: 13, fontFamily: 'inherit', marginBottom: 12 }}
      >
        <Icon name="arrow-left" size={13} /> Job Tracker
      </button>

      <div className="eyebrow">Interview loop</div>
      <h1 className="display" style={{ fontSize: 34, fontWeight: 600, margin: 0, letterSpacing: '-0.03em' }}>
        {loop.role || 'Interview'} · {loop.company || 'Company'}
      </h1>
      <p className="t-md fg-2" style={{ marginTop: 6 }}>
        {loop.process_summary || 'Practice the rounds this role is likely to put you through.'}
      </p>

      <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        {loop.seniority && <Badge tone="outline" size="xs">{loop.seniority}</Badge>}
        <span className="t-xs fg-3">
          {cleared} of {loop.rounds.length} rounds cleared
        </span>
      </div>

      {/* ── Round ladder ── */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 22 }}>
        {loop.rounds.map((round) => (
          <RoundCard
            key={round.key}
            round={round}
            onStart={() => navigate(`/loops/${loop.loop_id}/rounds/${round.key}`)}
            onRetry={() => retry.mutate(round.key)}
            retrying={retry.isPending && retry.variables === round.key}
          />
        ))}
      </div>

      {/* ── Debrief ── */}
      <div style={{ marginTop: 24 }}>
        {debriefing && (
          <ReasoningStream
            segments={steps.map((s) => ({ id: s.id, text: s.label, status: s.status }))}
            style={{ width: '100%', marginBottom: 14 }}
          />
        )}

        {loop.debrief ? (
          <Card padding="md" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div className="caps fg-3" style={{ fontSize: 10 }}>Debrief</div>
            <p className="t-md fg-0" style={{ margin: 0, lineHeight: 1.5 }}>{loop.debrief.verdict}</p>

            {loop.debrief.strengths.length > 0 && (
              <DebriefList label="What you showed" tone="pos" items={loop.debrief.strengths} />
            )}
            {loop.debrief.gaps.length > 0 && (
              <DebriefList label="What held you back" tone="warn" items={loop.debrief.gaps} />
            )}

            {loop.debrief.focus_next && (
              <div style={{ borderTop: '1px solid var(--line-1)', paddingTop: 10 }}>
                <div className="caps fg-3" style={{ fontSize: 10, marginBottom: 4 }}>Work on this next</div>
                <p className="t-sm fg-1" style={{ margin: 0 }}>{loop.debrief.focus_next}</p>
              </div>
            )}
          </Card>
        ) : (
          resolved && (
            <Button variant="signal" icon="sparkle" onClick={runDebrief} disabled={debriefing}>
              {debriefing ? 'Writing your debrief…' : 'Get your debrief'}
            </Button>
          )
        )}
      </div>
    </div>
  )
}

function DebriefList({ label, tone, items }: { label: string; tone: 'pos' | 'warn'; items: string[] }) {
  return (
    <div>
      <div className="caps fg-3" style={{ fontSize: 10, marginBottom: 4 }}>{label}</div>
      <ul style={{ margin: 0, paddingLeft: 16, display: 'flex', flexDirection: 'column', gap: 3 }}>
        {items.map((item, i) => (
          <li key={i} className="t-sm fg-1" style={{ color: tone === 'pos' ? undefined : 'var(--ink-1)' }}>{item}</li>
        ))}
      </ul>
    </div>
  )
}

interface RoundCardProps {
  round: InterviewRound
  onStart: () => void
  onRetry: () => void
  retrying: boolean
}

function RoundCard({ round, onStart, onRetry, retrying }: RoundCardProps) {
  const locked = round.status === 'locked'
  const graded = round.status === 'passed' || round.status === 'failed'

  return (
    <Card
      padding="sm"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        opacity: locked ? 0.55 : 1,
      }}
    >
      <div style={{
        width: 34, height: 34, borderRadius: 8, flexShrink: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'var(--paper-2)', color: 'var(--ink-2)',
      }}>
        <Icon name={KIND_ICON[round.kind] ?? 'mic'} size={15} />
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span className="t-sm fg-0" style={{ fontWeight: 500 }}>{round.title}</span>
          <Badge tone={STATUS_TONE[round.status]} size="xs">{STATUS_LABEL[round.status]}</Badge>
          {round.attempt > 1 && <span className="t-xs fg-3">attempt {round.attempt}</span>}
        </div>
        <div className="t-xs fg-3" style={{ marginTop: 3 }}>
          {/* The bar is always visible — a score means nothing without the mark it's judged against. */}
          {graded && round.score != null
            ? <>Scored {round.score.toFixed(1)} against a bar of {round.bar.toFixed(1)}</>
            : <>Bar for this round: {round.bar.toFixed(1)}/10</>}
          {round.focus_skills.length > 0 && <> · {round.focus_skills.slice(0, 3).join(', ')}</>}
        </div>
      </div>

      {!locked && (
        <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
          {graded ? (
            <>
              {/* The transcript, per-answer feedback and scoring matrix are the evidence the
                  learner earned — "Try again" alone threw it away. */}
              {round.interview_id && (
                <Button size="sm" variant="ghost" onClick={onStart}>Review</Button>
              )}
              <Button size="sm" variant="outline" onClick={onRetry} disabled={retrying}>
                {retrying ? 'Resetting…' : 'Try again'}
              </Button>
            </>
          ) : (
            <Button size="sm" variant="signal" icon="mic" onClick={onStart}>
              {round.status === 'in_progress' ? 'Resume' : 'Start'}
            </Button>
          )}
        </div>
      )}
    </Card>
  )
}

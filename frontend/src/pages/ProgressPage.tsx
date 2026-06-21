import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { progressAPI } from '@/lib/api'
import { useLearnerStore } from '@/stores/learnerStore'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import { Skeleton } from '@/components/ui/Skeleton'

const MASTERY_THRESHOLD = 700
const MOOD_EMOJI: Record<string, string> = { POSITIVE: '😊', NEGATIVE: '😟', NEUTRAL: '😐' }
const MOOD_TONE: Record<string, 'pos' | 'neg' | 'neutral'> = { POSITIVE: 'pos', NEGATIVE: 'neg', NEUTRAL: 'neutral' }

function eloToPercent(elo: number) {
  return Math.min(100, Math.max(0, elo / 10))
}

function eloBadge(elo: number): { label: string; tone: 'pos' | 'neutral' | 'warn' } {
  if (elo >= MASTERY_THRESHOLD) return { label: 'mastered', tone: 'pos' }
  if (elo >= 500) return { label: 'mid', tone: 'neutral' }
  return { label: 'needs work', tone: 'warn' }
}

function buildHeatmap(history: Array<{ recorded_at: string }>, days = 35) {
  const counts: Record<string, number> = {}
  for (const h of history) {
    const day = h.recorded_at?.slice(0, 10)
    if (day) counts[day] = (counts[day] ?? 0) + 1
  }
  const result: Array<{ date: string; count: number }> = []
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    const key = d.toISOString().slice(0, 10)
    result.push({ date: key, count: counts[key] ?? 0 })
  }
  return result
}

function HeatmapCell({ count }: { count: number }) {
  const alpha = count === 0 ? 0 : Math.min(1, 0.25 + count * 0.25)
  return (
    <div
      title={count > 0 ? `${count} activity` : 'No activity'}
      style={{
        aspectRatio: '1',
        borderRadius: 3,
        background: count > 0
          ? `color-mix(in srgb, var(--accent) ${Math.round(alpha * 100)}%, var(--paper-3))`
          : 'var(--paper-2)',
        border: '1px solid var(--line-1)',
      }}
    />
  )
}

export default function ProgressPage() {
  const navigate = useNavigate()
  const { xp: storedXp, streak: storedStreak, topicProficiency: storedProficiency } = useLearnerStore()

  const { data: progress, isLoading: loadingProgress } = useQuery({
    queryKey: ['progress'],
    queryFn: () => progressAPI.get().then((r) => r.data),
    staleTime: 60_000,
  })

  const { data: dueTopicsData, isLoading: loadingDue } = useQuery({
    queryKey: ['progress', 'due-topics'],
    queryFn: () => progressAPI.dueTopics().then((r) => r.data),
    staleTime: 60_000,
  })

  // Use API data when available, fall back to local store
  const proficiency = progress?.topic_proficiency ?? storedProficiency
  const xp = progress?.xp ?? storedXp
  const streak = progress?.streak ?? storedStreak
  const totalMinutes = progress?.total_study_minutes ?? 0
  const quizAccuracy = progress?.quiz_accuracy ?? 0
  const doubtsResolved = progress?.doubts_resolved ?? 0
  const moodTimeline = progress?.mood_timeline ?? []
  const history = progress?.history ?? []

  const skills = useMemo(() => {
    const entries = Object.entries(proficiency)
    if (entries.length === 0) return []
    return entries
      .map(([topic, elo]) => ({ topic, elo }))
      .sort((a, b) => b.elo - a.elo)
  }, [proficiency])

  const masteredCount = skills.filter((s) => s.elo >= MASTERY_THRESHOLD).length
  const masteryPct = skills.length > 0 ? Math.round((masteredCount / skills.length) * 100) : 0

  const heatmap = useMemo(() => buildHeatmap(history, 35), [history])

  const dueTopics = dueTopicsData?.due_topics ?? []
  const urgentTopics = dueTopics.filter((t) => t.is_due).slice(0, 5)

  const recentMoods = moodTimeline.slice(-5).reverse()

  const statsLoading = loadingProgress

  return (
    <div style={{ padding: '24px 28px', maxWidth: 1240, margin: '0 auto' }}>
      <div style={{ marginBottom: 18, display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <div>
          <div className="caps fg-3">Live Progress · Updated now</div>
          <h1 className="serif" style={{ fontSize: 36, fontWeight: 400, margin: 0, letterSpacing: '-0.02em' }}>Progress</h1>
        </div>
        <Button
          size="sm"
          variant="ghost"
          icon="download"
          onClick={async () => {
            try {
              const { data } = await progressAPI.downloadReport()
              const url = URL.createObjectURL(data as Blob)
              const a = document.createElement('a')
              a.href = url
              a.download = 'progress-report.json'
              a.click()
              URL.revokeObjectURL(url)
            } catch { /* non-critical */ }
          }}
        >
          Export
        </Button>
      </div>

      {/* Stat strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)', overflow: 'hidden', background: 'var(--paper-1)', marginBottom: 16 }}>
        {[
          { l: 'XP earned',    v: statsLoading ? null : xp.toLocaleString(),                      s: 'lifetime' },
          { l: 'Sub-skills',   v: statsLoading ? null : String(skills.length),                    s: `${masteredCount} mastered` },
          { l: 'Quiz accuracy',v: statsLoading ? null : `${Math.round(quizAccuracy * 100)}%`,     s: 'avg score' },
          { l: 'Doubts',       v: statsLoading ? null : String(doubtsResolved),                   s: 'resolved' },
          { l: 'Time',         v: statsLoading ? null : totalMinutes >= 60 ? `${Math.floor(totalMinutes / 60)}h ${totalMinutes % 60}m` : `${totalMinutes}m`, s: 'total studied' },
          { l: 'Mastery',      v: statsLoading ? null : `${masteryPct}%`,                         s: `${masteredCount}/${skills.length} topics` },
        ].map((s, i) => (
          <div key={i} style={{ padding: 14, borderRight: i < 5 ? '1px solid var(--line-1)' : 'none' }}>
            <div className="caps fg-2">{s.l}</div>
            {s.v == null
              ? <div style={{ height: 32, marginTop: 2 }}><Skeleton style={{ height: 28, width: 60, borderRadius: 4 }} /></div>
              : <div className="serif" style={{ fontSize: 26, color: 'var(--ink-0)', marginTop: 2 }}>{s.v}</div>
            }
            <div className="t-xs fg-3">{s.s}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 14 }}>
        {/* Skill mastery */}
        <Card padding="md">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <span className="caps fg-2">
              Skill mastery · {loadingProgress ? '…' : `${skills.length} sub-skills`}
            </span>
            {!loadingProgress && skills.length === 0 && (
              <span className="t-xs fg-3">Complete a quiz to see Elo data</span>
            )}
          </div>

          {loadingProgress && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {[1, 2, 3, 4].map((i) => <Skeleton key={i} style={{ height: 36 }} />)}
            </div>
          )}

          {!loadingProgress && skills.length === 0 && (
            <div style={{ padding: '24px 0', textAlign: 'center' }}>
              <Icon name="book" size={24} style={{ color: 'var(--ink-3)', marginBottom: 8 }} />
              <div className="t-sm fg-3">No proficiency data yet.</div>
              <Button size="sm" variant="ghost" style={{ marginTop: 8 }} onClick={() => navigate('/quiz/new')}>
                Take a quiz
              </Button>
            </div>
          )}

          {!loadingProgress && skills.map((s, i) => {
            const pct = eloToPercent(s.elo)
            const badge = eloBadge(s.elo)
            return (
              <div
                key={s.topic}
                style={{
                  padding: '8px 0',
                  borderTop: i ? '1px solid var(--line-1)' : 'none',
                  display: 'grid',
                  gridTemplateColumns: '140px 1fr 56px 80px',
                  gap: 12,
                  alignItems: 'center',
                }}
              >
                <span className="t-sm fg-0" style={{ fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={s.topic}>
                  {s.topic}
                </span>
                <div style={{ height: 6, background: 'var(--paper-3)', borderRadius: 'var(--r-pill)', overflow: 'hidden' }}>
                  <div
                    style={{
                      width: `${pct}%`,
                      height: '100%',
                      background: s.elo >= MASTERY_THRESHOLD ? 'var(--pos)' : 'var(--ink-0)',
                      borderRadius: 'var(--r-pill)',
                      transition: 'width 0.6s var(--ease-out)',
                    }}
                  />
                </div>
                <span className="t-sm fg-0 mono" style={{ textAlign: 'right' }}>{Math.round(s.elo)}</span>
                <Badge size="xs" tone={badge.tone}>{badge.label}</Badge>
              </div>
            )
          })}
        </Card>

        {/* Right column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Activity heatmap */}
          <Card padding="md">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <span className="caps fg-2">Activity · last 35 days</span>
              {loadingProgress && <Skeleton style={{ height: 14, width: 80 }} />}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 4 }}>
              {heatmap.map((d) => <HeatmapCell key={d.date} count={d.count} />)}
            </div>
            <div className="t-xs fg-3" style={{ marginTop: 8 }}>
              {streak > 0 ? `${streak}-day streak` : 'Start a session to build your streak'}
            </div>
          </Card>

          {/* Due topics (spaced repetition) */}
          <Card padding="md">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <span className="caps fg-2">Review reminders</span>
              {loadingDue && <Skeleton style={{ height: 14, width: 40 }} />}
            </div>
            {!loadingDue && urgentTopics.length === 0 && (
              <div className="t-sm fg-3" style={{ padding: '8px 0' }}>
                {dueTopics.length === 0 ? 'No topics tracked yet.' : 'All topics are up to date.'}
              </div>
            )}
            {urgentTopics.map((t, i) => (
              <div
                key={t.topic}
                style={{
                  padding: '7px 0',
                  borderTop: i ? '1px solid var(--line-1)' : 'none',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                }}
              >
                <Icon
                  name={t.urgency > 0.7 ? 'arrowDR' : 'arrowUR'}
                  size={11}
                  style={{ color: t.urgency > 0.7 ? 'var(--neg)' : 'var(--warn)', flexShrink: 0 }}
                />
                <span className="t-sm fg-1" style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {t.topic}
                </span>
                <span className="t-xs fg-3 mono">{Math.round(t.elo)}</span>
                <Button
                  size="xs"
                  variant="ghost"
                  onClick={() => navigate(`/quiz/new?topic=${encodeURIComponent(t.topic)}`)}
                >
                  Review
                </Button>
              </div>
            ))}
          </Card>

          {/* Mood insights */}
          <Card padding="md">
            <div className="caps fg-2" style={{ marginBottom: 6 }}>Mood insights</div>
            {loadingProgress && <Skeleton style={{ height: 64 }} />}
            {!loadingProgress && recentMoods.length === 0 && (
              <div className="t-sm fg-3">
                Mood is tracked from quiz reflections. Complete a quiz and leave a reflection to see trends here.
              </div>
            )}
            {recentMoods.map((m, i) => (
              <div
                key={m.session_id}
                style={{
                  padding: '6px 0',
                  borderTop: i ? '1px solid var(--line-1)' : 'none',
                  display: 'flex',
                  gap: 8,
                  alignItems: 'center',
                }}
              >
                <span style={{ fontSize: 13 }}>{MOOD_EMOJI[m.mood?.toUpperCase()] ?? '💬'}</span>
                <Badge size="xs" tone={MOOD_TONE[m.mood?.toUpperCase()] ?? 'neutral'}>
                  {m.mood?.toLowerCase() ?? 'unknown'}
                </Badge>
                <span className="t-xs fg-3" style={{ flex: 1, textAlign: 'right' }}>
                  {m.date ? new Date(m.date).toLocaleDateString() : '—'}
                </span>
              </div>
            ))}
          </Card>
        </div>
      </div>
    </div>
  )
}

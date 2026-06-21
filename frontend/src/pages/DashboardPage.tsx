import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import toast from 'react-hot-toast'
import { contentAPI, doubtsAPI, quizAPI, progressAPI, leaderboardAPI } from '@/lib/api'
import { useLearnerStore } from '@/stores/learnerStore'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import { ValueBar } from '@/components/ui/Progress'

function Stat({ label, value, change, sub, icon }: { label: string; value: string; change?: string; sub?: string; icon?: string }) {
  return (
    <div style={{ flex: 1, padding: 14, background: 'var(--paper-1)', border: '1px solid var(--line-1)', borderRadius: 'var(--r-3)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <span className="caps" style={{ color: 'var(--ink-2)' }}>{label}</span>
        {icon && <Icon name={icon} size={12} style={{ color: 'var(--ink-3)' }} />}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <span className="serif" style={{ fontSize: 28, color: 'var(--ink-0)', letterSpacing: '-0.02em' }}>{value}</span>
        {change && <span className="t-xs" style={{ color: change.startsWith('+') ? 'var(--pos)' : 'var(--neg)', fontWeight: 500 }}>{change}</span>}
      </div>
      {sub && <div className="t-xs fg-3" style={{ marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function SkillBar({ name, value }: { name: string; value: number }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0' }}>
      <span className="t-sm fg-1" style={{ width: 110, fontWeight: 500 }}>{name}</span>
      <div style={{ flex: 1, height: 4, background: 'var(--paper-3)', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ width: `${value * 100}%`, height: '100%', background: 'var(--ink-0)', borderRadius: 2 }} />
      </div>
      <span className="t-xs fg-3 mono" style={{ width: 30, textAlign: 'right' }}>{Math.round(value * 100)}</span>
    </div>
  )
}

function HeatCell({ v }: { v: number }) {
  const colors = ['transparent', '#E2DBC8', '#C6A988', '#A8553A', '#7E3F2A']
  return <div style={{ width: 10, height: 10, background: colors[v] || colors[0], borderRadius: 1.5, border: v === 0 ? '1px solid var(--line-1)' : 'none' }} />
}

const HEATMAP = Array.from({ length: 26 }, () => Array.from({ length: 7 }, () => Math.floor(Math.random() * 5)))

export default function DashboardPage() {
  const navigate = useNavigate()
  const { name, xp, streak, topicProficiency } = useLearnerStore()
  const [isGeneratingQuiz, setIsGeneratingQuiz] = useState(false)
  const [loadingModuleId, setLoadingModuleId] = useState<string | null>(null)

  const { data: contentData, isLoading: contentLoading } = useQuery({
    queryKey: ['content', 'feed', {}],
    queryFn: () => contentAPI.list({ limit: 6 }).then((r) => r.data),
    staleTime: 1000 * 60 * 2,   // content list: 2 min
    gcTime: 1000 * 60 * 10,
  })

  const { data: sessionsData } = useQuery({
    queryKey: ['doubts', 'sessions'],
    queryFn: () => doubtsAPI.getSessions().then((r) => r.data),
    staleTime: 1000 * 30,        // doubt sessions: 30 s
    gcTime: 1000 * 60 * 5,
  })

  const { data: dueTopicsData } = useQuery({
    queryKey: ['progress', 'due-topics'],
    queryFn: () => progressAPI.dueTopics().then((r) => r.data),
    staleTime: 1000 * 60 * 5,
  })

  const { data: leaderboardData } = useQuery({
    queryKey: ['leaderboard'],
    queryFn: () => leaderboardAPI.get().then((r) => r.data),
    staleTime: 1000 * 60 * 2,   // leaderboard: 2 min
    gcTime: 1000 * 60 * 10,
  })

  const handleStartQuiz = async () => {
    setIsGeneratingQuiz(true)
    try {
      const dueTopic = dueTopics[0]?.topic
      const topic = dueTopic ?? Object.keys(topicProficiency)[0] ?? 'Python'
      const { data } = await quizAPI.generate(topic)
      navigate(`/quiz/${data.quiz_id}`)
    } catch {
      toast.error('Could not generate quiz')
    } finally {
      setIsGeneratingQuiz(false)
    }
  }

  const items = contentData?.items ?? []
  const sessions = sessionsData ?? []
  const dueTopics = (dueTopicsData?.due_topics ?? []).filter((t) => t.is_due).slice(0, 5)
  const board = leaderboardData?.board ?? []
  const yourRank = leaderboardData?.your_rank

  return (
    <div style={{ padding: '24px 28px', maxWidth: 1240, margin: '0 auto' }}>
      {/* Greeting */}
      <div style={{ marginBottom: 20, display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between' }}>
        <div>
          <div className="caps" style={{ color: 'var(--ink-3)', marginBottom: 4 }}>
            {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
          </div>
          <h1 className="serif" style={{ fontSize: 36, fontWeight: 400, margin: 0, color: 'var(--ink-0)', letterSpacing: '-0.02em' }}>
            Good {new Date().getHours() < 12 ? 'morning' : 'afternoon'},{' '}
            <span style={{ fontStyle: 'italic', color: 'var(--accent)' }}>{name || 'Learner'}</span>.
          </h1>
          <p className="t-md fg-2" style={{ marginTop: 4 }}>You're on a {streak}-day streak. Three things on the docket today.</p>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <Button size="sm" variant="ghost" icon="calendar">Schedule</Button>
          <Button size="sm" variant="accent" icon="sparkle" onClick={() => navigate('/assistant')}>Ask Atelier</Button>
        </div>
      </div>

      {/* Stat row */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
        <Stat label="XP" value={xp.toLocaleString()} change="+120 today" icon="bolt" />
        <Stat label="Streak" value={String(streak)} sub="days · keep it up!" icon="flame" />
        <Stat label="Mastery" value="48%" change="+4% this week" icon="target" />
        <Stat label="Time" value="42h" sub="this month" icon="clock" />
        <Stat label="Doubts" value={String(sessions.length || 38)} change="+6" icon="chat" />
      </div>

      {/* Main grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 16 }}>
        {/* Column 1 */}
        <div>
          {/* Curriculum suggestion */}
          <Card accent padding="md" style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
              <div style={{ width: 32, height: 32, borderRadius: 'var(--r-2)', background: 'var(--accent)', color: '#fff', display: 'grid', placeItems: 'center', flexShrink: 0 }}>
                <Icon name="sparkle" size={16} />
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span className="caps" style={{ color: 'var(--accent)' }}>Learning Path</span>
                  <span className="t-xs fg-3">· just now</span>
                </div>
                <div className="t-md fg-0" style={{ fontWeight: 500, marginTop: 4 }}>Your derivative recall is dipping. A 9-min refresher will protect this week's progress.</div>
                <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                  <Button size="sm" variant="accent" iconRight="arrow" onClick={() => navigate('/learn')}>Take refresher</Button>
                  <Button size="sm" variant="ghost">Snooze 1 day</Button>
                </div>
              </div>
            </div>
          </Card>

          {/* Today's feed */}
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 8 }}>
            <span className="caps" style={{ color: 'var(--ink-2)' }}>Today's feed · {items.length} modules</span>
            <a className="t-sm fg-2" style={{ cursor: 'pointer' }} onClick={() => navigate('/learn')}>Open feed →</a>
          </div>

          {contentLoading ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {[0, 1, 2].map((i) => <div key={i} className="skel" style={{ height: 48, borderRadius: 'var(--r-2)', marginBottom: 1 }} />)}
            </div>
          ) : (
            <Card padding="none">
              {items.slice(0, 5).map((m: any, i: number) => {
                const isOpening = loadingModuleId === m.id
                return (
                  <div
                    key={m.id}
                    style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 12, borderTop: i ? '1px solid var(--line-1)' : 'none', cursor: 'pointer', transition: 'background 0.1s' }}
                    onClick={() => {
                      setLoadingModuleId(m.id)
                      navigate(`/learn/${m.id}`)
                    }}
                    onMouseEnter={(e) => { if (!isOpening) e.currentTarget.style.background = 'var(--paper-2)' }}
                    onMouseLeave={(e) => { if (!isOpening) e.currentTarget.style.background = 'transparent' }}
                  >
                    <div style={{ width: 28, height: 28, borderRadius: 'var(--r-2)', background: isOpening ? 'color-mix(in srgb, var(--accent) 12%, var(--paper-2))' : 'var(--paper-3)', display: 'grid', placeItems: 'center', transition: 'background 0.2s', flexShrink: 0 }}>
                      {isOpening ? (
                        <Icon name="refresh" size={13} style={{ color: 'var(--accent)', animation: 'spin 0.8s linear infinite' }} />
                      ) : (
                        <Icon name={m.content_type === 'video' ? 'play' : m.content_type === 'exercise' ? 'code' : 'book'} size={13} style={{ color: 'var(--ink-1)' }} />
                      )}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span className="t-md fg-0" style={{ fontWeight: 500 }}>{m.title}</span>
                        {m.is_ai_recommended && <Badge tone="accent" size="xs">AI Pick</Badge>}
                      </div>
                      <div className="t-xs fg-3" style={{ marginTop: 2 }}>{isOpening ? 'Loading your content…' : `${m.topic} · ${m.estimated_minutes}m`}</div>
                    </div>
                    <ValueBar value={Math.round((m.difficulty ?? 0.5) * 5)} segments={5} />
                    <Icon name={isOpening ? 'chevR' : 'chevR'} size={14} style={{ color: isOpening ? 'var(--accent)' : 'var(--ink-3)' }} />
                  </div>
                )
              })}
              {items.length === 0 && (
                <div className="t-sm fg-3" style={{ padding: '20px 14px', textAlign: 'center' }}>No content yet — building your learning path…</div>
              )}
            </Card>
          )}

          {/* Recent doubts */}
          <div style={{ marginTop: 20, display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 8 }}>
            <span className="caps" style={{ color: 'var(--ink-2)' }}>Recent doubts</span>
            <a className="t-sm fg-2" style={{ cursor: 'pointer' }} onClick={() => navigate('/doubts')}>All sessions →</a>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10 }}>
            {sessions.slice(0, 4).map((s: any) => (
              <Card key={s.id} hover padding="sm" style={{ cursor: 'pointer' }} onClick={() => navigate('/doubts')}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <Badge size="xs" tone={s.sentiment_mood === 'POSITIVE' ? 'pos' : s.sentiment_mood === 'NEGATIVE' ? 'neg' : 'neutral'} dot>
                    {(s.sentiment_mood ?? 'neutral').toLowerCase()}
                  </Badge>
                  <span className="t-xs fg-3">{new Date(s.started_at).toLocaleDateString()}</span>
                </div>
                <div className="t-sm fg-0" style={{ fontWeight: 500, marginBottom: 2 }}>{s.topic_context ?? 'General question'}</div>
              </Card>
            ))}
          </div>
        </div>

        {/* Column 2 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {/* Skill map */}
          <Card padding="md">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <span className="caps" style={{ color: 'var(--ink-2)' }}>Skill mastery</span>
              <span className="t-xs fg-3 mono">{Object.keys(topicProficiency).length} tracked</span>
            </div>
            {Object.entries(topicProficiency).slice(0, 6).map(([k, v]) => (
              <SkillBar key={k} name={k.slice(0, 14)} value={v / 1000} />
            ))}
            {Object.keys(topicProficiency).length === 0 && (
              <div className="t-xs fg-3" style={{ textAlign: 'center', padding: 8 }}>Tracking your skills…</div>
            )}
            <div className="t-xs fg-3" style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--line-1)', display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--agent-prog)', display: 'inline-block' }} />
              Updated by Progress agent
            </div>
          </Card>

          {/* Activity heatmap */}
          <Card padding="md">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <span className="caps" style={{ color: 'var(--ink-2)' }}>Activity · last 26 weeks</span>
              <span className="t-xs fg-3">{streak} day streak</span>
            </div>
            <div style={{ display: 'flex', gap: 2, overflowX: 'auto' }}>
              {HEATMAP.map((col, i) => (
                <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {col.map((v, j) => <HeatCell key={j} v={v} />)}
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 10, fontSize: 11, color: 'var(--ink-3)' }}>
              <span>Less</span>
              {[0, 1, 2, 3, 4].map((v) => <HeatCell key={v} v={v} />)}
              <span>More</span>
            </div>
          </Card>

          {/* Due for review */}
          <Card padding="none">
            <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--line-1)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span className="caps" style={{ color: 'var(--ink-2)' }}>Due for review</span>
              <Badge size="xs" tone="warn">{dueTopics.length} due</Badge>
            </div>
            {dueTopics.length > 0 ? dueTopics.map((t, i) => (
              <div key={t.topic} style={{ padding: '8px 14px', display: 'flex', alignItems: 'center', gap: 10, borderTop: i ? '1px solid var(--line-1)' : 'none' }}>
                <div className="t-sm fg-0" style={{ fontWeight: 500, flex: 1 }}>{t.topic}</div>
                <span className="t-xs fg-3 mono">Elo {Math.round(t.elo)}</span>
                <Badge size="xs" tone={t.urgency >= 0.8 ? 'neg' : t.urgency >= 0.5 ? 'warn' : 'outline'}>
                  {t.days_since_last_quiz === null ? 'New' : t.urgency >= 0.8 ? 'Urgent' : 'Due'}
                </Badge>
              </div>
            )) : (
              <div className="t-xs fg-3" style={{ padding: '16px 14px', textAlign: 'center' }}>
                {dueTopicsData ? 'All caught up! No reviews due.' : 'Loading due topics…'}
              </div>
            )}
            <div style={{ padding: 10, borderTop: '1px solid var(--line-1)' }}>
              <Button size="sm" variant="primary" full iconRight="arrow" onClick={handleStartQuiz} loading={isGeneratingQuiz}>
                {dueTopics[0] ? `Review ${dueTopics[0].topic}` : 'Start a quiz'}
              </Button>
            </div>
          </Card>

          {/* Leaderboard */}
          <Card padding="none">
            <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--line-1)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span className="caps" style={{ color: 'var(--ink-2)' }}>Leaderboard</span>
              {yourRank && <span className="t-xs fg-3">You're #{yourRank}</span>}
            </div>
            {board.slice(0, 5).map((entry, i) => (
              <div
                key={entry.rank}
                style={{
                  padding: '7px 14px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  borderTop: i ? '1px solid var(--line-1)' : 'none',
                  background: entry.is_you ? 'var(--paper-2)' : 'transparent',
                }}
              >
                <span className="t-xs mono fg-3" style={{ width: 18 }}>#{entry.rank}</span>
                <span className="t-sm fg-0" style={{ flex: 1, fontWeight: entry.is_you ? 600 : 400 }}>
                  {entry.name}{entry.is_you ? ' (you)' : ''}
                </span>
                <span className="t-xs fg-3 mono">{entry.xp.toLocaleString()} xp</span>
                {entry.streak > 0 && <span className="t-xs fg-2">{entry.streak}🔥</span>}
              </div>
            ))}
            {board.length === 0 && (
              <div className="t-xs fg-3" style={{ padding: '16px 14px', textAlign: 'center' }}>Loading leaderboard…</div>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}
